import { useState } from 'react'

// ── Cell vulnerability profiles ──────────────────────────────────────────────
// supplyVuln: sensitivity to demand volatility    [0, 1]
// alloVuln:   sensitivity to alloimmunization density [0, 1]
// Hyderabad (HYD) has the highest alloVuln (0.95) — mirrors the real
// CLN-HYD-01 CHRONIC bottleneck (score 16, COMPATIBILITY_LIMITED).

interface CellProfile {
  id: string
  name: string
  supplyVuln: number
  alloVuln: number
}

const GRID_CELLS: CellProfile[] = [
  { id: 'LKN', name: 'Lucknow',   supplyVuln: 0.95, alloVuln: 0.30 },
  { id: 'DEL', name: 'Delhi',     supplyVuln: 0.40, alloVuln: 0.35 },
  { id: 'AHM', name: 'Ahmedabad', supplyVuln: 0.60, alloVuln: 0.40 },
  { id: 'HYD', name: 'Hyderabad', supplyVuln: 0.20, alloVuln: 0.95 },
  { id: 'GNT', name: 'Guntur',    supplyVuln: 0.70, alloVuln: 0.60 },
  { id: 'BOM', name: 'Mumbai',    supplyVuln: 0.30, alloVuln: 0.25 },
  { id: 'KOL', name: 'Kolkata',   supplyVuln: 0.35, alloVuln: 0.40 },
  { id: 'CHN', name: 'Chennai',   supplyVuln: 0.45, alloVuln: 0.30 },
  { id: 'PUN', name: 'Pune',      supplyVuln: 0.25, alloVuln: 0.20 },
]

type CellClass = 'OK' | 'ACUTE' | 'CHRONIC' | 'MIXED'

interface ComputedCell extends CellProfile {
  supplyContrib: number
  alloContrib: number
  totalScore: number
  classification: CellClass
}

// ── Classification formula ────────────────────────────────────────────────────
//
//   volumeWeight   = demandVolatility / 100          range [0, 1]
//   antibodyWeight = alloimmunizationDensity / 100   range [0, 1]
//
//   supplyContrib  = cell.supplyVuln × volumeWeight   × 100
//   alloContrib    = cell.alloVuln   × antibodyWeight × 100
//   totalScore     = supplyContrib + alloContrib
//
//   if totalScore < 10                          → OK
//   elif alloContrib > supplyContrib × 1.5     → CHRONIC DESERT
//   elif supplyContrib > alloContrib × 1.5     → ACUTE SHORTFALL
//   else                                        → MIXED
//
// HYD verification at antibodyWeight=1.0, volumeWeight=0.0:
//   alloContrib  = 0.95 × 1.0 × 100 = 95.0
//   supplyContrib= 0.20 × 0.0 × 100 =  0.0
//   95.0 > 0.0 × 1.5 → CHRONIC  ✓  (reproduces CLN-HYD-01 signature)

function classifyCell(
  cell: CellProfile,
  volumeWeight: number,
  antibodyWeight: number,
): ComputedCell {
  const supplyContrib = cell.supplyVuln * volumeWeight * 100
  const alloContrib   = cell.alloVuln   * antibodyWeight * 100
  const totalScore    = supplyContrib + alloContrib

  let classification: CellClass
  if (totalScore < 10) {
    classification = 'OK'
  } else if (alloContrib > supplyContrib * 1.5) {
    classification = 'CHRONIC'
  } else if (supplyContrib > alloContrib * 1.5) {
    classification = 'ACUTE'
  } else {
    classification = 'MIXED'
  }

  return { ...cell, supplyContrib, alloContrib, totalScore, classification }
}

