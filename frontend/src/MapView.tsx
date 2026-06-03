import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, Marker, Popup, CircleMarker, Tooltip } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import markerIconUrl from 'leaflet/dist/images/marker-icon.png?url'
import markerIcon2xUrl from 'leaflet/dist/images/marker-icon-2x.png?url'
import markerShadowUrl from 'leaflet/dist/images/marker-shadow.png?url'
import {
  fetchBanks,
  fetchDeserts,
  fetchDuePatients,
  fetchMatch,
  type BankSummary,
  type DesertCell,
  type MatchResult,
  type PatientSummary,
} from './api'
import './MapView.css'

// Fix: Vite's bundler breaks Leaflet's internal CSS url() resolution for the
// default marker icons. Delete the prototype getter and set explicit asset URLs.
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)['_getIconUrl']
L.Icon.Default.mergeOptions({
  iconUrl: markerIconUrl,
  iconRetinaUrl: markerIcon2xUrl,
  shadowUrl: markerShadowUrl,
})

const makeCircle = (color: string) =>
  L.divIcon({
    className: '',
    html: `<div class="hg-marker" style="background:${color}"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
    popupAnchor: [0, -10],
  })

const ICON_COMPONENT = makeCircle('#d32f2f') // red — does_components=true
const ICON_STANDARD  = makeCircle('#1565c0') // blue — does_components=false

// India-level view: all 9 desert cells span Lucknow → Chennai → Kolkata.
// Guntur banks are still accessible by zooming into AP (~16.3, 80.44).
const INDIA_CENTER: [number, number] = [22.5, 80.0]
const INDIA_ZOOM = 5

const DESERT_COLORS: Record<string, string> = {
  SUPPLY_LIMITED:        '#e65100',
  COMPATIBILITY_LIMITED: '#6a1b9a',
  MIXED:                 '#b71c1c',
  OK:                    '#9e9e9e',
}

const DESERT_LABELS: Record<string, string> = {
  SUPPLY_LIMITED:        'Supply desert',
  COMPATIBILITY_LIMITED: 'Compatibility desert',
  MIXED:                 'Mixed desert',
  OK:                    'No desert',
}

const DESERT_DESC: Record<string, string> = {
  SUPPLY_LIMITED:
    'Shelves too thin — demand exceeds available supply. Fix: redistribute units.',
  COMPATIBILITY_LIMITED:
    'Shelves stocked but not antibody-safe for these patients. Fix: activate phenotype-matched donors.',
  MIXED:
    'Both insufficient supply and antibody incompatibility.',
  OK:
    'Demand fully met with antibody-safe inventory.',
}

const LEVER_LABELS: Record<string, string> = {
  inventory:  'Redistribute inventory',
  donor:      'Activate donor',
  emergency:  'Emergency escalation',
}

const LEVER_COLORS: Record<string, string> = {
  inventory: '#1565c0',
  donor:     '#2e7d32',
  emergency: '#b71c1c',
}

function desertRadius(score: number): number {
  if (score === 0) return 7
  return Math.min(9 + score * 1.5, 44)
}

function desertFillOpacity(score: number, type: string): number {
  if (type === 'OK') return 0.28
  return Math.min(0.50 + score / 60, 0.82)
}

// Human-readable blood type string (e.g. "B+")
function bloodType(abo: string, rh_d: boolean): string {
  return `${abo}${rh_d ? '+' : '-'}`
}

// Summary of phenotype_tags for display — shows only present flags
function phenotypeSummary(ph: { K?: boolean | null } | null): string {
  if (!ph) return 'untyped'
  const tags: string[] = []
  if (ph.K === false) tags.push('K-neg')
  if (ph.K === true)  tags.push('K-pos')
  return tags.length ? tags.join(', ') : 'typed'
}

export function MapView() {
  const [banks, setBanks]           = useState<BankSummary[]>([])
  const [bankStatus, setBankStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [bankError, setBankError]   = useState('')

  const [deserts, setDeserts]           = useState<DesertCell[]>([])
  const [desertStatus, setDesertStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [desertError, setDesertError]   = useState('')

  const [showDeserts, setShowDeserts] = useState(true)
  const [showBanks, setShowBanks]     = useState(true)

  // Desert cell detail + patient matching state
  const [selected, setSelected]             = useState<DesertCell | null>(null)
  const [patients, setPatients]             = useState<PatientSummary[]>([])
  const [patientsLoading, setPatientsLoading] = useState(false)
  const [patientsError, setPatientsError]   = useState('')
  const [matchResult, setMatchResult]       = useState<MatchResult | null>(null)
  const [matchLoading, setMatchLoading]     = useState(false)
  const [matchError, setMatchError]         = useState('')
  const [showDetails, setShowDetails]       = useState(false)

  useEffect(() => {
    fetchBanks('Guntur')
      .then((data) => { setBanks(data); setBankStatus('ok') })
      .catch((err: Error) => { setBankError(err.message); setBankStatus('error') })
  }, [])

  useEffect(() => {
    fetchDeserts()
      .then((data) => { setDeserts(data); setDesertStatus('ok') })
      .catch((err: Error) => { setDesertError(err.message); setDesertStatus('error') })
  }, [])

  // Auto-fetch due patients when a desert cell is selected
  useEffect(() => {
    setPatients([])
    setMatchResult(null)
    setMatchError('')
    setShowDetails(false)
    if (!selected) return

    setPatientsLoading(true)
    setPatientsError('')
    fetchDuePatients(selected.cell_id)
      .then((data) => { setPatients(data); setPatientsLoading(false) })
      .catch((err: Error) => { setPatientsError(err.message); setPatientsLoading(false) })
  }, [selected])

  const handlePatientClick = (p: PatientSummary) => {
    setMatchResult(null)
    setMatchError('')
    setShowDetails(false)
    setMatchLoading(true)
    fetchMatch(p.patient_id)
      .then((data) => { setMatchResult(data); setMatchLoading(false) })
      .catch((err: Error) => { setMatchError(err.message); setMatchLoading(false) })
  }

  const componentCount = banks.filter((b) => b.does_components).length
  const desertCount    = deserts.filter((c) => c.desert_type !== 'OK').length

  return (
    <div className="map-wrapper">

      {/* Loading / error overlays */}
      {(bankStatus === 'loading' || desertStatus === 'loading') && (
        <div className="map-overlay map-loading">Loading…</div>
      )}
      {bankStatus === 'error' && (
        <div className="map-overlay map-error">
          Failed to load banks<br /><small>{bankError}</small>
        </div>
      )}
      {desertStatus === 'error' && (
        <div className="map-overlay map-error" style={{ top: '60%' }}>
          Failed to load desert data<br /><small>{desertError}</small>
        </div>
      )}

      {/* Layer toggles — top-right */}
      <div className="hg-toggles">
        <label>
          <input type="checkbox" checked={showDeserts}
            onChange={(e) => setShowDeserts(e.target.checked)} />
          Desert cells
        </label>
        <label>
          <input type="checkbox" checked={showBanks}
            onChange={(e) => setShowBanks(e.target.checked)} />
          Guntur banks
        </label>
      </div>

      {/* Legend — bottom-left */}
      <div className="hg-legend">
        <div className="hg-legend-title">Blood Desert Types</div>
        <div className="hg-legend-row">
          <span className="hg-legend-swatch" style={{ background: DESERT_COLORS.SUPPLY_LIMITED }} />
          <div>
            <strong>Supply desert</strong>
            <div className="hg-legend-sub">Shelf too thin — units needed</div>
          </div>
        </div>
        <div className="hg-legend-row">
          <span className="hg-legend-swatch" style={{ background: DESERT_COLORS.COMPATIBILITY_LIMITED }} />
          <div>
            <strong>Compatibility desert</strong>
            <div className="hg-legend-sub">Stocked but immunologically mismatched</div>
          </div>
        </div>
        <div className="hg-legend-row">
          <span className="hg-legend-swatch" style={{ background: DESERT_COLORS.OK }} />
          <div>
            <strong>No desert</strong>
            <div className="hg-legend-sub">Demand met with safe inventory</div>
          </div>
        </div>
        <div className="hg-legend-note">Circle size ∝ desert score · click cell to match</div>
      </div>

      {/* Bank / desert count — bottom-right */}
      <div className="map-count-box">
        {bankStatus === 'ok' && (
          <>
            <span className="dot dot-red" /> Component-capable ({componentCount})<br />
            <span className="dot dot-blue" /> Standard ({banks.length - componentCount})<br />
            <strong>{banks.length} Guntur banks</strong>
          </>
        )}
        {desertStatus === 'ok' && (
          <><br />{desertCount} desert cell{desertCount !== 1 ? 's' : ''} / {deserts.length} total</>
        )}
      </div>

      {/* ── Desert cell detail panel ────────────────────────────────────── */}
      {selected && (
        <div className="hg-detail">
          <button className="hg-detail-close" onClick={() => setSelected(null)}>×</button>

          {/* Cell header */}
          <div className="hg-detail-header"
            style={{ borderLeftColor: DESERT_COLORS[selected.desert_type] }}>
            <span className="hg-detail-badge"
              style={{ background: DESERT_COLORS[selected.desert_type] }}>
              {DESERT_LABELS[selected.desert_type]}
            </span>
            <div className="hg-detail-name">{selected.name}</div>
            <div className="hg-detail-id">{selected.cell_id}</div>
          </div>

          <div className="hg-detail-desc">{DESERT_DESC[selected.desert_type]}</div>

          {/* Desert numbers */}
          <table className="hg-detail-table">
            <tbody>
              <tr><td>Patients due</td><td>{selected.patients_due}</td></tr>
              <tr><td>Demand (D)</td><td>{selected.demand_units} units</td></tr>
              <tr className="hg-row-divider">
                <td>ABO/Rh-compatible (S_raw)</td><td>{selected.raw_units} units</td>
              </tr>
              <tr>
                <td>Antibody-safe (S_safe)</td>
                <td style={{
                  color: selected.safe_units < selected.raw_units
                    ? DESERT_COLORS.COMPATIBILITY_LIMITED : undefined,
                  fontWeight: selected.safe_units < selected.raw_units ? 600 : undefined,
                }}>
                  {selected.safe_units} units
                  {selected.safe_units < selected.raw_units &&
                    ` (−${selected.raw_units - selected.safe_units} lost to antibody gate)`}
                </td>
              </tr>
              <tr><td>Met</td><td>{selected.met} units</td></tr>
              {selected.compatibility_gap > 0 && (
                <tr className="hg-row-compat">
                  <td>Compatibility gap</td><td>−{selected.compatibility_gap} units</td>
                </tr>
              )}
              {selected.supply_gap > 0 && (
                <tr className="hg-row-supply">
                  <td>Supply gap</td><td>−{selected.supply_gap} units</td>
                </tr>
              )}
              <tr className="hg-row-score">
                <td>Desert score</td><td>{selected.desert_score}</td>
              </tr>
            </tbody>
          </table>

          <div className="hg-detail-clock">
            <strong>Clock ingredients</strong>&nbsp;(informational)<br />
            Nearest safe inventory:&nbsp;
            {selected.nearest_safe_inventory_km !== null
              ? `${selected.nearest_safe_inventory_km.toFixed(1)} km` : 'none'}<br />
            Eligible matched donors nearby:&nbsp;
            {selected.eligible_matched_donors_nearby}
          </div>

          {/* ── Due patients section ───────────────────────────────────── */}
          <div className="hg-patients-section">
            <div className="hg-patients-title">
              Due patients ({selected.patients_due})
              {patientsLoading && <span className="hg-loading-inline"> loading…</span>}
            </div>

            {patientsError && (
              <div className="hg-error-inline">{patientsError}</div>
            )}

            {patients.length > 0 && (
              <div className="hg-patient-list">
                {patients.map((p) => (
                  <button
                    key={p.patient_id}
                    className={`hg-patient-row ${matchResult?.patient_id === p.patient_id ? 'hg-patient-active' : ''}`}
                    onClick={() => handlePatientClick(p)}
                  >
                    <span className="hg-patient-id">
                      {p.patient_id}
                      {/* Demo highlight for Aarav — patient_id comes from API */}
                      {p.patient_id === 'PAT-0001' && (
                        <span className="hg-demo-tag">demo</span>
                      )}
                    </span>
                    <span className="hg-patient-type">{bloodType(p.abo, p.rh_d)}</span>
                    {p.known_antibodies.length > 0 && (
                      <span className="hg-patient-ab">{p.known_antibodies.join(', ')}</span>
                    )}
                    <span className="hg-patient-due">
                      {p.days_until_due === 0 ? 'today'
                        : p.days_until_due < 0 ? `${Math.abs(p.days_until_due)}d overdue`
                        : `in ${p.days_until_due}d`}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {/* ── Match result ───────────────────────────────────────── */}
            {matchLoading && (
              <div className="hg-match-loading">Computing match…</div>
            )}
            {matchError && (
              <div className="hg-error-inline">{matchError}</div>
            )}

            {matchResult && !matchLoading && (
              <div className="hg-match-result">
                <div className="hg-match-header">
                  <span className="hg-match-badge"
                    style={{ background: LEVER_COLORS[matchResult.chosen_lever] }}>
                    {LEVER_LABELS[matchResult.chosen_lever]}
                  </span>
                  <span className="hg-match-pid">{matchResult.patient_id}</span>
                  <span className="hg-match-blood">{bloodType(matchResult.abo, matchResult.rh_d)}</span>
                </div>

                {/* Minimal view — chosen unit or donor */}
                {matchResult.chosen_lever === 'inventory' && matchResult.chosen_inventory && (() => {
                  const inv = matchResult.chosen_inventory
                  return (
                    <div className="hg-match-chosen">
                      <div className="hg-match-chosen-main">
                        <strong>{inv.bank_id}</strong>
                        <span className="hg-match-dash"> — </span>
                        <span>{inv.bank_name}</span>
                      </div>
                      <div className="hg-match-chosen-facts">
                        {bloodType(inv.abo, inv.rh_d)} PRBC
                        {' · '}{phenotypeSummary(inv.phenotype_tags)}
                        {' · '}expires in {inv.days_to_expiry}d
                        {inv.distance_km !== null && ` · ${inv.distance_km} km`}
                      </div>
                      <div className="hg-match-inv-options">
                        {inv.inventory_options} compatible unit{inv.inventory_options !== 1 ? 's' : ''} in range
                      </div>
                    </div>
                  )
                })()}

                {matchResult.chosen_lever === 'donor' && matchResult.chosen_donor && (() => {
                  const don = matchResult.chosen_donor
                  return (
                    <div className="hg-match-chosen">
                      <div className="hg-match-chosen-main">
                        <strong>{don.donor_id}</strong>
                        {don.bonded && <span className="hg-bonded-tag">bonded</span>}
                      </div>
                      <div className="hg-match-chosen-facts">
                        {bloodType(don.abo, don.rh_d)}
                        {' · '}{don.distance_km} km
                        {' · '}reliability {don.reliability_score.toFixed(3)}
                        {' · '}score {don.score.toFixed(4)}
                      </div>
                      <div className="hg-match-inv-options">
                        {don.candidates_ranked} eligible donor{don.candidates_ranked !== 1 ? 's' : ''} ranked
                      </div>
                    </div>
                  )
                })()}

                {matchResult.chosen_lever === 'emergency' && (
                  <div className="hg-match-emergency">
                    No compatible inventory or eligible donor found within range.
                    Escalate to regional emergency network.
                  </div>
                )}

                {/* Why */}
                <div className="hg-match-reasoning">{matchResult.reasoning}</div>

                {/* Show details toggle */}
                <button
                  className="hg-details-toggle"
                  onClick={() => setShowDetails((v) => !v)}
                >
                  {showDetails ? 'Hide details ▲' : 'Show details ▼'}
                </button>

                {showDetails && (
                  <div className="hg-match-details">
                    {matchResult.ranked_inventory.length > 0 && (
                      <>
                        <div className="hg-details-subtitle">
                          Inventory candidates (top {matchResult.ranked_inventory.length}, sorted by expiry → distance)
                        </div>
                        <table className="hg-rank-table">
                          <thead>
                            <tr>
                              <th>#</th><th>Bank</th><th>Type</th>
                              <th>Exp</th><th>Dist</th>
                            </tr>
                          </thead>
                          <tbody>
                            {matchResult.ranked_inventory.map((item) => (
                              <tr key={`${item.bank_id}-${item.days_to_expiry}`}
                                className={item.rank === 1 ? 'hg-rank-winner' : ''}>
                                <td>{item.rank}</td>
                                <td>{item.bank_id}</td>
                                <td>{bloodType(item.abo, item.rh_d)}</td>
                                <td>{item.days_to_expiry}d</td>
                                <td>{item.distance_km !== null ? `${item.distance_km}km` : '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </>
                    )}

                    {matchResult.ranked_donors.length > 0 && (
                      <>
                        <div className="hg-details-subtitle" style={{ marginTop: 8 }}>
                          Donor candidates (top {matchResult.ranked_donors.length}, by rank_matches score)
                        </div>
                        <table className="hg-rank-table">
                          <thead>
                            <tr>
                              <th>#</th><th>Donor</th><th>Type</th>
                              <th>Score</th><th>Rel</th><th>Dist</th><th>Bond</th>
                            </tr>
                          </thead>
                          <tbody>
                            {matchResult.ranked_donors.map((d) => (
                              <tr key={d.donor_id}
                                className={d.bonded ? 'hg-rank-bonded' : d.rank === 1 ? 'hg-rank-winner' : ''}>
                                <td>{d.rank}</td>
                                <td>{d.donor_id}</td>
                                <td>{bloodType(d.abo, d.rh_d)}</td>
                                <td>{d.score.toFixed(3)}</td>
                                <td>{d.reliability.toFixed(3)}</td>
                                <td>{d.distance_km}km</td>
                                <td>{d.bonded ? '★' : ''}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <MapContainer center={INDIA_CENTER} zoom={INDIA_ZOOM} className="map-container">
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          maxZoom={19}
        />

        {/* Desert layer */}
        {showDeserts && deserts.map((cell) => (
          <CircleMarker
            key={cell.cell_id}
            center={[cell.lat, cell.lng]}
            radius={desertRadius(cell.desert_score)}
            pathOptions={{
              color: DESERT_COLORS[cell.desert_type],
              fillColor: DESERT_COLORS[cell.desert_type],
              fillOpacity: desertFillOpacity(cell.desert_score, cell.desert_type),
              weight: cell.desert_type === 'OK' ? 1 : 2,
              opacity: cell.desert_type === 'OK' ? 0.45 : 0.9,
            }}
            eventHandlers={{ click: () => setSelected(cell) }}
          >
            <Tooltip direction="top" offset={[0, -4]} opacity={0.92}>
              <strong>{cell.name}</strong><br />
              {DESERT_LABELS[cell.desert_type]} · score {cell.desert_score}
            </Tooltip>
          </CircleMarker>
        ))}

        {/* Guntur banks layer */}
        {showBanks && banks.map((bank) => (
          <Marker
            key={bank.bank_id}
            position={[bank.lat, bank.lng]}
            icon={bank.does_components ? ICON_COMPONENT : ICON_STANDARD}
          >
            <Popup>
              <strong>{bank.name}</strong><br />
              Category: {bank.category ?? 'unknown'}<br />
              Components: {bank.does_components ? 'Yes' : 'No'}<br />
              ID: {bank.bank_id}
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  )
}
