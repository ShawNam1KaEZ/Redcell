# 08 — Frontend

## File Structure

```
frontend/src/
├── main.tsx          (10 lines)  React entry point
├── App.tsx           (7 lines)   Root component → <MapView />
├── MapView.tsx       (1136 lines) Primary UI — 3-column layout
├── MapView.css       (2338 lines) All UI styles
├── GridSimulator.tsx (255 lines)  Slide-up simulation widget
├── api.ts            (343 lines)  Typed API client
├── index.css         (12 lines)   Global CSS resets
└── App.css           (184 lines)  Root app styles (minimal use)
```

---

## `main.tsx`

Bootstraps React 19 in strict mode onto `<div id="root">`. No significant logic.

## `App.tsx`

```tsx
function App() { return <MapView /> }
```

The entire application is `MapView`. No routing, no providers, no context.

---

## `MapView.tsx` — Primary UI Component

### Responsibilities
- 3-column split-grid layout: Triage Matrix (left) / Leaflet Map (center) / Intelligence Panel (right)
- Fetches and displays blood bank markers, blood desert circles, due-patient list
- Runs `/match` and `/propose` in parallel on patient click
- Presents HITL approval UI (Approve/Reject buttons or specialized PAT-0001/PAT-EMERG-99 modules)
- SMS Gateway panel (bottom-right) for donor activation visualization
- Chaos mode toggle (Ctrl+Shift+X)
- Grid Simulation widget toggle
- Demo reset button

### Key State Variables

| State | Type | Purpose |
|-------|------|---------|
| `banks` | `BankSummary[]` | Blood bank markers for the map |
| `bankStatus` | `'loading'\|'ok'\|'error'` | Bank fetch status |
| `deserts` | `DesertCell[]` | Desert circle data |
| `desertStatus` | `'loading'\|'ok'\|'error'` | Desert fetch status |
| `showDeserts` | `boolean` | Toggle desert circles |
| `showBanks` | `boolean` | Toggle bank markers |
| `selected` | `DesertCell \| null` | Currently selected desert cell (left panel drill-down) |
| `patients` | `PatientSummary[]` | Due patients for selected clinic |
| `activePatientId` | `string \| null` | Currently clicked patient |
| `matchResult` | `MatchResult \| null` | Engine match result from `/match` |
| `matchLoading` | `boolean` | `/match` fetch in progress |
| `proposalResp` | `ProposalResponse \| null` | HITL proposal from `/propose` |
| `proposalLoading` | `boolean` | `/propose` fetch in progress |
| `approveResp` | `ApproveResponse \| null` | Result from `/approve` |
| `approveLoading` | `boolean` | `/approve` in progress |
| `showSimulator` | `boolean` | Toggle `GridSimulator` widget |
| `loadingStep` | `number` | Progress bar step index (0–4) |
| `chaosMode` | `boolean` | Chaos mode active flag |
| `fulfilledIds` | `string[]` | Patient IDs approved this session (local) |
| `stockOverrides` | `Record<string, number>` | Local inventory count adjustments by bank_id |
| `patientStatuses` | `PatientStatuses` | Backend-synced triage decisions |
| `resetLoading` | `boolean` | Demo reset in progress |
| `receivedSMS` | `Array<{from, body, time}>` | SMS gateway messages |
| `smsSending` | `boolean` | SMS sending animation state |
| `liveMode` | `boolean` | From `/api/health`; drives map viewport and bank filter |
| `healthLoaded` | `boolean` | Guards bank fetch until health check completes |

### Key Constants and Lookup Tables

