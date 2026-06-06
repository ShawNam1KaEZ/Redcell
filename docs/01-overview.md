# 01 — Project Overview

## What HemoGrid Is

HemoGrid is a predictive blood logistics intelligence platform designed for the Indian thalassemia transfusion ecosystem. The system connects thalassemia centres (clinics) with blood banks and voluntary donors to solve a structural supply problem: chronically transfused thalassemia patients require highly compatible blood — matched not just on ABO/Rh but on extended antigens (Kell, Rh C/c/E/e) and specific alloantibodies — and current reactive processes leave supply chains unable to anticipate or avert shortfalls before they become emergencies.

HemoGrid was built for a hackathon with a CSR (Corporate Social Responsibility) framing: demonstrating how data infrastructure can shift blood supply management from reactive ("patient arrives, we search for blood") to predictive ("patient will arrive in 5 days, we ensure blood is ready now").

## The Problem Domain

**Thalassemia patients** require PRBC (Packed Red Blood Cell) transfusions on a 21–28 day recurring cycle for life. In India, roughly 150,000 patients are registered with this condition. Because each patient receives tens to hundreds of transfusions over their lifetime, a significant fraction (~20%) develop **alloantibodies** — immune reactions to specific blood antigens (anti-K, anti-E, anti-c being the most common). Once alloimmunized, a patient can only receive blood that is negative for the triggering antigen(s), dramatically narrowing the compatible donor and inventory pool.

**Blood Bridge** is the concept of a standing matched-donor registry: donors who have previously donated for a specific alloimmunized patient and whose phenotype is known to be compatible. These "bonded" donors are a critical supply path when bank inventory is insufficient.

## The Core Thesis

The platform rests on two main ideas:

1. **Reactive → Predictive**: Transfusion dates are deterministic (last date + interval). The system can forecast who will need blood in the next 7 days and pre-calculate which source (inventory unit or donor) is the best match, days in advance.

2. **Deterministic engine / LLM-only-at-edges**: All matching, ranking, safety gating, desert scoring, and lever selection are pure deterministic Python (`hemogrid/engine.py`). The LLM is used exclusively to narrate already-made decisions, draft donor outreach messages, and generate structural recommendations. It cannot change any outcome.

## The Two Supply Levers

When a patient's transfusion is due, the engine selects one of three responses:

| Lever | Meaning | When chosen |
|-------|---------|-------------|
| `inventory` | Redistribute a near-expiry PRBC unit from a nearby blood bank | Compatible, antibody-safe PRBC unit exists within 100 km and can be delivered before the need clock expires |
| `donor` | Activate an eligible bonded or matched voluntary donor | No suitable inventory; an eligible, compatible, antibody-safe donor exists within 100 km |
| `emergency` | Escalate to the regional emergency network | Neither inventory nor donor found within the search radius |

The `inventory` lever also serves an anti-wastage purpose: units are ranked by soonest-to-expire first, so redistribution prevents discards.

## The Orchestrator

A LangGraph agent graph (`hemogrid/agents/graph.py`) sequences four pipeline stages per patient: **forecast → desert → orchestrate → approval_gate**. After the engine selects the lever in the orchestrate node, the graph pauses at a Human-in-the-Loop (HITL) gate requiring a coordinator's explicit approval before any action is committed.

## The Blood Desert Model

The system classifies each of the 9 clinic cells into:
- **OK**: demand fully met by antibody-safe inventory
- **ACUTE**: raw supply shelf is too thin (volume shortfall)
- **COMPATIBILITY_LIMITED**: inventory exists but fails the antibody-safety gate (immunological barrier)
- **MIXED**: both gap types present

A `CHRONIC` desert arises when the cell is `COMPATIBILITY_LIMITED` with a high score (≥ 10), indicating a structural, persistent problem that redistribution alone cannot fix.

## Who the Users Are

- **Blood Bank Coordinators**: The primary user. They review predicted transfusion needs, view the engine's recommendation (lever + reasoning + donor/inventory details), and approve or reject the proposed action. They never interact with raw data — only coordinator-facing summaries and approve/reject buttons.
- **HITL reviewers**: The system forces a runtime pause before any action. No dispatch, no state mutation, no outreach happens without an explicit human approval click.
- **System administrators**: Can reset demo state via `POST /api/demo/reset` and toggle live vs. synthetic data via `HEMOGRID_USE_LIVE_DATA`.

## Hackathon/CSR Context

HemoGrid was developed as a multi-phase hackathon project:
- **Phase 1**: Real blood bank data load + canonical models
- **Phase 2**: Synthetic patients, donors, inventory; enrichment constants
- **Phase 3**: Engine (compatibility, ranking, desert, lever selection)
- **Phase 4**: LangGraph agent graph + HITL gate + LLM narration
- **Phase 5**: Live data integration (`LiveHybridSource`), UI polish, demo scenarios

## What "Done" Means Here vs What Needs Improvement

The system is functionally complete: data loads, engine runs, agents orchestrate, API serves, and the frontend displays results. All three golden demo scenarios work as specified.

Known outstanding issues (documented in detail in [docs/10](10-data-flow-and-known-issues.md)):
- `cleaned_thalassemia_data.csv` (a cleaned version of the hackathon data) exists in `newdata/` but is not read by any source code — may be the "new data" that is not reflecting in the UI
- `TODAY_SIMULATION` in `LiveHybridSource` is hardcoded to `2026-06-05`, causing live patient transfusion dates to drift from `date.today()` calculations in the API
- Several hardcoded values in the frontend (PAT-0001 module) may diverge from live engine output
