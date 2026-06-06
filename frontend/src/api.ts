const API_BASE = 'http://localhost:8000'

export interface HealthResponse {
  status: string
  dataset: {
    donors: number
    patients: number
    banks: number
    valid_coord_banks: number
    inventory_units: number
  }
  live_mode: boolean
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/api/health`)
  if (!res.ok) throw new Error(`API ${res.status} — health check failed`)
  return res.json() as Promise<HealthResponse>
}

// ---------------------------------------------------------------------------
// Stage-demo chaos mode — toggled by Ctrl+Shift+X in the UI
// ---------------------------------------------------------------------------
let _chaosActive = false

export function activateChaosMode(): void { _chaosActive = true }
export function deactivateChaosMode(): void { _chaosActive = false }
export function isChaosActive(): boolean { return _chaosActive }

function chaosHeaders(): Record<string, string> {
  return _chaosActive ? { 'X-HemoGrid-Chaos': 'inject-timeout' } : {}
}

/** Mirrors hemogrid/api/main.py BankSummary exactly — field names are the contract. */
export interface BankSummary {
  bank_id: string
  name: string
  lat: number
  lng: number
  category: string | null
  does_components: boolean
  district: string | null
  state: string
  coord_valid: boolean
}

export async function fetchBanks(district?: string): Promise<BankSummary[]> {
  const params = new URLSearchParams()
  // valid_only defaults to true on the backend; no need to pass it explicitly.
  if (district) params.set('district', district)
  const url = `${API_BASE}/api/banks${params.size ? '?' + params : ''}`
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`API ${res.status} — is the backend running on port 8000?`)
  }
  return res.json() as Promise<BankSummary[]>
}

/** Mirrors hemogrid/api/main.py CellDesertScore exactly — field names are the contract. */
export interface DesertCell {
  cell_id: string
  lat: number
  lng: number
  name: string
  patients_due: number
  demand_units: number
  raw_units: number
  safe_units: number
  met: number
  compatibility_gap: number
  supply_gap: number
  desert_score: number
  desert_type: 'SUPPLY_LIMITED' | 'COMPATIBILITY_LIMITED' | 'MIXED' | 'OK'
  nearest_safe_inventory_km: number | null
  eligible_matched_donors_nearby: number
  classification: 'CHRONIC' | 'ACUTE' | 'OK'
  structural_recommendation: string
}

export async function fetchDeserts(): Promise<DesertCell[]> {
  const res = await fetch(`${API_BASE}/api/deserts`, { headers: chaosHeaders() })
  if (!res.ok) {
    throw new Error(`API ${res.status} — is the backend running on port 8000?`)
  }
  return res.json() as Promise<DesertCell[]>
}

/** Mirrors hemogrid/api/main.py PatientSummary exactly. */
export interface PatientSummary {
  patient_id: string
  abo: string
  rh_d: boolean
  known_antibodies: string[]
  clinic_id: string
  days_until_due: number
  due_soon: boolean
  units_per_session: number
  status: 'pending' | 'approved' | 'rejected'
}

export async function fetchDuePatients(clinicId: string): Promise<PatientSummary[]> {
  const params = new URLSearchParams({ clinic_id: clinicId, due_soon: 'true' })
  const res = await fetch(`${API_BASE}/api/patients?${params}`)
  if (!res.ok) {
    throw new Error(`API ${res.status} — is the backend running on port 8000?`)
  }
  return res.json() as Promise<PatientSummary[]>
}

/** Mirrors hemogrid/api/main.py PhenotypeOut exactly. */
export interface PhenotypeOut {
  C: boolean | null
  c: boolean | null
  E: boolean | null
  e: boolean | null
  K: boolean | null
}

/** Mirrors hemogrid/api/main.py ChosenInventoryOut exactly. */
export interface ChosenInventoryOut {
  bank_id: string
  bank_name: string
  component: string
  abo: string
  rh_d: boolean
  phenotype_tags: PhenotypeOut | null
  days_to_expiry: number
  distance_km: number | null
  inventory_options: number
}

/** Mirrors hemogrid/api/main.py DonorBreakdownOut exactly. */
export interface DonorBreakdownOut {
  proximity_km: number
  proximity_score: number
  reliability: number
  phenotype_quality: number
  bonded: boolean
  bond_bonus: number
}

/** Mirrors hemogrid/api/main.py ChosenDonorOut exactly. */
export interface ChosenDonorOut {
  donor_id: string
  abo: string
  rh_d: boolean
  distance_km: number
  reliability_score: number
  bonded: boolean
  score: number
  breakdown: DonorBreakdownOut
  candidates_ranked: number
}

/** Mirrors hemogrid/api/main.py RankedInventoryItem exactly. */
export interface RankedInventoryItem {
  rank: number
  bank_id: string
  bank_name: string
  abo: string
  rh_d: boolean
  days_to_expiry: number
  distance_km: number | null
}

/** Mirrors hemogrid/api/main.py RankedDonorItem exactly. */
export interface RankedDonorItem {
  rank: number
  donor_id: string
  abo: string
  rh_d: boolean
  distance_km: number
  reliability: number
  phenotype_quality: number
  bonded: boolean
  score: number
}

/** Mirrors hemogrid/api/main.py MatchResult exactly. */
export interface MatchResult {
  patient_id: string
  abo: string
  rh_d: boolean
  known_antibodies: string[]
  days_until_due: number
  chosen_lever: 'inventory' | 'donor' | 'emergency'
  chosen_inventory: ChosenInventoryOut | null
  chosen_donor: ChosenDonorOut | null
  ranked_inventory: RankedInventoryItem[]
  ranked_donors: RankedDonorItem[]
  reasoning: string
}

export async function fetchMatch(patientId: string): Promise<MatchResult> {
  const res = await fetch(`${API_BASE}/api/patients/${encodeURIComponent(patientId)}/match`)
  if (!res.ok) {
    throw new Error(`API ${res.status} — patient ${patientId} not found or backend error`)
  }
  return res.json() as Promise<MatchResult>
}

/** Details shape for the orchestrate event (node === 'orchestrate'). */
export interface OrchestrateEventDetails {
  chosen_lever: string
  narration?: string
  need_clock_days?: number | null
  supply_clock_days?: number | null
  transport_tier?: number | null
  deliverable?: boolean | null
  agent_reasoning?: string | null
  agent_validation?: string | null
}

/** Mirrors hemogrid/api/main.py ActivityEventOut exactly — field names are the contract. */
export interface ActivityEvent {
  step_index: number
  agent: string
  node: string
  summary: string
  details: Record<string, unknown>
}

/** Mirrors hemogrid/api/main.py ActivityFeedOut exactly. */
export interface ActivityFeed {
  patient_id: string
  chosen_lever: 'inventory' | 'donor' | 'emergency'
  events: ActivityEvent[]
}

export async function fetchActivity(patientId: string): Promise<ActivityFeed> {
  const res = await fetch(
    `${API_BASE}/api/patients/${encodeURIComponent(patientId)}/activity`,
    { headers: chaosHeaders() },
  )
  if (!res.ok) {
    throw new Error(`API ${res.status} — patient ${patientId} not found or backend error`)
  }
  return res.json() as Promise<ActivityFeed>
}

/** Mirrors hemogrid/api/main.py ProposedActionOut exactly. */
export interface ProposedAction {
  type: 'redistribute' | 'activate_donor' | 'emergency_escalation'
  recipient: string
  bank_id?: string
  bank_name?: string
  days_to_expiry?: number
  distance_km?: number
  donor_id?: string
  score?: number
  bonded?: boolean
}

/** Mirrors hemogrid/api/main.py ProposalOut exactly. */
export interface ProposalOut {
  patient_id: string
  chosen_lever: 'inventory' | 'donor' | 'emergency'
  proposed_action: ProposedAction
  reasoning: string
}

/** Mirrors hemogrid/api/main.py ProposalResponse exactly. */
export interface ProposalResponse {
  thread_id: string
  status: 'awaiting_approval'
  proposal: ProposalOut
  events_so_far: ActivityEvent[]
  donor_message_draft?: string      // present when chosen_lever === 'donor'
  emergency_reasoning?: string      // present when chosen_lever === 'emergency'
}

/** Mirrors hemogrid/api/main.py ApproveRequest exactly. */
export interface ApproveRequest {
  thread_id: string
  decision: 'approve' | 'reject'
}

/** Mirrors hemogrid/api/main.py ApproveResponse exactly. */
export interface ApproveResponse {
  status: 'fulfilled' | 'declined'
  chosen_lever: 'inventory' | 'donor' | 'emergency'
  events: ActivityEvent[]
  emergency_reasoning?: string      // present when chosen_lever === 'emergency'
}

export async function proposeAction(patientId: string): Promise<ProposalResponse> {
  const res = await fetch(
    `${API_BASE}/api/patients/${encodeURIComponent(patientId)}/propose`,
    { method: 'POST', headers: { 'Content-Type': 'application/json', ...chaosHeaders() } },
  )
  if (!res.ok) {
    throw new Error(`API ${res.status} — propose failed for ${patientId}`)
  }
  return res.json() as Promise<ProposalResponse>
}

export async function approveAction(
  patientId: string,
  body: ApproveRequest,
): Promise<ApproveResponse> {
  const res = await fetch(
    `${API_BASE}/api/patients/${encodeURIComponent(patientId)}/approve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) {
    throw new Error(`API ${res.status} — approve failed for ${patientId}`)
  }
  return res.json() as Promise<ApproveResponse>
}

// ---------------------------------------------------------------------------
// Demo state endpoints
// ---------------------------------------------------------------------------

/** patient_id → "APPROVED" | "REJECTED" */
export type PatientStatuses = Record<string, 'APPROVED' | 'REJECTED'>

export async function fetchDemoStatuses(): Promise<PatientStatuses> {
  const res = await fetch(`${API_BASE}/api/demo/statuses`)
  if (!res.ok) throw new Error(`API ${res.status} — demo statuses fetch failed`)
  return res.json() as Promise<PatientStatuses>
}

export interface DemoAdjustments {
  bank_adjustments: Record<string, number>
  cell_adjustments: Record<string, { met_delta: number; supply_gap_delta: number }>
}

export async function fetchDemoAdjustments(): Promise<DemoAdjustments> {
  const res = await fetch(`${API_BASE}/api/demo/adjustments`)
  if (!res.ok) throw new Error(`API ${res.status} — demo adjustments fetch failed`)
  return res.json() as Promise<DemoAdjustments>
}

export async function resetDemo(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE}/api/demo/reset`, { method: 'POST' })
  if (!res.ok) throw new Error(`API ${res.status} — demo reset failed`)
  return res.json()
}
