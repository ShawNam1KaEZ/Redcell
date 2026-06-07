import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap, useMapEvents, CircleMarker, ZoomControl } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './App.css';

const API_BASE = 'http://localhost:8000';
const TODAY_MS = new Date('2026-06-06').getTime();
const MAX_DONOR_MARKERS = 500;

// ── Types ─────────────────────────────────────────────────────────────────────

interface PatientRow {
  patient_id: string;
  abo: string;
  rhd: string;
  sex?: string;
  latitude: string;
  longitude: string;
  expected_transfusion_date: string;
  home_facility_id: string;
  immunized?: string;
  diagnosis?: string;
  [key: string]: string | undefined;
}

interface DonorRow {
  donor_id: string;
  abo: string;
  rhd: string;
  latitude: string;
  longitude: string;
  eligibility_status: string;
  home_bank_id: string;
  donor_type?: string;
  active_status?: string;
  donation_count?: string;
  last_donation_date?: string;
}

interface MapPoint {
  id: string;
  type: 'bank' | 'facility';
  name: string;
  latitude: number;
  longitude: number;
  available_bags?: number;
  patient_ids?: string[];
}

interface InventoryMap {
  [bankId: string]: { [bloodType: string]: number };
}

interface Candidate {
  bag_id: string;
  donor_id: string;
  abo: string;
  rhd: string;
  donor_typed: boolean;
  phenotype_concordance: number;
  distance_km: number | null;
  eta_minutes: number | null;
  is_long_haul: boolean;
  risk_flags: string[];
  expiry_date: string;
  current_location_id: string;
}

interface MatchResult {
  patient_id: string;
  G1: Candidate[];
  G2: Candidate[];
  G3: Candidate[];
  excluded: Array<{ bag_id: string; donor_id: string; reason: string }>;
}

interface ForecastEntry {
  initial_stock: number;
  days_to_depletion: number;
  shortage_severity: 'CRITICAL' | 'WARNING' | 'STABLE';
}

interface ForecastMap {
  [bankId: string]: { [bloodType: string]: ForecastEntry };
}

interface LogEntry {
  id: number;
  timestamp: string;
  action_type: string;
  actor: string;
  description: string;
  affected_ids: string | null;
}

// ── Icons (created once, outside component) ───────────────────────────────────

const bankIcon = L.divIcon({
  className: '',
  html: `<div style="width:26px;height:26px;border-radius:50%;background:#dc2626;border:2.5px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.2);display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:800;">B</div>`,
  iconSize: [26, 26], iconAnchor: [13, 13], popupAnchor: [0, -16],
});

const bankEmptyIcon = L.divIcon({
  className: '',
  html: `<div style="width:20px;height:20px;border-radius:50%;background:#e5e7eb;border:2px solid #9ca3af;box-shadow:0 1px 4px rgba(0,0,0,.1);display:flex;align-items:center;justify-content:center;color:#6b7280;font-size:10px;font-weight:700;">B</div>`,
  iconSize: [20, 20], iconAnchor: [10, 10], popupAnchor: [0, -13],
});

const facilityIcon = L.divIcon({
  className: '',
  html: `<div style="width:26px;height:26px;border-radius:5px;background:#2563eb;border:2.5px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.2);display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:800;">H</div>`,
  iconSize: [26, 26], iconAnchor: [13, 13], popupAnchor: [0, -16],
});