| Constant | Type | Purpose |
|----------|------|---------|
| `LOADING_STEPS` | `string[4]` | 4-step progress bar text |
| `INDIA_CENTER` | `[22.5, 80.0]` | Map center for synthetic mode |
| `INDIA_ZOOM` | `5` | Map zoom for synthetic mode |
| `HYD_CENTER` | `[17.3850, 78.4867]` | Map center for live mode |
| `HYD_ZOOM` | `11` | Map zoom for live mode |
| `DESERT_COLORS` | Record | Desert type → CSS color |
| `DESERT_LABELS` | Record | Desert type → display label |
| `CLASSIFICATION_LABELS` | Record | CHRONIC/ACUTE/OK → badge text |
| `CLASSIFICATION_COLORS` | Record | CHRONIC → purple `#6a1b9a`, ACUTE → orange `#e65100` |
| `DESERT_DESC` | Record | Desert type → tooltip description |
| `LEVER_LABELS` | Record | inventory/donor/emergency → display text |
| `LEVER_COLORS` | Record | inventory → blue `#1565c0`, donor → green `#2e7d32`, emergency → crimson `#b71c1c` |
| `NODE_CHIPS` | Record | node id → chip label |
| `NODE_COLORS` | Record | node id → color |

### `useEffect` Hooks (in order)

1. **Chaos mode keyboard listener**: `Ctrl+Shift+X` toggles `chaosMode`, calls `activateChaosMode()` / `deactivateChaosMode()` in `api.ts`
2. **Loading step ticker**: advances `loadingStep` by 1 every 200ms when step > 0
3. **Loading step reset**: clears `loadingStep` to 0 when `matchLoading` and `proposalLoading` both false
4. **Health check on mount**: `fetchHealth()` → sets `liveMode`, `healthLoaded`
5. **Bank fetch** (depends on `healthLoaded`, `liveMode`): `fetchBanks(liveMode ? undefined : 'Guntur')` — in live mode no district filter; in synthetic mode filters to Guntur only
6. **Desert fetch on mount**: `fetchDeserts()` (no dependency on `liveMode` — always fetches all 9 cells)
7. **Demo statuses sync on mount**: `fetchDemoStatuses()` → sets `patientStatuses`
8. **Patient fetch on cell select** (depends on `selected`): `fetchDuePatients(selected.cell_id)` when a desert cell is clicked; resets all match/proposal/approve state

### Patient Click Handler (`handlePatientClick`)

When a patient row is clicked (and patient is not already approved):
1. Sets `activePatientId`
2. Starts `loadingStep=1`
3. Clears previous match/proposal/approve state
4. Fires **two parallel fetches**:
   - `fetchMatch(patient_id)` → sets `matchResult` + `matchLoading`
   - `proposeAction(patient_id)` → sets `proposalResp` + `proposalLoading`

### Decision Handler (`handleDecision`)

When coordinator clicks Approve or Reject:
1. Sets `approveLoading=true`
2. If `decision == "approve"` and `patient_id == "PAT-0001"`: sets `smsSending=true` (SMS animation)
3. **Optimistic local update**: if approve → adds to `fulfilledIds`, increments `stockOverrides[bank_id]`
4. Calls `approveAction(activePatientId, {thread_id: proposalResp.thread_id, decision})`
5. On success: sets `approveResp`, refreshes `patientStatuses` from backend, re-fetches `deserts` (refreshes map circles)
6. If PAT-0001 donor dispatch: pushes SMS message to `receivedSMS` (from `proposalResp.donor_message_draft` or hardcoded fallback)

### Hardcoded Values in PAT-0001 Module (Intelligence Panel)

The Intelligence Panel has a special section for `activePatientId === 'PAT-0001'` that renders a hardcoded "Bonded Donor Engagement" card:
```tsx
<div className="hg-cred-row"><span>Donor ID</span><span>DON-0002</span></div>
<div className="hg-cred-row"><span>Phenotype Match</span><span>B+, K-negative</span></div>
<div className="hg-cred-row"><span>Proximity</span><span>2.4 km away</span></div>
<div className="hg-cred-row"><span>Match Score</span><span className="accent">0.9141</span></div>
<div className="hg-cred-row"><span>Supply Clock</span><span>4 days</span></div>
```

**These values are hardcoded in JSX, not from the live API response.** The donor activation message displayed in this card uses `proposalResp?.donor_message_draft` (live from API) with a hardcoded fallback string. If the engine produces different values (e.g., different date shifts the 5-day window), the displayed credentials card will be stale.

