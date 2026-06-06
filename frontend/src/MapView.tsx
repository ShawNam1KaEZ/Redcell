import { useEffect, useState } from 'react'
import { GridSimulator } from './GridSimulator'
import { MapContainer, TileLayer, Marker, Popup, CircleMarker, Tooltip } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import markerIconUrl from 'leaflet/dist/images/marker-icon.png?url'
import markerIcon2xUrl from 'leaflet/dist/images/marker-icon-2x.png?url'
import markerShadowUrl from 'leaflet/dist/images/marker-shadow.png?url'
import {
  activateChaosMode,
  deactivateChaosMode,
  approveAction,
  fetchBanks,
  fetchDeserts,
  fetchDuePatients,
  fetchDemoStatuses,
  fetchHealth,
  fetchMatch,
  proposeAction,
  resetDemo,
  type ApproveResponse,
  type BankSummary,
  type DesertCell,
  type MatchResult,
  type OrchestrateEventDetails,
  type PatientStatuses,
  type PatientSummary,
  type ProposalResponse,
} from './api'
import './MapView.css'

delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)['_getIconUrl']
L.Icon.Default.mergeOptions({
  iconUrl: markerIconUrl,
  iconRetinaUrl: markerIcon2xUrl,
  shadowUrl: markerShadowUrl,
})

const LOADING_STEPS = [
  '[STAGE 1/4] Ingesting Indian Regional Phenotype Metrics (K-negative: 0.97 Baseline)...',
  '[STAGE 2/4] Scanning Proximity Threshold Tiers for Local Bank Repositories...',
  '[STAGE 3/4] Running Safe Antibody Matching Intercept Gates...',
  '[STAGE 4/4] Completing Narrative Wrappers via Local Edge LLM (qwen2.5:7b)...',
]

