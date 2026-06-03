const API_BASE = 'http://localhost:8000'

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
}

export async function fetchDeserts(): Promise<DesertCell[]> {
  const res = await fetch(`${API_BASE}/api/deserts`)
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