const donorIcon = L.divIcon({
  className: '',
  html: `<div style="width:10px;height:10px;border-radius:50%;background:#16a34a;border:1.5px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.2);"></div>`,
  iconSize: [10, 10], iconAnchor: [5, 5], popupAnchor: [0, -8],
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function daysUntil(dateStr: string): number {
  return Math.ceil((new Date(dateStr).getTime() - TODAY_MS) / 86400000);
}

function bloodLabel(abo: string, rhd: string): string {
  return `${abo}${rhd === 'pos' ? '+' : rhd === 'neg' ? '−' : rhd}`;
}

function phenoEntries(row: PatientRow): Array<{ key: string; val: string }> {
  return Object.entries(row)
    .filter(([k, v]) => k.startsWith('phenotype_') && v !== '' && v !== undefined)
    .map(([k, v]) => ({ key: k.replace('phenotype_', ''), val: v as string }));
}

// ── FlyController — must live inside MapContainer ─────────────────────────────

function FlyController({ target }: { target: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (target) map.flyTo(target, 14, { duration: 1.1 });
  }, [target, map]);
  return null;
}

function MapEventsHandler({ onZoomChange }: { onZoomChange: (zoom: number) => void }) {
  const map = useMapEvents({
    zoomend: () => {
      onZoomChange(map.getZoom());
    },
  });
  return null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function App() {
  // Roster state
  const [rosterTab, setRosterTab] = useState<'patients' | 'donors' | 'banks'>('patients');
  const [searchQuery, setSearchQuery] = useState('');
  const [patientsList, setPatientsList] = useState<PatientRow[]>([]);
  const [donorsList, setDonorsList] = useState<DonorRow[]>([]);

  // Selection & map fly-to
  const [selectedPatient, setSelectedPatient] = useState<PatientRow | null>(null);
  const [selectedDonorId, setSelectedDonorId] = useState<string | null>(null);
  const [flyTarget, setFlyTarget] = useState<[number, number] | null>(null);

  // Map data & filters
  const [mapPoints, setMapPoints] = useState<MapPoint[]>([]);
  const [showEmptyBanks, setShowEmptyBanks] = useState(false);
  const [showDonors, setShowDonors] = useState(false);

  // Inventory
  const [inventory, setInventory] = useState<InventoryMap>({});
  const [totalAvailable, setTotalAvailable] = useState(0);

  // Match
  const [matchResult, setMatchResult] = useState<MatchResult | null>(null);
  const [matchLoading, setMatchLoading] = useState(false);

  // Forecast
  const [forecastData, setForecastData] = useState<ForecastMap>({});

  // Logs
  const [logs, setLogs] = useState<LogEntry[]>([]);

  // UI
  const [notification, setNotification] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);

  // Donate form (collapsed)
  const [donorIdInput, setDonorIdInput] = useState('');
  const [bankIdInput, setBankIdInput] = useState('');
  const [donationAbo, setDonationAbo] = useState('');
  const [donationRhd, setDonationRhd] = useState('');
  const [donating, setDonating] = useState(false);

  // Map zoom tracking
  const [currentZoom, setCurrentZoom] = useState(12);

  // Facility popup tab tracking
  const [facilityPopupTab, setFacilityPopupTab] = useState<Record<string, 'patients' | 'blood'>>({});

  const logBodyRef = useRef<HTMLDivElement>(null);

  // ── Helpers ───────────────────────────────────────────────────────────────────

  const showNotification = useCallback((msg: string) => {
    setNotification(msg);
    setTimeout(() => setNotification(null), 4000);
  }, []);

  // ── Fetch functions ───────────────────────────────────────────────────────────

  const fetchInventory = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/inventory`);
      const data: InventoryMap = await res.json();
      setInventory(data);
      const total = Object.values(data).reduce(
        (sum, btMap) => sum + Object.values(btMap).reduce((s, n) => s + n, 0), 0
      );
      setTotalAvailable(total);
    } catch {}
  }, []);

  const fetchMapData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/map-data`);
      setMapPoints(await res.json());
    } catch {}
  }, []);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/logs`);
      setLogs(await res.json());
    } catch {}
  }, []);

  const fetchForecast = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/forecast`);
      setForecastData(await res.json());
    } catch {}
  }, []);

  const fetchPatients = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/patients`);
      if (!res.ok) {
        console.error('Fetch patients error:', res.status, res.statusText);
        setPatientsList([]);
        return;
      }
      const data = await res.json();
      const patients = Array.isArray(data) ? data : (data.patients || []);
      // Ensure coordinates are parsed as floats
      const validated = patients.map((p: PatientRow) => ({
        ...p,
        latitude: String(parseFloat(p.latitude) || 0),
        longitude: String(parseFloat(p.longitude) || 0),
      }));
      setPatientsList(validated);
    } catch (err) {
      console.error('Error fetching patients:', err);
      setPatientsList([]);
    }
  }, []);

  const fetchDonors = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/donors`);
      if (!res.ok) {
        console.error('Fetch donors error:', res.status, res.statusText);
        setDonorsList([]);
        return;
      }
      const data = await res.json();
      const donors = Array.isArray(data) ? data : (data.donors || []);
      // Ensure coordinates are parsed as floats
      const validated = donors.map((d: DonorRow) => ({
        ...d,
        latitude: String(parseFloat(d.latitude) || 0),
        longitude: String(parseFloat(d.longitude) || 0),
      }));
      setDonorsList(validated);
    } catch (err) {
      console.error('Error fetching donors:', err);
      setDonorsList([]);
    }
  }, []);

  const fetchMatch = useCallback(async (pid: string) => {
    if (!pid.trim()) return;
    setMatchLoading(true);
    setMatchResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/patient/${encodeURIComponent(pid.trim())}/match`);
      if (!res.ok) {
        const err = await res.json() as { detail?: string };
        showNotification(`Match error: ${err.detail ?? res.statusText}`);
      } else {
        setMatchResult(await res.json());
      }
    } catch { showNotification('Network error fetching match.'); }
    finally { setMatchLoading(false); }
  }, [showNotification]);

  // ── Action handlers ───────────────────────────────────────────────────────────

  const handleReset = async () => {
    setResetting(true);
    try {
      const res = await fetch(`${API_BASE}/api/state/reset`, { method: 'POST' });
      const data = await res.json() as { available_bags: number };
      showNotification(`Reset complete — ${data.available_bags} units restored`);
      await Promise.all([fetchInventory(), fetchMapData(), fetchLogs()]);
      if (matchResult) await fetchMatch(matchResult.patient_id);
    } catch { showNotification('Reset failed — is the server running?'); }
    finally { setResetting(false); }
  };

  const handleIssue = async (pid: string, bagId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/actions/treat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patient_id: pid, bag_id: bagId }),
      });
      if (!res.ok) {
        const err = await res.json() as { detail?: string };
        showNotification(`Issue failed: ${err.detail ?? res.statusText}`);
        return;
      }
      showNotification(`Issued ${bagId} → ${pid}`);
      // Re-trigger the primary data loaders to update the map canvas and sidebar live
      await fetchInventory();
      await fetchMapData();
      await fetchLogs();
      if (selectedPatient) {
        await fetchMatch(selectedPatient.patient_id);
      }
    } catch { showNotification('Network error issuing unit.'); }
  };

  const handleDonate = async () => {
    if (!donorIdInput || !bankIdInput || !donationAbo || !donationRhd) return;
    setDonating(true);
    try {
      const res = await fetch(`${API_BASE}/api/actions/donate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ donor_id: donorIdInput, bank_id: bankIdInput, abo: donationAbo, rhd: donationRhd }),
      });
      if (!res.ok) {
        const err = await res.json() as { detail?: string };
        showNotification(`Donation failed: ${err.detail ?? res.statusText}`);
      } else {
        const data = await res.json() as { bag_id: string };
        showNotification(`Registered ${data.bag_id}`);
        setDonorIdInput(''); setBankIdInput(''); setDonationAbo(''); setDonationRhd('');
        await Promise.all([fetchInventory(), fetchMapData(), fetchLogs()]);
      }
    } catch { showNotification('Network error registering donation.'); }
    finally { setDonating(false); }
  };

  const handleMobilizeRequest = (donorId: string) => {
    console.log(`[mobilize-request] Donor: ${donorId}, Timestamp: ${new Date().toISOString()}`);
    showNotification(`Mobilization request queued for ${donorId}`);
  };

  // ── Effects ───────────────────────────────────────────────────────────────────

  useEffect(() => {
    fetchInventory();
    fetchMapData();
    fetchLogs();
    fetchForecast();
    fetchPatients();
    fetchDonors();
  }, [fetchInventory, fetchMapData, fetchLogs, fetchForecast, fetchPatients, fetchDonors]);

  useEffect(() => {
    const id = setInterval(fetchLogs, 5000);
    return () => clearInterval(id);
  }, [fetchLogs]);

  useEffect(() => {
    if (logBodyRef.current) logBodyRef.current.scrollTop = 0;
  }, [logs]);

  useEffect(() => {
    if (selectedPatient) fetchMatch(selectedPatient.patient_id);
  }, [selectedPatient, fetchMatch]);

  // ── Derived data ──────────────────────────────────────────────────────────────

  const criticalAlerts = useMemo(() => {
    return Object.entries(forecastData)
      .flatMap(([bankId, btMap]) =>
        Object.entries(btMap)
          .filter(([, info]) =>
            (info.shortage_severity === 'CRITICAL' || info.shortage_severity === 'WARNING') &&
            info.initial_stock > 0
          )
          .map(([bloodType, info]) => ({ bankId, bloodType, ...info }))
      )
      .sort((a, b) => a.days_to_depletion - b.days_to_depletion)
      .slice(0, 6);
  }, [forecastData]);

  const filteredPatients = useMemo(() => {
    const list = Array.isArray(patientsList) ? patientsList : [];
    const q = searchQuery.toLowerCase();
    return list
      .filter(p =>
        !q ||
        p.patient_id.toLowerCase().includes(q) ||
        bloodLabel(p.abo, p.rhd).toLowerCase().includes(q) ||
        (p.home_facility_id ?? '').toLowerCase().includes(q)
      )
      .sort((a, b) => daysUntil(a.expected_transfusion_date) - daysUntil(b.expected_transfusion_date));
  }, [patientsList, searchQuery]);

  const filteredDonors = useMemo(() => {
    const list = Array.isArray(donorsList) ? donorsList : [];
    const q = searchQuery.toLowerCase();
    return list.filter(d =>
      !q ||
      d.donor_id.toLowerCase().includes(q) ||
      bloodLabel(d.abo, d.rhd).toLowerCase().includes(q) ||
      d.eligibility_status.toLowerCase().includes(q)
    );
  }, [donorsList, searchQuery]);

  const filteredBanks = useMemo(() => {
    const list = Array.isArray(mapPoints) ? mapPoints : [];
    const q = searchQuery.toLowerCase();
    return list
      .filter(p => p.type === 'bank')
      .filter(p => !q || p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q));
  }, [mapPoints, searchQuery]);

  const visibleBanks = useMemo(() => {
    const list = Array.isArray(mapPoints) ? mapPoints : [];
    return list.filter(p => p.type === 'bank' && (showEmptyBanks || (p.available_bags ?? 0) > 0));
  }, [mapPoints, showEmptyBanks]);

  const facilities = useMemo(() => {
    const list = Array.isArray(mapPoints) ? mapPoints : [];
    return list.filter(p => p.type === 'facility');
  }, [mapPoints]);

  const patientsByFacility = useMemo(() => {
    const list = Array.isArray(patientsList) ? patientsList : [];
    const map: Record<string, number> = {};
    list.forEach(p => {
      if (p.home_facility_id) map[p.home_facility_id] = (map[p.home_facility_id] ?? 0) + 1;
    });
    return map;
  }, [patientsList]);

  // Limit donor markers for performance
  const donorMarkers = useMemo(() => {
    const list = Array.isArray(donorsList) ? donorsList : [];
    return list
      .filter(d => {
        const lat = parseFloat(d.latitude);
        const lon = parseFloat(d.longitude);
        return !isNaN(lat) && !isNaN(lon);
      })
      .slice(0, MAX_DONOR_MARKERS);
  }, [donorsList]);

  const HYDBD: [number, number] = [17.385, 78.487];

  // ── Sub-renderers ─────────────────────────────────────────────────────────────────

  const formatBloodType = (rawType: string): string => {
    // Convert database format (e.g., 'Opos', 'ABneg') to display format (e.g., 'O+', 'AB−')
    let display = rawType.replace('pos', '+').replace('neg', '−');
    return display;
  };

  const buildInventoryTable = (bankId: string) => {
    const btMap = inventory[bankId] || {};
    const bloodTypes = ['Opos', 'Oneg', 'Apos', 'Aneg', 'Bpos', 'Bneg', 'ABpos', 'ABneg'];
    
    return (
      <div className="stock-grid">
        {bloodTypes.map(bt => {
          const count = btMap[bt] || 0;
          return (
            <div key={bt} className="stock-item">
              <span className="stock-type">{formatBloodType(bt)}</span>
              <span className={`stock-count ${count === 0 ? 'zero' : 'active'}`}>{count}</span>
            </div>
          );
        })}
      </div>
    );
  };

  const renderCandidate = (c: Candidate, tier: string, pid: string) => (
    <div key={c.bag_id} className={`cand tier-${tier.toLowerCase()}`}>
      <div className="cand-row">
        <span className="cand-id">{c.bag_id}</span>
        <span className="cand-bt">{bloodLabel(c.abo, c.rhd)}</span>
        {c.distance_km !== null && <span className="cand-metric">{c.distance_km.toFixed(1)} km</span>}
        {c.eta_minutes !== null && <span className="cand-metric">{c.eta_minutes} min</span>}
        <span className="bag-location-tag">📍 {c.current_location_id || 'Local Hub'}</span>
        <span className={`typed-pill ${c.donor_typed ? 'yes' : 'no'}`}>
          {c.donor_typed ? 'Typed' : 'Untyped'}
        </span>
        {c.phenotype_concordance > 0 && (
          <span className="cand-metric">{(c.phenotype_concordance * 100).toFixed(0)}%</span>
        )}
        <span className="cand-exp">exp {c.expiry_date}</span>
        {tier !== 'G3' && (
          <button className="issue-btn" onClick={() => handleIssue(pid, c.bag_id)}>
            Issue Unit
          </button>
        )}
      </div>
      {c.risk_flags.length > 0 && (
        <div className="cand-flags">
          {c.risk_flags.map(f => <span key={f} className="flag">{f}</span>)}
        </div>
      )}
    </div>
  );

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="app">
      {notification && <div className="notif">{notification}</div>}

      {/* Header */}
      <header className="hdr">
        <div className="hdr-brand">
          <span className="hdr-logo">⬡</span>
          <span className="hdr-title">HemoGrid</span>
          <span className="hdr-sub">Thalassemia Matching · Hyderabad</span>
        </div>
        <div className="hdr-right">
          <div className="live-pill">
            <span className="live-dot" />
            <span className="live-num">{totalAvailable}</span>
            <span className="live-lbl">units available</span>
          </div>
          <button className="reset-btn" onClick={handleReset} disabled={resetting}>
            {resetting ? 'Resetting…' : 'Reset Simulation'}
          </button>
        </div>
      </header>

      {/* 3-column main */}
      <main className="app-main">

        {/* ── LEFT PANEL: Search & Roster ── */}
        <aside className="left-panel">
          <div className="roster-tabs">
            {(['patients', 'donors', 'banks'] as const).map(tab => (
              <button
                key={tab}
                className={`roster-tab ${rosterTab === tab ? 'active' : ''}`}
                onClick={() => { setRosterTab(tab); setSearchQuery(''); }}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
                <span className="rtab-count">
                  {tab === 'patients' ? patientsList.length
                    : tab === 'donors' ? donorsList.length
                    : filteredBanks.length}
                </span>
              </button>
            ))}
          </div>

          <div className="search-box-wrap">
            <input
              className="search-box"
              placeholder={`Search ${rosterTab}…`}
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
          </div>

          <div className="roster-list">
            {rosterTab === 'patients' && filteredPatients.map(p => {
              const days = daysUntil(p.expected_transfusion_date);
              const isUrgent = days <= 3;
              const isSelected = selectedPatient?.patient_id === p.patient_id;
              return (
                <div
                  key={p.patient_id}
                  className={`roster-card${isUrgent ? ' urgent' : ''}${isSelected ? ' selected' : ''}`}
                  onClick={() => {
                    setSelectedPatient(p);
                    setSelectedDonorId(null);
                    setFlyTarget([parseFloat(p.latitude), parseFloat(p.longitude)]);
                  }}
                >
                  <div className="rc-top">
                    <span className="rc-id">{p.patient_id}</span>
                    <span className="rc-bt">{bloodLabel(p.abo, p.rhd)}</span>
                  </div>
                  <div className="rc-bottom">
                    <span className={`rc-days${days <= 1 ? ' critical' : days <= 3 ? ' warning' : ''}`}>
                      {days <= 0 ? 'Today' : `${days}d`}
                    </span>
                    <span className="rc-meta">{p.home_facility_id}</span>
                  </div>
                </div>
              );
            })}

            {rosterTab === 'donors' && filteredDonors.map(d => {
              const eligible = d.eligibility_status === 'eligible';
              const isSelected = selectedDonorId === d.donor_id;
              return (
                <div
                  key={d.donor_id}
                  className={`roster-card${isSelected ? ' selected' : ''}`}
                  onClick={() => {
                    setSelectedDonorId(d.donor_id);
                    setSelectedPatient(null);
                    setMatchResult(null);
                    setFlyTarget([parseFloat(d.latitude), parseFloat(d.longitude)]);
                  }}
                >
                  <div className="rc-top">
                    <span className="rc-id">{d.donor_id}</span>
                    <span className="rc-bt">{bloodLabel(d.abo, d.rhd)}</span>
                  </div>
                  <div className="rc-bottom">
                    <span className={`rc-status ${eligible ? 'eligible' : 'ineligible'}`}>
                      {d.eligibility_status}
                    </span>
                    <span className="rc-meta">{d.donor_type ?? ''}</span>
                  </div>
                </div>
              );
            })}

            {rosterTab === 'banks' && filteredBanks.map(b => (
              <div
                key={b.id}
                className="roster-card"
                onClick={() => setFlyTarget([b.latitude, b.longitude])}
              >
                <div className="rc-top">
                  <span className="rc-id">{b.id}</span>
                  <span className={`rc-bags${(b.available_bags ?? 0) === 0 ? ' empty' : ''}`}>
                    {b.available_bags ?? 0} units
                  </span>
                </div>
                <div className="rc-bottom">
                  <span className="rc-meta rc-name">{b.name}</span>
                </div>
              </div>
            ))}
          </div>
        </aside>

        {/* ── CENTER: Map ── */}
        <section className="map-panel">
          <div className="map-controls">
            <label className="map-ctrl-label">
              <input
                type="checkbox"
                checked={showEmptyBanks}
                onChange={e => setShowEmptyBanks(e.target.checked)}
              />
              Show Empty Blood Banks
            </label>
            <label className="map-ctrl-label">
              <input
                type="checkbox"
                checked={showDonors}
                onChange={e => setShowDonors(e.target.checked)}
              />
              Show Local Donors
            </label>
          </div>

          <MapContainer center={HYDBD} zoom={10} style={{ height: '100%', width: '100%' }} zoomControl={false}>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
            />
            <ZoomControl position="topright" />
            <FlyController target={flyTarget} />
            <MapEventsHandler onZoomChange={setCurrentZoom} />

            {/* Blood banks */}
            {visibleBanks.map(pt => (
              <Marker
                key={pt.id}
                position={[pt.latitude, pt.longitude]}
                icon={(pt.available_bags ?? 0) > 0 ? bankIcon : bankEmptyIcon}
              >
                <Popup>
                  <div className="popup-box">
                    <strong className="popup-name">{pt.name}</strong>
                    <div className="popup-meta">
                      <span className="popup-kind bank">Blood Bank</span>
                      <code className="popup-id">{pt.id}</code>
                    </div>
                    <div className="popup-inv">
                      <div className="popup-inv-lbl">Available Stock</div>
                      {buildInventoryTable(pt.id)}
                    </div>
                  </div>
                </Popup>
              </Marker>
            ))}

            {/* Treatment facilities */}
            {facilities.map(pt => {
              const activeTab = facilityPopupTab[pt.id] ?? 'patients';
              const patientCount = patientsByFacility[pt.id] ?? 0;
              const facilityInventory = inventory[pt.id] || {};
              const bloodTypes = ['Opos', 'Oneg', 'Apos', 'Aneg', 'Bpos', 'Bneg', 'ABpos', 'ABneg'];
              
              return (
                <Marker key={pt.id} position={[pt.latitude, pt.longitude]} icon={facilityIcon}>
                  <Popup>
                    <div className="popup-box">
                      <strong className="popup-name">{pt.name}</strong>
                      <div className="popup-meta">
                        <span className="popup-kind facility">Treatment Facility</span>
                        <code className="popup-id">{pt.id}</code>
                      </div>
                      <div className="popup-stat">
                        <span className="popup-stat-lbl">Active Patients:</span>
                        <strong className="popup-stat-val">{patientCount}</strong>
                      </div>

                      {/* Tab switcher */}
                      <div className="popup-tab-bar">
                        <button
                          className={`popup-tab-btn ${activeTab === 'patients' ? 'active' : ''}`}
                          onClick={() => setFacilityPopupTab({...facilityPopupTab, [pt.id]: 'patients'})}
                        >
                          Patients
                        </button>
                        <button
                          className={`popup-tab-btn ${activeTab === 'blood' ? 'active' : ''}`}
                          onClick={() => setFacilityPopupTab({...facilityPopupTab, [pt.id]: 'blood'})}
                        >
                          Available Blood
                        </button>
                      </div>

                      {/* Tab content: Patients */}
                      {activeTab === 'patients' && (() => {
                        // Defensive fallback: if pt.patient_ids doesn't exist, calculate it live by filtering the global patientsList
                        const activeIds = pt.patient_ids || (Array.isArray(patientsList) ? 
                          patientsList
                            .filter(p => p.home_facility_id === pt.id || p.facility_id === pt.id)
                            .map(p => p.patient_id)
                          : []);
                        
                        return (
                          <div className="popup-patient-list">
                            {activeIds && activeIds.length > 0 ? (
                              <>
                                <div className="popup-list-hdr">Registered Patients ({activeIds.length})</div>
                                <div className="popup-scroll-container">
                                  {activeIds.map((pid: string) => {
                                    const patient = patientsList.find(x => x.patient_id === pid);
                                    const bloodType = patient ? bloodLabel(patient.abo, patient.rhd) : '?';
                                    return (
                                      <button
                                        key={pid}
                                        className="popup-patient-link"
                                        onClick={() => {
                                          if (patient) {
                                            setSelectedPatient(patient);
                                            setSelectedDonorId(null);
                                            setFlyTarget([parseFloat(patient.latitude), parseFloat(patient.longitude)]);
                                          }
                                        }}
                                      >
                                        {pid} <span className="popup-patient-bt">[{bloodType}]</span>
                                      </button>
                                    );
                                  })}
                                </div>
                              </>
                            ) : (
                              <div className="empty-msg">No patients assigned.</div>
                            )}
                          </div>
                        );
                      })()}

                      {/* Tab content: Available Blood */}
                      {activeTab === 'blood' && (
                        <div className="popup-inv">
                          <div className="popup-inv-lbl">Available Stock</div>
                          <div className="stock-grid">
                            {bloodTypes.map(bt => {
                              const count = facilityInventory[bt] || 0;
                              const label = bt.replace('pos', '+').replace('neg', '−');
                              return (
                                <div key={bt} className="stock-item">
                                  <span className="stock-type">{label}</span>
                                  <span className={`stock-count ${count === 0 ? 'zero' : 'active'}`}>{count}</span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  </Popup>
                </Marker>
              );
            })}

            {/* Donor layer (capped for performance) */}
            {showDonors && (Array.isArray(donorsList) ? donorsList : []).map(donor => {
              const lat = parseFloat(donor.latitude);
              const lng = parseFloat(donor.longitude);
              
              if (isNaN(lat) || isNaN(lng)) return null;

              // Dynamic radius based on zoom level for better visibility and clickability
              const dynamicRadius = currentZoom <= 11 ? 8 : currentZoom <= 13 ? 6 : 4;

              // Format blood type with proper symbols
              const formattedRh = donor.rhd === 'pos' || donor.rhd === 'Bpos' || String(donor.rhd).toLowerCase().includes('pos') ? '+' : '−';
              const displayBloodType = `${donor.abo}${formattedRh}`;

              return (
                <CircleMarker
                  key={donor.donor_id}
                  center={[lat, lng]}
                  radius={dynamicRadius}
                  pathOptions={{
                    color: '#10b981', // Medical emerald green
                    fillColor: '#10b981',
                    fillOpacity: 0.6,
                    weight: 2
                  }}
                >
                  <Popup>
                    <div className="popup-card">
                      <h4>Donor: {donor.donor_id}</h4>
                      <p><strong>Blood Type:</strong> {displayBloodType}</p>
                      <p><strong>Status:</strong> <span className={`status-badge badge-${donor.eligibility_status.replace(' ', '-')}`}>{donor.eligibility_status}</span></p>
                      <p><strong>Total Donations:</strong> {donor.donation_count || 0}</p>
                      <p><strong>Last Active:</strong> {donor.last_donation_date || 'N/A'}</p>
                      <button className="btn-mobilize" onClick={() => handleMobilizeRequest(donor.donor_id)}>Mobilize Donor</button>
                      <details className="popup-details">
                        <summary className="details-summary">View More Details</summary>
                        <div className="details-body">
                          <p><strong>Registration Date:</strong> {donor.registration_date || 'N/A'}</p>
                          <p><strong>Donor Subtype:</strong> {donor.donor_subtype || 'Voluntary'}</p>
                          <p><strong>Contact:</strong> {donor.email || 'No email registered'}</p>
                        </div>
                      </details>
                    </div>
                  </Popup>
                </CircleMarker>
              );
            })}
          </MapContainer>
        </section>

        {/* ── RIGHT PANEL: Action Engine ── */}
        <aside className="right-panel">

          {selectedPatient ? (
            <div className="patient-ctx">
              {/* Demographic card */}
              <div className="ctx-card">
                <div className="ctx-card-top">
                  <span className="ctx-pid">{selectedPatient.patient_id}</span>
                  <span className="ctx-bt">{bloodLabel(selectedPatient.abo, selectedPatient.rhd)}</span>
                  {selectedPatient.immunized === 'True' && (
                    <span className="ctx-badge immunized">Immunized</span>
                  )}
                </div>
                <div className="ctx-card-row">
                  <span className="ctx-lbl">Facility</span>
                  <span className="ctx-val">{selectedPatient.home_facility_id}</span>
                </div>
                {selectedPatient.diagnosis && (
                  <div className="ctx-card-row">
                    <span className="ctx-lbl">Diagnosis</span>
                    <span className="ctx-val">{selectedPatient.diagnosis}</span>
                  </div>
                )}
                <div className="ctx-card-row">
                  <span className="ctx-lbl">Transfusion</span>
                  <span className={`ctx-val${daysUntil(selectedPatient.expected_transfusion_date) <= 3 ? ' urgent-text' : ''}`}>
                    {selectedPatient.expected_transfusion_date}&nbsp;
                    <span className="ctx-days-badge">
                      {daysUntil(selectedPatient.expected_transfusion_date)}d
                    </span>
                  </span>
                </div>
              </div>

              {/* Antigen profile */}
              {phenoEntries(selectedPatient).length > 0 && (
                <div className="antigen-profile">
                  <div className="ap-hdr">Extended Antigen Profile</div>
                  <div className="ap-grid">
                    {phenoEntries(selectedPatient).map(({ key, val }) => (
                      <div key={key} className={`ap-cell ${val === 'pos' ? 'pos' : val === 'neg' ? 'neg' : 'unk'}`}>
                        <span className="ap-ag">{key}</span>
                        <span className="ap-val">{val === 'pos' ? '+' : val === 'neg' ? '−' : val}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Match results */}
              <div className="match-section">
                {matchLoading && <div className="loading-msg">Running match pipeline…</div>}
                {matchResult && matchResult.patient_id === selectedPatient.patient_id && (
                  <>
                    <div className="match-summary">
                      <span className="tbadge g1">{matchResult.G1.length} G1</span>
                      <span className="tbadge g2">{matchResult.G2.length} G2</span>
                      <span className="tbadge g3">{matchResult.G3.length} G3</span>
                      <span className="tbadge ex">{matchResult.excluded.length} excl</span>
                    </div>
                    {matchResult.G1.length > 0 && (
                      <div className="tier-sec">
                        <div className="tier-hdr g1-hdr">G1 — Exact Match</div>
                        {matchResult.G1.map(c => renderCandidate(c, 'G1', matchResult.patient_id))}
                      </div>
                    )}
                    {matchResult.G2.length > 0 && (
                      <div className="tier-sec">
                        <div className="tier-hdr g2-hdr">G2 — Compatible</div>
                        {matchResult.G2.map(c => renderCandidate(c, 'G2', matchResult.patient_id))}
                      </div>
                    )}
                    {matchResult.G3.length > 0 && (
                      <div className="tier-sec">
                        <div className="tier-hdr g3-hdr">G3 — Emergency (Review Required)</div>
                        {matchResult.G3.map(c => renderCandidate(c, 'G3', matchResult.patient_id))}
                      </div>
                    )}
                    {matchResult.G1.length === 0 &&
                     matchResult.G2.length === 0 &&
                     matchResult.G3.length === 0 && (
                      <div className="empty-msg">No compatible units found.</div>
                    )}
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="no-selection">
              <div className="no-sel-icon">⬡</div>
              <div className="no-sel-text">
                Select a patient from the roster to run the matching pipeline
              </div>
            </div>
          )}

          {/* Critical stock alerts */}
          {criticalAlerts.length > 0 && (
            <div className="forecast-alerts">
              <div className="fa-hdr">Critical Stock Alerts</div>
              {criticalAlerts.map(r => (
                <div key={`${r.bankId}-${r.bloodType}`} className="fa-row">
                  <span className="fa-sev">CRIT</span>
                  <span className="fa-bt">{r.bloodType}</span>
                  <span className="fa-bank">{r.bankId}</span>
                  <span className="fa-days">{r.days_to_depletion}d left</span>
                </div>
              ))}
            </div>
          )}

          {/* Simulate donation (collapsible) */}
          <details className="donate-section">
            <summary className="donate-toggle">
              Simulate Walk-in Donation
            </summary>
            <div className="donate-form">
              <input className="d-in" placeholder="DNR-#####" value={donorIdInput}
                onChange={e => setDonorIdInput(e.target.value)} />
              <input className="d-in" placeholder="BNK-#####" value={bankIdInput}
                onChange={e => setBankIdInput(e.target.value)} />
              <div className="d-row">
                <select className="d-sel" value={donationAbo} onChange={e => setDonationAbo(e.target.value)}>
                  <option value="">ABO</option>
                  {['O', 'A', 'B', 'AB'].map(a => <option key={a} value={a}>{a}</option>)}
                </select>
                <select className="d-sel" value={donationRhd} onChange={e => setDonationRhd(e.target.value)}>
                  <option value="">Rh</option>
                  <option value="pos">+</option>
                  <option value="neg">−</option>
                </select>
                <button
                  className="donate-btn"
                  onClick={handleDonate}
                  disabled={donating || !donorIdInput || !bankIdInput || !donationAbo || !donationRhd}
                >
                  {donating ? '…' : 'Donate'}
                </button>
              </div>
            </div>
          </details>

          {/* Activity ticker */}
          <div className="ticker">
            <div className="ticker-hdr">
              <span className="live-dot" />
              Live Activity
            </div>
            <div className="ticker-body" ref={logBodyRef}>
              {logs.length === 0
                ? <div className="empty-msg">No activity yet.</div>
                : logs.map(entry => (
                  <div key={entry.id} className="te">
                    <span className="te-time">
                      {new Date(entry.timestamp).toLocaleTimeString([], {
                        hour: '2-digit', minute: '2-digit', second: '2-digit',
                      })}
                    </span>
                    <span className={`te-type t-${entry.action_type}`}>{entry.action_type}</span>
                    <span className="te-desc">{entry.description}</span>
                  </div>
                ))
              }
            </div>
          </div>
        </aside>

      </main>
    </div>
  );
}