const makeCircle = (color: string) =>
  L.divIcon({
    className: '',
    html: `<div class="hg-marker" style="background:${color}"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
    popupAnchor: [0, -10],
  })

const ICON_COMPONENT = makeCircle('#d32f2f')
const ICON_STANDARD  = makeCircle('#1565c0')

const INDIA_CENTER: [number, number] = [22.5, 80.0]
const INDIA_ZOOM = 5
const HYD_CENTER: [number, number] = [17.3850, 78.4867]
const HYD_ZOOM = 11

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
const CLASSIFICATION_LABELS: Record<string, string> = {
  CHRONIC: 'CHRONIC STRUCTURAL DESERT',
  ACUTE:   'ACUTE SHORTFALL',
  OK:      '',
}
const CLASSIFICATION_COLORS: Record<string, string> = {
  CHRONIC: '#6a1b9a',
  ACUTE:   '#e65100',
  OK:      '',
}
const DESERT_DESC: Record<string, string> = {
  SUPPLY_LIMITED:        'Shelves too thin — demand exceeds available supply. Fix: redistribute units.',
  COMPATIBILITY_LIMITED: 'Shelves stocked but not antibody-safe for these patients. Fix: activate phenotype-matched donors.',
  MIXED:                 'Both insufficient supply and antibody incompatibility.',
  OK:                    'Demand fully met with antibody-safe inventory.',
}
const LEVER_LABELS: Record<string, string> = {
  inventory: 'Redistribute inventory',
  donor:     'Activate donor',
  emergency: 'Emergency escalation',
}
const LEVER_COLORS: Record<string, string> = {
  inventory: '#1565c0',
  donor:     '#2e7d32',
  emergency: '#b71c1c',
}
const NODE_CHIPS: Record<string, string> = {
  forecast:       'forecast',
  desert:         'desert',
  orchestrate:    'orchestrate',
  approval:       'approval',
  redistribution: 'redistribution',
  donor_matching: 'donor',
  emergency:      'emergency',
  declined:       'declined',
}
const NODE_COLORS: Record<string, string> = {
  forecast:       '#546e7a',
  desert:         '#546e7a',
  orchestrate:    '#546e7a',
  approval:       '#f57f17',
  redistribution: '#1565c0',
  donor_matching: '#2e7d32',
  emergency:      '#b71c1c',
  declined:       '#795548',
}

function desertRadius(score: number): number {
  if (score === 0) return 7
  return Math.min(9 + score * 1.5, 44)
}
function desertFillOpacity(score: number, type: string): number {
  if (type === 'OK') return 0.28
  return Math.min(0.50 + score / 60, 0.82)
}
function bloodType(abo: string, rh_d: boolean): string {
  return `${abo}${rh_d ? '+' : '-'}`
}
function phenotypeSummary(ph: { K?: boolean | null } | null): string {
  if (!ph) return 'untyped'
  const tags: string[] = []
  if (ph.K === false) tags.push('K-neg')
  if (ph.K === true)  tags.push('K-pos')
  return tags.length ? tags.join(', ') : 'typed'
}

export function MapView() {
  const [banks, setBanks]             = useState<BankSummary[]>([])
  const [bankStatus, setBankStatus]   = useState<'loading'|'ok'|'error'>('loading')
  const [bankError, setBankError]     = useState('')
  const [deserts, setDeserts]         = useState<DesertCell[]>([])
  const [desertStatus, setDesertStatus] = useState<'loading'|'ok'|'error'>('loading')
  const [desertError, setDesertError] = useState('')
  const [showDeserts, setShowDeserts] = useState(true)
  const [showBanks, setShowBanks]     = useState(true)

  const [selected, setSelected]             = useState<DesertCell | null>(null)
  const [patients, setPatients]             = useState<PatientSummary[]>([])
  const [patientsLoading, setPatientsLoading] = useState(false)
  const [patientsError, setPatientsError]   = useState('')
  const [activePatientId, setActivePatientId] = useState<string | null>(null)

  const [matchResult, setMatchResult]   = useState<MatchResult | null>(null)
  const [matchLoading, setMatchLoading] = useState(false)
  const [matchError, setMatchError]     = useState('')
  const [showDetails, setShowDetails]   = useState(false)

  const [proposalResp, setProposalResp]     = useState<ProposalResponse | null>(null)
  const [proposalLoading, setProposalLoading] = useState(false)
  const [proposalError, setProposalError]   = useState('')
  const [approveResp, setApproveResp]       = useState<ApproveResponse | null>(null)
  const [approveLoading, setApproveLoading] = useState(false)
  const [approveError, setApproveError]     = useState('')

  const [showSimulator, setShowSimulator] = useState(false)
  const [loadingStep, setLoadingStep]     = useState(0)
  const [chaosMode, setChaosMode]         = useState(false)

  // Session-scoped triage tracking — canonical source of truth is the backend
  const [fulfilledIds, setFulfilledIds]       = useState<string[]>([])
  const [stockOverrides, setStockOverrides]   = useState<Record<string, number>>({})
  const [patientStatuses, setPatientStatuses] = useState<PatientStatuses>({})
  const [resetLoading, setResetLoading]       = useState(false)

  // SMS gateway — live receiver node state
  const [receivedSMS, setReceivedSMS] = useState<Array<{from: string; body: string; time: string}>>([])
  const [smsSending, setSmsSending]   = useState(false)
  const [smsGatewayClosed, setSmsGatewayClosed] = useState(false)

  // Live-mode detection — populated from GET /api/health on mount
  const [liveMode, setLiveMode]       = useState(false)
  const [healthLoaded, setHealthLoaded] = useState(false)

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'X') {
        setChaosMode(prev => {
          const next = !prev
          if (next) activateChaosMode()
          else deactivateChaosMode()
          return next
        })
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [])

  useEffect(() => {
    if (loadingStep === 0 || loadingStep >= LOADING_STEPS.length) return
    const t = setTimeout(() => setLoadingStep(s => s + 1), 200)
    return () => clearTimeout(t)
  }, [loadingStep])

  useEffect(() => {
    if (!matchLoading && !proposalLoading && loadingStep > 0) {
      const t = setTimeout(() => setLoadingStep(0), 250)
      return () => clearTimeout(t)
    }
  }, [matchLoading, proposalLoading, loadingStep])

  // Detect live mode first — bank fetch and map viewport depend on it
  useEffect(() => {
    fetchHealth()
      .then(h => { setLiveMode(h.live_mode); setHealthLoaded(true) })
      .catch(() => setHealthLoaded(true))   // backend offline → fall back to synthetic
  }, [])

  useEffect(() => {
    if (!healthLoaded) return
    fetchBanks(liveMode ? undefined : 'Guntur')
      .then(data => { setBanks(data); setBankStatus('ok') })
      .catch((err: Error) => { setBankError(err.message); setBankStatus('error') })
  }, [healthLoaded, liveMode])

  useEffect(() => {
    fetchDeserts()
      .then(data => { setDeserts(data); setDesertStatus('ok') })
      .catch((err: Error) => { setDesertError(err.message); setDesertStatus('error') })
  }, [])

  // Sync backend patient statuses on mount
  useEffect(() => {
    fetchDemoStatuses().then(setPatientStatuses).catch(() => {})
  }, [])

  useEffect(() => {
    setPatients([])
    setLoadingStep(0)
    setMatchResult(null); setMatchError(''); setShowDetails(false)
    setProposalResp(null); setProposalError('')
    setApproveResp(null); setApproveError('')
    setActivePatientId(null)
    if (!selected) return
    setPatientsLoading(true); setPatientsError('')
    fetchDuePatients(selected.cell_id)
      .then(data => { setPatients(data); setPatientsLoading(false) })
      .catch((err: Error) => { setPatientsError(err.message); setPatientsLoading(false) })
  }, [selected])

  const isApproved = (pid: string) =>
    fulfilledIds.includes(pid) || patientStatuses[pid] === 'APPROVED'
  const isRejected = (pid: string) => patientStatuses[pid] === 'REJECTED'

  const handlePatientClick = (p: PatientSummary) => {
    setActivePatientId(p.patient_id)
    // Approved patients are locked — don't re-run the pipeline
    if (isApproved(p.patient_id)) return
    setLoadingStep(1)
    setMatchResult(null); setMatchError(''); setShowDetails(false); setMatchLoading(true)
    setProposalResp(null); setProposalError(''); setProposalLoading(true)
    setApproveResp(null); setApproveError(''); setApproveLoading(false)

    fetchMatch(p.patient_id)
      .then(data => { setMatchResult(data); setMatchLoading(false) })
      .catch((err: Error) => { setMatchError(err.message); setMatchLoading(false) })

    proposeAction(p.patient_id)
      .then(data => { setProposalResp(data); setProposalLoading(false) })
      .catch((err: Error) => { setProposalError(err.message); setProposalLoading(false) })
  }

  const handleDecision = (decision: 'approve' | 'reject') => {
    if (!proposalResp || !activePatientId) return
    setApproveLoading(true); setApproveError('')

    const isSMSDispatch = decision === 'approve' && activePatientId === 'PAT-0001'
    if (isSMSDispatch) { setSmsSending(true); setSmsGatewayClosed(false) }

    if (decision === 'approve') {
      setFulfilledIds(prev => prev.includes(activePatientId) ? prev : [...prev, activePatientId])
      const bankId = proposalResp.proposal.proposed_action.bank_id
      if (bankId) {
        setStockOverrides(prev => ({ ...prev, [bankId]: (prev[bankId] ?? 0) + 1 }))
      }
    }

    const capturedProposalResp = proposalResp
    approveAction(activePatientId, { thread_id: proposalResp.thread_id, decision })
      .then(data => {
        setApproveResp(data)
        setApproveLoading(false)
        setSmsSending(false)
        // Sync backend status after decision
        fetchDemoStatuses().then(setPatientStatuses).catch(() => {})
        // Refresh desert cells so map circles and overview table update live
        fetchDeserts().then(freshDeserts => {
          setDeserts(freshDeserts)
          setSelected(prev => {
            if (!prev) return prev
            const updated = freshDeserts.find(c => c.cell_id === prev.cell_id)
            return updated ?? prev
          })
        }).catch(() => {})
        // Push SMS payload to gateway when PAT-0001 donor dispatch fires
        if (isSMSDispatch) {
          const msgBody = capturedProposalResp.donor_message_draft ??
            'Dear Donor DON-0002,\n\nWe urgently request your blood donation (B+, K-negative) for patient PAT-0001 (Aarav), who requires a matched transfusion within 5 days.\n\nYour phenotype profile is the closest compatible match within our regional registry. Please contact us at your earliest convenience to schedule your appointment.\n\nReference: DON-0002 / PAT-0001.'
          setReceivedSMS(prev => [...prev, {
            from: 'HemoGrid Hub',
            body: msgBody,
            time: 'Just Now',
          }])
        }
      })
      .catch((err: Error) => {
        setApproveError(err.message)
        setApproveLoading(false)
        setSmsSending(false)
      })
  }

  const getTriageBadge = (patientId: string): { label: string; cls: string } => {
    if (patientId === 'PAT-EMERG-99') return { label: '🚨 EMERGENCY ESCALATION', cls: 'hg-triage-emergency' }
    if (patientId === 'PAT-0001')     return { label: '📡 DONOR MATCH REQ',       cls: 'hg-triage-donor'     }
    return { label: '📦 LOCAL RE-ROUTE', cls: 'hg-triage-inventory' }
  }

  const componentCount = banks.filter(b => b.does_components).length
  const desertCount    = deserts.filter(c => c.desert_type !== 'OK').length

  // Live table overrides — computed from approved patients in active cell
  const approvedInCell = selected ? patients.filter(p => isApproved(p.patient_id)).length : 0
  const dynMet         = selected ? selected.met + approvedInCell : 0
  const rawSupplyGap   = selected ? Math.abs(selected.supply_gap) : 0
  const dynSupplyGap   = selected ? Math.max(0, rawSupplyGap - approvedInCell) : 0
  const isStabilized   = selected ? (dynSupplyGap === 0 && rawSupplyGap > 0) : false
  const dynDesertScore = isStabilized ? 0 : (selected?.desert_score ?? 0)

  const activeLever = (approveResp?.chosen_lever ?? proposalResp?.proposal?.chosen_lever ?? matchResult?.chosen_lever) || null

  const activityEvents = approveResp
    ? approveResp.events
    : proposalResp
    ? proposalResp.events_so_far
    : []

  const activityPanelVisible =
    proposalLoading || proposalError !== '' ||
    proposalResp !== null || approveResp !== null

  return (
    <div className="tactical-root">

      {/* ══════════════════════════════════════════════════════════════════
          GLOBAL TOP-PANEL MATRIX LOADING PROGRESS BAR
      ══════════════════════════════════════════════════════════════════ */}
      {loadingStep > 0 && (matchLoading || proposalLoading) && (
        <div className="matrix-processing-ticker">
          <div
            className="matrix-processing-bar"
            style={{ width: `${(loadingStep / LOADING_STEPS.length) * 100}%` }}
          />
          <div className="matrix-processing-label">
            {LOADING_STEPS[loadingStep - 1]}
          </div>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════════
          LEFT COLUMN — Triage Matrix
      ══════════════════════════════════════════════════════════════════ */}
      <div className="tactical-left">
        <div className="tactical-col-header">
          <div className="tactical-col-header-left">
            <span className="tactical-col-title">TRIAGE MATRIX</span>
            {bankStatus === 'ok' && (
              <span className="tactical-col-meta">
                {banks.length} banks · {desertCount} desert cell{desertCount !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <div className="tactical-col-header-right">
            {bankStatus === 'ok' && (
              <>
                <span className="dot dot-red" style={{ width: 8, height: 8 }} />
                <span className="tactical-bank-num">{componentCount}</span>
                <span className="dot dot-blue" style={{ width: 8, height: 8, marginLeft: 6 }} />
                <span className="tactical-bank-num">{banks.length - componentCount}</span>
              </>
            )}
          </div>
        </div>

        {selected ? (
          <div className="tactical-left-body">
            {/* Desert cell header */}
            <div className="hg-detail-header" style={{ borderLeftColor: DESERT_COLORS[selected.desert_type] }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                <div>
                  <span className="hg-detail-badge" style={{ background: DESERT_COLORS[selected.desert_type] }}>
                    {DESERT_LABELS[selected.desert_type]}
                  </span>
                  {selected.classification !== 'OK' && (
                    <span
                      className="hg-classification-badge"
                      style={{ background: CLASSIFICATION_COLORS[selected.classification] }}
                    >
                      {CLASSIFICATION_LABELS[selected.classification]}
                    </span>
                  )}
                </div>
                <button className="hg-detail-close" onClick={() => setSelected(null)}>×</button>
              </div>
              <div className="hg-detail-name">{selected.name}</div>
              <div className="hg-detail-id">{selected.cell_id}</div>
            </div>

            <div className="hg-detail-desc">{DESERT_DESC[selected.desert_type]}</div>

            <table className="hg-detail-table"><tbody>
              <tr><td>Patients due</td><td>{selected.patients_due}</td></tr>
              <tr><td>Demand (D)</td><td>{selected.demand_units} units</td></tr>
              <tr className="hg-row-divider"><td>ABO/Rh-compatible (S_raw)</td><td>{selected.raw_units} units</td></tr>
              <tr><td>Antibody-safe (S_safe)</td>
                <td style={{ color: selected.safe_units < selected.raw_units ? DESERT_COLORS.COMPATIBILITY_LIMITED : undefined, fontWeight: selected.safe_units < selected.raw_units ? 600 : undefined }}>
                  {selected.safe_units} units
                  {selected.safe_units < selected.raw_units && ` (${selected.raw_units - selected.safe_units} lost to antibody gate)`}
                </td>
              </tr>
              <tr><td>Met</td><td>{dynMet} units</td></tr>
              {Math.abs(selected.compatibility_gap) > 0 && <tr className="hg-row-compat"><td>Compatibility gap</td><td>{Math.abs(selected.compatibility_gap)} units</td></tr>}
              {dynSupplyGap > 0 && <tr className="hg-row-supply"><td>Supply gap</td><td>{dynSupplyGap} units</td></tr>}
              <tr className="hg-row-score"><td>Desert score</td><td>{dynDesertScore}</td></tr>
              {isStabilized && (
                <tr><td colSpan={2} style={{ padding: '6px 16px 10px' }}>
                  <div className="hg-stabilized-badge">📦 INVENTORY STABILIZED</div>
                </td></tr>
              )}
            </tbody></table>

            <div className="hg-detail-clock">
              <strong>Clock ingredients</strong><br />
              Nearest safe inventory: {selected.nearest_safe_inventory_km !== null ? `${selected.nearest_safe_inventory_km.toFixed(1)} km` : 'none'}<br />
              Eligible matched donors nearby: {selected.eligible_matched_donors_nearby}
            </div>

            {/* ── Due patients ─────────────────────────────────────────── */}
            <div className="hg-patients-section">
              {(() => {
                const pendingPatients = patients.filter(p => p.status !== 'approved')
                return (
              <>
              <div className="hg-patients-title">
                Total Pending Patients ({pendingPatients.length})
                {patientsLoading && <span className="hg-loading-inline"> loading...</span>}
              </div>
              {patientsError && <div className="hg-error-inline">{patientsError}</div>}
              {pendingPatients.length > 0 && (
                <div className="hg-patient-list hg-patient-list-expanded">
                  {pendingPatients.map(p => {
                    const approved = isApproved(p.patient_id)
                    const rejected = isRejected(p.patient_id)
                    const badge    = getTriageBadge(p.patient_id)
                    return (
                      <button
                        key={p.patient_id}
                        className={[
                          'hg-patient-row hg-patient-row-v2',
                          activePatientId === p.patient_id ? 'hg-patient-active' : '',
                          approved ? 'hg-patient-fulfilled' : '',
                          rejected ? 'hg-patient-rejected' : '',
                        ].join(' ').trim()}
                        onClick={() => handlePatientClick(p)}
                      >
                        <div className="hg-patient-badge-line">
                          <span className={badge.cls}>{badge.label}</span>
                          {approved && (
                            <span className="hg-triage-dispatched">✓ ACTIONS DISPATCHED</span>
                          )}
                          {rejected && !approved && (
                            <span className="hg-triage-denied">✕ LINE ACTION DENIED</span>
                          )}
                        </div>
                        <div className="hg-patient-row-data">
                          <span
                            className="hg-patient-id"
                            style={approved ? { textDecoration: 'line-through' } : {}}
                          >
                            {p.patient_id}
                            {p.patient_id === 'PAT-0001' && !approved && (
                              <span className="hg-demo-tag">demo</span>
                            )}
                          </span>
                          <span className="hg-patient-type">{bloodType(p.abo, p.rh_d)}</span>
                          {p.known_antibodies.length > 0 && (
                            <span className="hg-patient-ab">{p.known_antibodies.join(', ')}</span>
                          )}
                          <span className="hg-patient-due">
                            {p.days_until_due === 0 ? 'today' : p.days_until_due < 0 ? `${Math.abs(p.days_until_due)}d overdue` : `in ${p.days_until_due}d`}
                          </span>
                        </div>
                      </button>
                    )
                  })}
                </div>
              )}
              </>
                )
              })()}

              {/* Structural recommendation */}
              {selected.classification !== 'OK' && selected.structural_recommendation && (
                <div className={`hg-struct-rec-block hg-struct-rec-${selected.classification.toLowerCase()}`}>
                  <div className="hg-struct-rec-label">
                    {selected.classification === 'CHRONIC' ? 'Structural Recommendation' : 'Tactical Recommendation'}
                    {chaosMode && <span className="hg-chaos-badge">⚡ DEMO FALLBACK ACTIVE</span>}
                  </div>
                  <div className="hg-struct-rec-text">{selected.structural_recommendation}</div>
                </div>
              )}

              {/* Recommendation panel */}
              {matchError && <div className="hg-error-inline">{matchError}</div>}
              {matchResult && !matchLoading && (
                <div className="hg-match-result">
                  <div className="hg-match-header">
                    <span className="hg-match-badge" style={{ background: LEVER_COLORS[matchResult.chosen_lever] }}>
                      {LEVER_LABELS[matchResult.chosen_lever]}
                    </span>
                    <span className="hg-match-pid">{matchResult.patient_id}</span>
                    <span className="hg-match-blood">{bloodType(matchResult.abo, matchResult.rh_d)}</span>
                  </div>
                  {matchResult.chosen_lever === 'inventory' && matchResult.chosen_inventory && (() => {
                    const inv = matchResult.chosen_inventory
                    const dispatched = stockOverrides[inv.bank_id] ?? 0
                    const displayed  = Math.max(0, inv.inventory_options - dispatched)
                    return (
                      <div className="hg-match-chosen">
                        <div className="hg-match-chosen-main">
                          <strong>{inv.bank_id}</strong>
                          <span className="hg-match-dash"> — </span>
                          <span>{inv.bank_name}</span>
                        </div>
                        <div className="hg-match-chosen-facts">
                          {bloodType(inv.abo, inv.rh_d)} PRBC · {phenotypeSummary(inv.phenotype_tags)} · expires in {inv.days_to_expiry}d
                          {inv.distance_km !== null ? ` · ${inv.distance_km} km` : ''}
                        </div>
                        <div className="hg-match-inv-options">
                          <span className={dispatched > 0 ? 'hg-units-adjusted' : ''}>
                            {displayed} compatible unit{displayed !== 1 ? 's' : ''} in range
                          </span>
                          {dispatched > 0 && (
                            <span className="hg-units-adjustment-note"> (−{dispatched} dispatched)</span>
                          )}
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
                          {bloodType(don.abo, don.rh_d)} · {don.distance_km} km · reliability {don.reliability_score.toFixed(3)} · score {don.score.toFixed(4)}
                        </div>
                        <div className="hg-match-inv-options">
                          {don.candidates_ranked} eligible donor{don.candidates_ranked !== 1 ? 's' : ''} ranked
                        </div>
                      </div>
                    )
                  })()}
                  {matchResult.chosen_lever === 'emergency' && (
                    <div className="hg-match-emergency">
                      No compatible inventory or eligible donor found. Escalate to regional emergency network.
                    </div>
                  )}
                  <div className="hg-match-reasoning">{matchResult.reasoning}</div>
                  <button className="hg-details-toggle" onClick={() => setShowDetails(v => !v)}>
                    {showDetails ? 'Hide details' : 'Show details'}
                  </button>
                  {showDetails && (
                    <div className="hg-match-details">
                      {matchResult.ranked_inventory.length > 0 && (() => {
                        const seen = new Map<string, { item: typeof matchResult.ranked_inventory[0]; count: number }>()
                        for (const item of matchResult.ranked_inventory) {
                          const entry = seen.get(item.bank_id)
                          if (!entry) seen.set(item.bank_id, { item, count: 1 })
                          else entry.count++
                        }
                        const deduped = Array.from(seen.values())
                        return (<>
                          <div className="hg-details-subtitle">
                            Inventory candidates — {deduped.length} bank{deduped.length !== 1 ? 's' : ''}, {matchResult.ranked_inventory.length} unit{matchResult.ranked_inventory.length !== 1 ? 's' : ''} (sorted by expiry)
                          </div>
                          <table className="hg-rank-table">
                            <thead><tr><th>#</th><th>Bank</th><th>Type</th><th>Exp</th><th>Dist</th></tr></thead>
                            <tbody>{deduped.map(({ item, count }) => (
                              <tr key={item.bank_id} className={item.rank === 1 ? 'hg-rank-winner' : ''}>
                                <td>{item.rank}</td>
                                <td>
                                  {item.bank_id}
                                  {count > 1 && <span className="hg-unit-count">×{count}</span>}
                                </td>
                                <td>{bloodType(item.abo, item.rh_d)}</td>
                                <td>{item.days_to_expiry}d</td>
                                <td>{item.distance_km !== null ? `${item.distance_km}km` : '—'}</td>
                              </tr>
                            ))}</tbody>
                          </table>
                        </>)
                      })()}
                      {matchResult.ranked_donors.length > 0 && (<>
                        <div className="hg-details-subtitle" style={{ marginTop: 8 }}>
                          Donor candidates (top {matchResult.ranked_donors.length}, by score)
                        </div>
                        <table className="hg-rank-table">
                          <thead><tr><th>#</th><th>Donor</th><th>Type</th><th>Score</th><th>Rel</th><th>Dist</th><th>Bond</th></tr></thead>
                          <tbody>{matchResult.ranked_donors.map(d => (
                            <tr key={d.donor_id} className={d.bonded ? 'hg-rank-bonded' : d.rank === 1 ? 'hg-rank-winner' : ''}>
                              <td>{d.rank}</td><td>{d.donor_id}</td><td>{bloodType(d.abo, d.rh_d)}</td>
                              <td>{d.score.toFixed(3)}</td><td>{d.reliability.toFixed(3)}</td>
                              <td>{d.distance_km}km</td><td>{d.bonded ? '*' : ''}</td>
                            </tr>
                          ))}</tbody>
                        </table>
                      </>)}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="tactical-empty">
            <div className="tactical-empty-icon">🩸</div>
            <div className="tactical-empty-text">Click a desert marker on the map to begin triage assessment</div>
            {desertStatus === 'ok' && desertCount > 0 && (
              <div className="tactical-desert-warning">
                ⚠ {desertCount} active desert cell{desertCount !== 1 ? 's' : ''} detected
              </div>
            )}
          </div>
        )}
      </div>

      {/* ══════════════════════════════════════════════════════════════════
          CENTER COLUMN — Map
      ══════════════════════════════════════════════════════════════════ */}
      <div className="tactical-center">
        {(bankStatus === 'loading' || desertStatus === 'loading') && (
          <div className="map-overlay map-loading">Loading...</div>
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

        <div className="hg-toggles">
          <label><input type="checkbox" checked={showDeserts} onChange={e => setShowDeserts(e.target.checked)} /> Desert cells</label>
          <label><input type="checkbox" checked={showBanks}   onChange={e => setShowBanks(e.target.checked)}   /> {liveMode ? 'Hyderabad banks' : 'Guntur banks'}</label>
          <div
            className={`hg-chaos-indicator ${chaosMode ? 'hg-chaos-on' : ''}`}
            title="Ctrl+Shift+X to toggle LLM fallback demo mode"
          >
            {chaosMode ? '⚡ DEMO MODE ON' : 'Demo mode off'}
          </div>
          <button
            className={`hg-sim-toggle-btn ${showSimulator ? 'hg-sim-toggle-on' : ''}`}
            onClick={() => setShowSimulator(v => !v)}
            title="Toggle Grid Matrix Simulation widget"
          >
            {showSimulator ? 'Hide Simulation' : 'Grid Simulation'}
          </button>
          <button
            className="hg-reset-demo-btn"
            disabled={resetLoading}
            title="Reset all demo state to seed=42 baseline"
            onClick={async () => {
              setResetLoading(true)
              try {
                await resetDemo()
                setPatientStatuses({})
                setFulfilledIds([])
                setStockOverrides({})
                setMatchResult(null); setMatchError(''); setShowDetails(false)
                setProposalResp(null); setProposalError('')
                setApproveResp(null); setApproveError('')
                setActivePatientId(null)
                setLoadingStep(0)
                setReceivedSMS([]); setSmsSending(false)
                // Refresh desert cells to show un-adjusted metrics
                fetchDeserts()
                  .then(data => setDeserts(data))
                  .catch(() => {})
              } finally {
                setResetLoading(false)
              }
            }}
          >
            {resetLoading ? '...' : '🔄 Reset Demo State'}
          </button>
        </div>

        <div className="hg-legend">
          <div className="hg-legend-title">Blood Desert Types</div>
          <div className="hg-legend-row">
            <span className="hg-legend-swatch" style={{ background: DESERT_COLORS.SUPPLY_LIMITED }} />
            <div><strong>Supply desert</strong><div className="hg-legend-sub">Shelf too thin</div></div>
          </div>
          <div className="hg-legend-row">
            <span className="hg-legend-swatch" style={{ background: DESERT_COLORS.COMPATIBILITY_LIMITED }} />
            <div><strong>Compatibility desert</strong><div className="hg-legend-sub">Immunologically mismatched</div></div>
          </div>
          <div className="hg-legend-row">
            <span className="hg-legend-swatch" style={{ background: DESERT_COLORS.OK }} />
            <div><strong>No desert</strong><div className="hg-legend-sub">Demand met</div></div>
          </div>
          <div className="hg-legend-note">Circle size proportional to desert score</div>
        </div>

        <div className="map-count-box">
          {bankStatus === 'ok' && (<>
            <span className="dot dot-red" /> Component-capable ({componentCount})<br />
            <span className="dot dot-blue" /> Standard ({banks.length - componentCount})<br />
            <strong>{banks.length} {liveMode ? 'Hyderabad' : 'Guntur'} banks</strong>
          </>)}
          {desertStatus === 'ok' && (<><br />{desertCount} desert cell{desertCount !== 1 ? 's' : ''} / {deserts.length} total</>)}
        </div>

        {showSimulator && (
          <GridSimulator onClose={() => setShowSimulator(false)} />
        )}

        <MapContainer
          key={liveMode ? 'live' : 'synthetic'}
          center={liveMode ? HYD_CENTER : INDIA_CENTER}
          zoom={liveMode ? HYD_ZOOM : INDIA_ZOOM}
          className="map-container"
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            maxZoom={19}
          />
          {showDeserts && deserts.map(cell => (
            <CircleMarker
              key={cell.cell_id}
              center={[cell.lat, cell.lng]}
              radius={desertRadius(cell.desert_score)}
              pathOptions={{
                color:       DESERT_COLORS[cell.desert_type],
                fillColor:   DESERT_COLORS[cell.desert_type],
                fillOpacity: desertFillOpacity(cell.desert_score, cell.desert_type),
                weight:      cell.desert_type === 'OK' ? 1 : 2,
                opacity:     cell.desert_type === 'OK' ? 0.45 : 0.9,
                className:   activePatientId === 'PAT-EMERG-99' ? 'pulse-crimson-radar' : '',
              }}
              eventHandlers={{ click: () => setSelected(cell) }}
            >
              <Tooltip direction="top" offset={[0, -4]} opacity={0.92}>
                <strong>{cell.name}</strong><br />
                {DESERT_LABELS[cell.desert_type]} · score {cell.desert_score}
              </Tooltip>
            </CircleMarker>
          ))}
          {showBanks && banks.map(bank => (
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

      {/* ══════════════════════════════════════════════════════════════════
          RIGHT COLUMN — Intelligence Panel
      ══════════════════════════════════════════════════════════════════ */}
      <div className={`tactical-right${activeLever ? ` hg-lever-${activeLever}` : ''}`}>
        <div className="tactical-col-header">
          <span className="tactical-col-title">INTELLIGENCE PANEL</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {chaosMode && <span className="hg-chaos-badge">⚡ DEMO</span>}
            {approveResp && (
              <span className={`hg-activity-status-badge hg-status-${approveResp.status}`}>
                {approveResp.status === 'fulfilled' ? 'Fulfilled' : 'Declined'}
              </span>
            )}
            {!approveResp && proposalResp && (
              <span className="hg-activity-status-badge hg-status-awaiting">Awaiting</span>
            )}
          </div>
        </div>

        {/* ── PAT-0001: Bonded Donor Matching Module ────────────────────── */}
        {activePatientId === 'PAT-0001' && !isApproved('PAT-0001') && (
          <div className="tactical-right-body">
            <div className="hg-donor-module">
              <div className="hg-donor-module-header">
                📡 DEPLOYING ALTERNATIVE LEVER: BONDED DONOR ENGAGEMENT
              </div>
              <div className="hg-donor-credentials">
                <div className="hg-cred-row"><span className="hg-cred-key">Donor ID</span><span className="hg-cred-val">DON-0002</span></div>
                <div className="hg-cred-row"><span className="hg-cred-key">Phenotype Match</span><span className="hg-cred-val">B+, K-negative</span></div>
                <div className="hg-cred-row"><span className="hg-cred-key">Proximity</span><span className="hg-cred-val">2.4 km away</span></div>
                <div className="hg-cred-row"><span className="hg-cred-key">Match Score</span><span className="hg-cred-val hg-cred-accent">0.9141</span></div>
                <div className="hg-cred-row"><span className="hg-cred-key">Supply Clock</span><span className="hg-cred-val">4 days</span></div>
              </div>
              <div className="hg-donor-msg-block">
                <div className="hg-donor-msg-label">Donor Activation Message</div>
                <div className="hg-donor-msg-text">
                  {proposalResp?.donor_message_draft ??
                    'Dear Donor DON-0002,\n\nWe urgently request your blood donation (B+, K-negative) for patient PAT-0001 (Aarav), who requires a matched transfusion within 5 days.\n\nYour phenotype profile is the closest compatible match within our regional registry. Please contact us at your earliest convenience to schedule your appointment.\n\nReference: DON-0002 / PAT-0001.'}
                </div>
              </div>
              {proposalLoading && <div className="hg-activity-loading">Engaging agent matrix…</div>}
              <div className="hg-approval-buttons" style={{ marginTop: 12 }}>
                <button
                  className={`hg-btn-dispatch-sms${smsSending ? ' hg-btn-sending' : ''}`}
                  disabled={!proposalResp || proposalLoading || !!approveResp || smsSending}
                  onClick={() => handleDecision('approve')}
                >
                  {smsSending ? '📡 [SENDING...]' : '🚀 DISPATCH SMS OUTREACH PAYLOAD'}
                </button>
              </div>
              {approveLoading && <div className="hg-activity-loading">Dispatching…</div>}
              {approveResp && (
                <div className="hg-approval-result hg-result-fulfilled" style={{ margin: '10px 0 0' }}>
                  ✓ SMS outreach dispatched — DON-0002 engagement initiated
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── PAT-0001 committed banner ─────────────────────────────────── */}
        {activePatientId === 'PAT-0001' && isApproved('PAT-0001') && (
          <div className="tactical-right-body">
            <div className="hg-committed-banner">
              <div className="hg-committed-header">
                ✓ THIS TRANSFUSION MATRIX HAS BEEN COMMITTED AND ROUTED
              </div>
            </div>
          </div>
        )}

        {/* ── PAT-EMERG-99: Emergency Escalation Hub ───────────────────── */}
        {activePatientId === 'PAT-EMERG-99' && !isApproved('PAT-EMERG-99') && (
          <div className="tactical-right-body">
            <div className="hg-emergency-hub">
              <div className="hg-emergency-hub-header">
                🚨 CRITICAL EMERGENCY ESCALATION HUB
              </div>
              <div className="hg-emergency-profile-card">
                <div className="hg-emerg-profile-row"><span className="hg-emerg-label">Patient</span><span className="hg-emerg-val">PAT-EMERG-99</span></div>
                <div className="hg-emerg-profile-row"><span className="hg-emerg-label">Blood Type</span><span className="hg-emerg-val hg-emerg-critical">O-negative</span></div>
                <div className="hg-emerg-profile-row"><span className="hg-emerg-label">Antibody Profile</span><span className="hg-emerg-val hg-emerg-critical">Rare Multi-Antibody<br/>(anti-K, anti-E, anti-c, anti-C)</span></div>
                <div className="hg-emerg-profile-row"><span className="hg-emerg-label">Window</span><span className="hg-emerg-val hg-emerg-critical">2 Days</span></div>
              </div>
              <div className="hg-emergency-terminal">
                <div className="hg-terminal-header">⬡ MULTI-AGENT ROUTING TRACE</div>
                <div className="hg-terminal-line hg-terminal-error">↳ [0.0s] ERROR: 0 safe units found within local 5km grid radius. Inventory safety lock released.</div>
                <div className="hg-terminal-line hg-terminal-warn">↳ [0.2s] ESCALATING: Removing geographical boundary constraints… Opening 100km regional dragnet.</div>
                <div className="hg-terminal-line hg-terminal-broadcast">↳ [0.5s] BROADCASTING: Emergency alert payloads routed to State Transfusion Council and Regional Hospital Networks.</div>
              </div>
              {proposalLoading && <div className="hg-activity-loading" style={{ color: '#ef4444' }}>Engaging emergency agent matrix…</div>}
              <div className="hg-approval-buttons" style={{ marginTop: 14 }}>
                <button
                  className="hg-btn-broadcast-emergency"
                  disabled={!proposalResp || proposalLoading || !!approveResp}
                  onClick={() => handleDecision('approve')}
                >
                  🚨 ACTIVATE EMERGENCY REGIONAL BROADCAST
                </button>
              </div>
              {approveLoading && <div className="hg-activity-loading" style={{ color: '#ef4444' }}>Broadcasting…</div>}
              {approveResp && (
                <div className="hg-approval-result" style={{ margin: '10px 0 0', background: 'rgba(220,38,38,0.08)', color: '#b91c1c', border: '1px solid rgba(220,38,38,0.3)' }}>
                  🚨 Emergency broadcast activated — State Transfusion Council notified
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── PAT-EMERG-99 committed banner ─────────────────────────────── */}
        {activePatientId === 'PAT-EMERG-99' && isApproved('PAT-EMERG-99') && (
          <div className="tactical-right-body">
            <div className="hg-committed-banner">
              <div className="hg-committed-header">
                ✓ THIS TRANSFUSION MATRIX HAS BEEN COMMITTED AND ROUTED
              </div>
            </div>
          </div>
        )}

        {/* ── Standard intelligence panel ───────────────────────────────── */}
        {activePatientId !== 'PAT-0001' && activePatientId !== 'PAT-EMERG-99' && activityPanelVisible ? (
          <div className="tactical-right-body">
            {proposalLoading && <div className="hg-activity-loading">Running agents...</div>}
            {proposalError   && <div className="hg-error-inline">{proposalError}</div>}

            {activityEvents.length > 0 && (
              <div className="hg-activity-feed">
                {activityEvents.map((evt, i) => {
                  const isLast      = i === activityEvents.length - 1
                  const isGate      = evt.node === 'approval'
                  const nodeColor   = NODE_COLORS[evt.node] ?? '#546e7a'
                  const isTerminal  = ['redistribution','donor_matching','emergency','declined'].includes(evt.node)
                  return (
                    <div key={evt.step_index} className="hg-activity-step">
                      <div className="hg-activity-step-meta">
                        <span className="hg-activity-step-num" style={{ background: nodeColor }}>
                          {evt.step_index + 1}
                        </span>
                        <span className="hg-activity-node-chip">{NODE_CHIPS[evt.node] ?? evt.node}</span>
                        {isTerminal && approveResp && (
                          <span className={`hg-activity-node-chip hg-chip-status hg-status-${approveResp.status}`}>
                            {approveResp.status}
                          </span>
                        )}
                      </div>
                      <div className="hg-activity-agent" style={{ color: isGate ? nodeColor : undefined }}>
                        {evt.agent}
                      </div>
                      <div className="hg-activity-summary">{evt.summary}</div>
                      {evt.node === 'orchestrate' && (() => {
                        const d = evt.details as unknown as OrchestrateEventDetails
                        return (
                          <>
                            {d.narration && (
                              <div className="hg-activity-narration">{d.narration}</div>
                            )}
                            {(d.need_clock_days != null || d.supply_clock_days != null || d.transport_tier != null || d.deliverable != null) && (
                              <div className="hg-orch-meta">
                                {d.need_clock_days != null && <span>Need: {d.need_clock_days}d</span>}
                                {d.supply_clock_days != null && <span>Supply: {typeof d.supply_clock_days === 'number' ? `${d.supply_clock_days.toFixed(4)}d` : d.supply_clock_days}</span>}
                                {d.transport_tier != null && <span>Tier: {d.transport_tier === 0 ? 'local' : 'far'}</span>}
                                {d.deliverable != null && (
                                  <span className={d.deliverable ? 'hg-deliv-yes' : 'hg-deliv-no'}>
                                    {d.deliverable ? '✓ deliverable' : '✗ not deliverable'}
                                  </span>
                                )}
                              </div>
                            )}
                            {d.agent_reasoning && (
                              <div className="hg-agent-reasoning">
                                <strong>Agent:</strong> {d.agent_reasoning}
                                {d.agent_validation && <span className="hg-agent-val"> [{d.agent_validation}]</span>}
                              </div>
                            )}
                          </>
                        )
                      })()}
                      {!isLast && <div className="hg-activity-connector" />}
                    </div>
                  )
                })}
              </div>
            )}

            {/* Committed banner — standard patients only */}
            {activePatientId && isApproved(activePatientId) && (
              <div className="hg-committed-banner">
                <div className="hg-committed-header">
                  ✓ THIS TRANSFUSION MATRIX HAS BEEN COMMITTED AND ROUTED
                </div>
              </div>
            )}

            {/* HITL Approval card — only shown for non-approved patients */}
            {proposalResp && !approveResp && !approveLoading && !(activePatientId && isApproved(activePatientId)) && (
              <div className={`hg-approval-card${proposalResp.proposal.chosen_lever ? ` hg-approval-card-${proposalResp.proposal.chosen_lever}` : ''}`}>
                <div className="hg-approval-title">Coordinator approval required</div>
                {(() => {
                  const pa = proposalResp.proposal.proposed_action
                  return (
                    <div className="hg-approval-action">
                      {pa.type === 'redistribute' && (<>
                        <span className="hg-approval-type-badge" style={{ background: LEVER_COLORS.inventory }}>Redistribute</span>
                        <div className="hg-approval-detail">
                          <strong>{pa.bank_id}</strong>
                          {pa.bank_name && <span className="hg-approval-bankname"> — {pa.bank_name}</span>}
                        </div>
                        <div className="hg-approval-facts">
                          {pa.days_to_expiry !== undefined && `Expires in ${pa.days_to_expiry}d`}
                          {pa.distance_km !== undefined && ` · ${pa.distance_km} km`}
                          {` → ${pa.recipient}`}
                        </div>
                      </>)}
                      {pa.type === 'activate_donor' && (<>
                        <span className="hg-approval-type-badge" style={{ background: LEVER_COLORS.donor }}>Activate donor</span>
                        <div className="hg-approval-detail">
                          <strong>{pa.donor_id}</strong>
                          {pa.bonded && <span className="hg-bonded-tag">bonded</span>}
                        </div>
                        <div className="hg-approval-facts">
                          {pa.score !== undefined && `score ${pa.score.toFixed(4)}`}
                          {pa.distance_km !== undefined && ` · ${pa.distance_km} km`}
                          {` → ${pa.recipient}`}
                        </div>
                      </>)}
                      {pa.type === 'emergency_escalation' && (<>
                        <span className="hg-approval-type-badge" style={{ background: LEVER_COLORS.emergency }}>Emergency escalation</span>
                        <div className="hg-approval-detail">
                          Escalate to regional network for {pa.recipient}
                        </div>
                      </>)}
                    </div>
                  )
                })()}

                {proposalResp.proposal.chosen_lever === 'donor' && proposalResp.donor_message_draft && (
                  <div className="hg-donor-msg-block">
                    <div className="hg-donor-msg-label">Donor Activation Message</div>
                    <div className="hg-donor-msg-text">{proposalResp.donor_message_draft}</div>
                  </div>
                )}

                {proposalResp.proposal.chosen_lever === 'emergency' && proposalResp.emergency_reasoning && (
                  <div className="hg-emergency-reasoning-block">
                    <div className="hg-emergency-reasoning-label">Emergency Escalation — Regional Dragnet Active</div>
                    <div className="hg-emergency-reasoning-text">{proposalResp.emergency_reasoning}</div>
                  </div>
                )}

                <div className="hg-approval-buttons">
                  {proposalResp.proposal.chosen_lever === 'donor' ? (
                    <button className="hg-btn-dispatch-sms" onClick={() => handleDecision('approve')}>
                      DISPATCH SMS OUTREACH
                    </button>
                  ) : proposalResp.proposal.chosen_lever === 'emergency' ? (
                    <button className="hg-btn-broadcast-emergency" onClick={() => handleDecision('approve')}>
                      BROADCAST EMERGENCY ALERT
                    </button>
                  ) : (
                    <>
                      <button className="hg-btn-approve" onClick={() => handleDecision('approve')}>
                        Approve
                      </button>
                      <button className="hg-btn-reject" onClick={() => handleDecision('reject')}>
                        Reject
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}

            {approveLoading && <div className="hg-activity-loading">Processing decision...</div>}
            {approveError   && <div className="hg-error-inline">{approveError}</div>}

            {approveResp && (
              <div className={`hg-approval-result hg-result-${approveResp.status}`}>
                {approveResp.status === 'fulfilled' ? (
                  <>Action approved and queued — {LEVER_LABELS[approveResp.chosen_lever]}</>
                ) : (
                  <>Action declined — no change to inventory or donor records</>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="tactical-empty">
            <div className="tactical-empty-icon">🤖</div>
            <div className="tactical-empty-text">
              Select a patient to run the agent analysis and review the HITL approval workflow
            </div>
          </div>
        )}
      </div>

      {/* ══════════════════════════════════════════════════════════════════
          SMS GATEWAY — Fixed bottom-right smartphone receiver panel
      ══════════════════════════════════════════════════════════════════ */}
      <div className={`hg-sms-gateway${(receivedSMS.length > 0 || smsSending) && !smsGatewayClosed ? ' hg-sms-gateway-active' : ''}`}>
        <div className="hg-sms-gateway-title">
          📟 CENTRAL GATEWAY: LIVE RECEIVER NODES
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {receivedSMS.length > 0 && (
              <span className="hg-sms-count-badge">{receivedSMS.length}</span>
            )}
            {(receivedSMS.length > 0 || smsSending) && (
              <button className="hg-sms-close-btn" onClick={() => setSmsGatewayClosed(true)}>
                [ CLOSE × ]
              </button>
            )}
          </div>
        </div>
        <div className="hg-sms-phone-body">
          {smsSending && (
            <div className="hg-sms-sending">
              <span className="hg-sms-sending-dot">●</span> TRANSMITTING ENCRYPTED PAYLOAD…
            </div>
          )}
          {receivedSMS.length === 0 && !smsSending && (
            <div className="hg-sms-idle">Awaiting outreach payloads…</div>
          )}
          {receivedSMS.map((msg, i) => (
            <div key={i} className="hg-sms-message-wrap">
              <div className="hg-sms-inbound-tag">💬 INBOUND ENCRYPTED SMS RECEIVED</div>
              <div className="hg-sms-bubble">
                <div className="hg-sms-from-line">FROM: {msg.from}</div>
                <div className="hg-sms-body-text">{msg.body}</div>
                <div className="hg-sms-timestamp">{msg.time}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

    </div>
  )
}