const CLASS_BG: Record<CellClass, string> = {
  CHRONIC: '#fef2f2',
  ACUTE:   '#fff7ed',
  MIXED:   '#faf5ff',
  OK:      '#f0fdf4',
}
const CLASS_BORDER: Record<CellClass, string> = {
  CHRONIC: '#fca5a5',
  ACUTE:   '#fdba74',
  MIXED:   '#d8b4fe',
  OK:      '#86efac',
}
const CLASS_LABEL: Record<CellClass, string> = {
  CHRONIC: 'CHRONIC DESERT',
  ACUTE:   'ACUTE SHORTFALL',
  MIXED:   'MIXED',
  OK:      'OK',
}
const CLASS_COLOR: Record<CellClass, string> = {
  CHRONIC: '#0f172a',
  ACUTE:   '#0f172a',
  MIXED:   '#0f172a',
  OK:      '#0f172a',
}

const RECOMMENDATIONS: Record<CellClass, string> = {
  CHRONIC: 'Activate phenotype-matched donors (K-neg, E-neg). Expand Blood Bridge bonded-donor pool within 50 km. Launch systematic alloimmunization screening. Structural fix — inventory alone cannot resolve.',
  ACUTE:   'Trigger Tier-0 redistribution from nearest surplus blood banks. Issue urgent collection drives in adjacent zones. Prioritize O-neg and high-demand ABO groups for emergency replenishment.',
  MIXED:   'Dual intervention: (1) Immediate Tier-0 inventory redistribution for volume gap, (2) Phenotype-matched donor activation for compatibility gap. Prioritise by need clock.',
  OK:      'All demand met with antibody-safe inventory. No intervention required.',
}

interface Props {
  onClose: () => void
}