The `getTriageBadge()` function also hardcodes badge labels by patient ID:
```typescript
if (patientId === 'PAT-EMERG-99') return { label: '🚨 EMERGENCY ESCALATION', cls: 'hg-triage-emergency' }
if (patientId === 'PAT-0001')     return { label: '📡 DONOR MATCH REQ',       cls: 'hg-triage-donor'     }
// all others: { label: '📦 LOCAL RE-ROUTE', cls: 'hg-triage-inventory' }
```

This means every patient except PAT-0001 and PAT-EMERG-99 gets the "LOCAL RE-ROUTE" badge regardless of what lever the engine selects for them.

### Dynamic Desert Score Display

The left panel computes display adjustments locally:
```typescript
const approvedInCell = patients.filter(p => isApproved(p.patient_id)).length
const dynMet         = selected.met + approvedInCell
const rawSupplyGap   = Math.abs(selected.supply_gap)
const dynSupplyGap   = Math.max(0, rawSupplyGap - approvedInCell)
const isStabilized   = dynSupplyGap === 0 && rawSupplyGap > 0
const dynDesertScore = isStabilized ? 0 : selected.desert_score
```

This is a local optimistic overlay; the source-of-truth score is refreshed from the backend after each decision via `fetchDeserts()`.

### Map Configuration

- Leaflet `MapContainer` has `key={liveMode ? 'live' : 'synthetic'}` — remounts (resetting viewport) when live mode changes
- `liveMode=true` → center `[17.3850, 78.4867]` zoom 11 (Hyderabad)
- `liveMode=false` → center `[22.5, 80.0]` zoom 5 (India-wide)
- Desert circles: `CircleMarker` with radius from `desertRadius(score)` and fill opacity from `desertFillOpacity(score, type)`
- Bank markers: `Marker` with `ICON_COMPONENT` (red, `#d32f2f`) or `ICON_STANDARD` (blue, `#1565c0`) based on `does_components`
- The PAT-EMERG-99 active state adds CSS class `pulse-crimson-radar` to all desert circle markers (visual alarm effect)

### SMS Gateway Panel

Fixed bottom-right panel. Shown when `receivedSMS.length > 0` or `smsSending`. Only fires for PAT-0001 approved donor dispatch. Shows hardcoded `"INBOUND ENCRYPTED SMS RECEIVED"` messages. The SMS content comes from `proposalResp.donor_message_draft` (or hardcoded fallback).

---

## `GridSimulator.tsx` — Simulation Widget

**Responsibilities**: Interactive 3×3 grid showing how 9 cities classify based on two slider inputs.

**Sliders**:
- `demandVolatility` (0–100): regional demand volatility
- `alloimmunizationDensity` (0–100): patient alloimmunization density

**Cell profiles** (hardcoded, not from API):
```
LKN (Lucknow):   supplyVuln=0.95, alloVuln=0.30
DEL (Delhi):     supplyVuln=0.40, alloVuln=0.35
AHM (Ahmedabad): supplyVuln=0.60, alloVuln=0.40
HYD (Hyderabad): supplyVuln=0.20, alloVuln=0.95
GNT (Guntur):    supplyVuln=0.70, alloVuln=0.60
BOM (Mumbai):    supplyVuln=0.30, alloVuln=0.25
KOL (Kolkata):   supplyVuln=0.35, alloVuln=0.40
CHN (Chennai):   supplyVuln=0.45, alloVuln=0.30
PUN (Pune):      supplyVuln=0.25, alloVuln=0.20
```

Note: `PUN (Pune)` is included in the simulator but does NOT correspond to any of the 9 canonical clinic centres (which have `CLN-MUM-01` for Mumbai). The simulator is purely a visual/pitch tool — it does not read from the engine.

**Classification formula**:
```
volumeWeight   = demandVolatility / 100
antibodyWeight = alloimmunizationDensity / 100
supplyContrib  = cell.supplyVuln * volumeWeight * 100
alloContrib    = cell.alloVuln   * antibodyWeight * 100
totalScore     = supplyContrib + alloContrib
if totalScore < 10:                → OK
elif alloContrib > supplyContrib * 1.5: → CHRONIC
elif supplyContrib > alloContrib * 1.5: → ACUTE
else:                              → MIXED
```

HYD verification readout is shown at the bottom.

**This widget is completely disconnected from the backend.** It uses hardcoded vulnerability scores, not live engine data.

---

## `api.ts` — Typed API Client

### Base URL
```typescript
const API_BASE = 'http://localhost:8000'
```
Hardcoded. No proxy, no env variable.

### Chaos Mode State
Module-level `_chaosActive: boolean` flag. `chaosHeaders()` returns `{'X-HemoGrid-Chaos': 'inject-timeout'}` when active, else `{}`.

### Interfaces (matching backend DTOs exactly)

| Interface | Matches backend |
|-----------|----------------|
| `HealthResponse` | `HealthResponse` |
| `BankSummary` | `BankSummary` |
| `DesertCell` | `CellDesertScore` |
| `PatientSummary` | `PatientSummary` |
| `PhenotypeOut` | `PhenotypeOut` |
| `ChosenInventoryOut` | `ChosenInventoryOut` |
| `DonorBreakdownOut` | `DonorBreakdownOut` |
| `ChosenDonorOut` | `ChosenDonorOut` |
| `RankedInventoryItem` | `RankedInventoryItem` |
| `RankedDonorItem` | `RankedDonorItem` |
| `MatchResult` | `MatchResult` |
| `OrchestrateEventDetails` | (no backend model — manually typed for `event.node === 'orchestrate'` details) |
| `ActivityEvent` | `ActivityEventOut` |
| `ActivityFeed` | `ActivityFeedOut` |
| `ProposedAction` | `ProposedActionOut` |
| `ProposalOut` | `ProposalOut` |
| `ProposalResponse` | `ProposalResponse` |
| `ApproveRequest` | `ApproveRequest` |
| `ApproveResponse` | `ApproveResponse` |
| `PatientStatuses` | `dict[str, str]` (backend) |
| `DemoAdjustments` | from `GET /api/demo/adjustments` |

### Fetch Functions

| Function | Method | Endpoint |
|----------|--------|----------|
| `fetchHealth()` | GET | `/api/health` |
| `fetchBanks(district?)` | GET | `/api/banks` |
| `fetchDeserts()` | GET | `/api/deserts` |
| `fetchDuePatients(clinicId)` | GET | `/api/patients?clinic_id=X&due_soon=true` |
| `fetchMatch(patientId)` | GET | `/api/patients/{id}/match` |
| `fetchActivity(patientId)` | GET | `/api/patients/{id}/activity` |
| `proposeAction(patientId)` | POST | `/api/patients/{id}/propose` |
| `approveAction(patientId, body)` | POST | `/api/patients/{id}/approve` |
| `fetchDemoStatuses()` | GET | `/api/demo/statuses` |
| `fetchDemoAdjustments()` | GET | `/api/demo/adjustments` |
| `resetDemo()` | POST | `/api/demo/reset` |

**Chaos headers applied to**: `fetchDeserts`, `fetchActivity`, `proposeAction`.
**No chaos headers**: `fetchHealth`, `fetchBanks`, `fetchDuePatients`, `fetchMatch`, `approveAction`, demo endpoints.

### API Mismatches and Notes

1. **`DesertCell.desert_type`**: Frontend types this as `'SUPPLY_LIMITED' | 'COMPATIBILITY_LIMITED' | 'MIXED' | 'OK'` — matches backend.
2. **`ActivityEvent.details`**: Typed as `Record<string, unknown>` in the interface (open-ended). The `OrchestrateEventDetails` interface is a separate manual typing for when `evt.node === 'orchestrate'`, cast with `evt.details as unknown as OrchestrateEventDetails`.
3. **`fetchDemoAdjustments()`** is imported in `api.ts` but **not called** from `MapView.tsx`. The map uses `fetchDemoStatuses()` and refreshes deserts after decisions; it does not use `fetchDemoAdjustments()` directly.
4. **`fetchActivity()`** is defined in `api.ts` but **not called** from `MapView.tsx` (the component uses `proposeAction()` and `approveAction()` instead, which return full event traces). `fetchActivity()` is available but unused in the UI.