export function GridSimulator({ onClose }: Props) {
  const [demandVolatility,       setDemandVolatility]       = useState(30)
  const [alloimmunizationDensity, setAlloimmunizationDensity] = useState(20)

  const volumeWeight   = demandVolatility / 100
  const antibodyWeight = alloimmunizationDensity / 100

  const computedCells = GRID_CELLS.map(cell =>
    classifyCell(cell, volumeWeight, antibodyWeight)
  )

  const chronicCount = computedCells.filter(c => c.classification === 'CHRONIC').length
  const acuteCount   = computedCells.filter(c => c.classification === 'ACUTE').length
  const mixedCount   = computedCells.filter(c => c.classification === 'MIXED').length

  let dominantClass: CellClass = 'OK'
  if (antibodyWeight > volumeWeight + 0.20 && chronicCount > 0) dominantClass = 'CHRONIC'
  else if (volumeWeight > antibodyWeight + 0.20 && acuteCount > 0)   dominantClass = 'ACUTE'
  else if (chronicCount + acuteCount + mixedCount > 0)               dominantClass = 'MIXED'

  // Find HYD cell for verification display
  const hydCell = computedCells.find(c => c.id === 'HYD')!

  return (
    <div className="hg-sim-panel hg-sim-panel-light">
      <div className="hg-sim-header">
        <span className="hg-sim-title">Live Grid Matrix Simulation</span>
        <button className="hg-sim-close" onClick={onClose}>×</button>
      </div>

      {/* ── Routing rules text buffer ───────────────────────────────────────── */}
      <div className="hg-sim-rulebox">
        <span className="hg-sim-rule-head">Deterministic Routing Rules — </span>
        Two independent failure modes drive classification.{' '}
        <span className="hg-sim-tag-acute">ACUTE SHORTFALL</span>{' '}
        = raw demand exceeds inventory volume; fix via redistribution.{' '}
        <span className="hg-sim-tag-chronic">CHRONIC DESERT</span>{' '}
        = inventory exists but the antibody-safety gate rejects it (dense anti-K / anti-E
        alloimmunization); fix via phenotype-matched donor activation.
        Threshold: Allo &gt; Supply × 1.5 → CHRONIC · Supply &gt; Allo × 1.5 → ACUTE · else MIXED.
      </div>

      {/* ── Sliders ────────────────────────────────────────────────────────── */}
      <div className="hg-sim-sliders">
        <div className="hg-sim-pitch-insight">
          💡 <strong>PITCH INSIGHT:</strong> HemoGrid differentiates failure signatures automatically. If Volume dominates, the system flags an <strong>ACUTE SHORTFALL</strong> (resolved by shifting stock). If Alloimmunization trends dominate, it flags a <strong>CHRONIC DESERT</strong>, signaling an absolute matching bottleneck where simple inventory dumps fail, forcing the platform to scale to localized matched-donor registries.
        </div>
        <div className="hg-sim-slider-row">
          <div className="hg-sim-slider-meta">
            <span className="hg-sim-slider-label">Regional Demand Volatility</span>
            <span className="hg-sim-slider-val hg-sim-val-acute">{demandVolatility}</span>
          </div>
          <input
            type="range" min={0} max={100}
            value={demandVolatility}
            onChange={e => setDemandVolatility(Number(e.target.value))}
            className="hg-sim-range hg-sim-range-acute"
            aria-label="Regional Demand Volatility"
          />
        </div>
        <div className="hg-sim-slider-row">
          <div className="hg-sim-slider-meta">
            <span className="hg-sim-slider-label">Patient Alloimmunization Density</span>
            <span className="hg-sim-slider-val hg-sim-val-chronic">{alloimmunizationDensity}</span>
          </div>
          <input
            type="range" min={0} max={100}
            value={alloimmunizationDensity}
            onChange={e => setAlloimmunizationDensity(Number(e.target.value))}
            className="hg-sim-range hg-sim-range-chronic"
            aria-label="Patient Alloimmunization Density"
          />
        </div>
      </div>

      {/* ── 3×3 Grid ───────────────────────────────────────────────────────── */}
      <div className="hg-sim-grid">
        {computedCells.map(cell => (
          <div
            key={cell.id}
            className="hg-sim-cell"
            style={{
              background:   CLASS_BG[cell.classification],
              borderColor:  CLASS_BORDER[cell.classification],
            }}
          >
            <div className="hg-sim-cell-id">{cell.id}</div>
            <div className="hg-sim-cell-name">{cell.name}</div>
            <div className="hg-sim-cell-score" style={{ color: CLASS_COLOR[cell.classification] }}>
              {cell.totalScore.toFixed(1)}
            </div>
            <div
              className="hg-sim-cell-badge"
              style={{
                color:      CLASS_COLOR[cell.classification],
                borderColor: CLASS_BORDER[cell.classification],
              }}
            >
              {CLASS_LABEL[cell.classification]}
            </div>
          </div>
        ))}
      </div>

      {/* ── Live recommendation ────────────────────────────────────────────── */}
      <div
        className="hg-sim-recommendation"
        style={{ borderLeftColor: CLASS_BORDER[dominantClass] }}
      >
        <div
          className="hg-sim-rec-label"
          style={{ color: CLASS_COLOR[dominantClass] }}
        >
          {CLASS_LABEL[dominantClass]} — Structural Recommendation
        </div>
        <div className="hg-sim-rec-text">{RECOMMENDATIONS[dominantClass]}</div>
        <div className="hg-sim-rec-counts">
          {chronicCount > 0 && <span className="hg-sim-count hg-sim-count-chronic">{chronicCount} CHRONIC</span>}
          {acuteCount   > 0 && <span className="hg-sim-count hg-sim-count-acute">{acuteCount} ACUTE</span>}
          {mixedCount   > 0 && <span className="hg-sim-count hg-sim-count-mixed">{mixedCount} MIXED</span>}
        </div>
      </div>

      {/* ── HYD verification readout ───────────────────────────────────────── */}
      <div className="hg-sim-verify">
        <span className="hg-sim-verify-label">HYD trace — </span>
        supplyContrib={hydCell.supplyContrib.toFixed(1)} ·
        alloContrib={hydCell.alloContrib.toFixed(1)} ·
        score={hydCell.totalScore.toFixed(1)} ·
        <span
          style={{ color: CLASS_COLOR[hydCell.classification], fontWeight: 600, marginLeft: 4 }}
        >
          {hydCell.classification}
        </span>
        {hydCell.classification === 'CHRONIC' && (
          <span className="hg-sim-verify-ok"> ✓ CLN-HYD-01 signature reproduced</span>
        )}
      </div>
    </div>
  )
}
