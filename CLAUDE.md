# HemoGrid — Multi-Agent Blood Infrastructure Platform Specification (Phase 5 Polish Live)

## 🚀 Execution Architecture & Port Topologies
- Backend API Process: `uvicorn hemogrid.api.main:app --reload --port 8000` (Executed from project root)
- Frontend Development Server: `cd frontend && npm run dev` (Runs natively on Port 5173)
- Live LLM Harness: Bounded manual prompt loop inside `_agent_select` routing to local Ollama endpoints via a custom `llm.generate()` wrapper module. Default live model is `qwen2.5:7b` (configured via environment flag `HEMOGRID_LLM_MODEL`). If Ollama is offline, system intercepts faults via `LLMUnavailable` and switches seamlessly to f-string fallback scripts.
- Memory Clear Gate: `POST http://localhost:8000/api/demo/reset` (Wipes the volatile cache dictionary and snaps parameters instantly back to default seed data).

## 📊 Core Invariants, Scientific Weights, & Two-Lock Safety
1. Deterministic Engine Core, Edge LLM Only: All systemic calculations—including blood group compatibility, Indian subcontinent phenotype filtering, distance matrices, demand forecasting, desert cell calculations, deliverability clocks, and transport tiering—are handled purely via deterministic Python inside `hemogrid/engine.py`. The LLM computes absolutely nothing. It operates purely at the periphery to (a) narrate chosen execution reasons, (b) draft outreach copy, and (c) offer system-level structural recommendations over grid metrics.
2. Misleading File Format: `data/blood-banks.xls` is secretly a cp1252-encoded CSV file with a `.xls` extension. It must be processed strictly via `pd.read_csv(encoding='cp1252')`, never using native Excel or xlrd parsers.
3. Subcontinent Phenotype Frequencies: Indian regional probability for Kell K-negative is fixed at exactly `0.97` (Antigen frequency `K = 0.03`). Do not drift to the 0.91 Caucasian baseline. Alloimmunization rules mandate that antibodies are only generated against antigens a patient entirely lacks (e.g., anti-K is generated only if the patient is K-negative).
4. Seeding Isolation Invariant: The synthetic database engine uses a static generation seed via `np.random.default_rng(seed=42)`. Core structural entities are sequence-dependent. Any custom test case injection must be appended at the absolute tail-end of the pipeline post-RNG initialization to keep prior object patterns undisturbed.
5. The Two-Lock Safety Model: No agent can autonomously dispatch data or mutate state. The system requires two explicit validation parameters:
   - Deterministic Filtering: The engine restricts options to safe, deliverable, and eligible sets before the LLM even sees them. The final LLM selection is re-validated against this list.
   - Human-in-the-Loop (HITL): The system forces a hard runtime pause via LangGraph interrupts, requiring an explicit manual approval click from a human coordinator before a state transition can be committed.

## 🎯 The Golden Regression Targets & Presentation Profiles
- **PAT-0001 (Aarav):** B+, K-negative, anti-K POSITIVE, Guntur clinic `CLN-GNT-01`, due in 5 days (`need_clock=5d`).
  - Default State: Resolves to the `INVENTORY` lever -> local bank `BB-0036` (Government General Hospital, Guntur), which holds a matching B+ K-neg PRBC unit expiring in ~3 days located 0.7 km away. It wins on soonest-expiry within Transport Tier 0 (local ≤ 5km).
  - Inventory Bypassed State: Resolves to the `DONOR` lever -> `DON-0002` (B+, K-neg, eligible, bonded, 2.4 km away, match score ≈0.9141, `supply_clock=4d`).
- **PAT-EMERG-99:** O-negative, rare multi-antibody profile (`anti-K`, `anti-E`, `anti-c`, `anti-C`), tight 2-day timeline. Forces immediate routing to the `EMERGENCY` lever, expanding search boundaries to a 100km regional dragnet and bypassing local proximity rules.
- **CLN-HYD-01 (Hyderabad):** Map grid cell classified mathematically as a `CHRONIC DESERT` (Score of `16`), driven by deep localized alloimmunization trends rather than a temporary volume shortfall (Acute).

## 📂 Layout Map & File Index
- `hemogrid/`: Core modules container.
  - `models.py`: Pydantic v2 data models inheriting from `CanonicalModel` with explicit field-level provenance tracking.
  - `enrichment.py`: Baseline epidemiological constants for Indian subcontinent antigen distribution profiles.
  - `engine.py`: Pure, side-effect-free matching mathematics, sorting primitives, haversine functions, and desert decomposition algorithms.
  - `llm.py`: Swappable language model interface wrapper. Houses the presentation-grade golden fallback blocks.
  - `api/main.py`: FastAPI application routing layer. Manages the volatile in-memory dictionary singleton state (`_DEMO_CACHE`).
  - `agents/graph.py`: LangGraph state topology definition, `GraphState` types, and native checkpoint interrupts.
- `frontend/src/`: Modern user interface layer.
  - `api.ts`: Strongly typed API schema mapping definitions to enforce code contract synchronization.
  - `MapView.tsx` & `MapView.css`: Premium 3-column Split-Grid presentation interface. Handles conditional component rendering.
  - `GridSimulator.tsx`: Slide-up matrix widget simulating regional supply volatility and crossover thresholds.

## 🛠️ Code Maintenance & Token Discipline Guide
1. Pure Additive Modifications: Never rewrite core logical evaluation primitives inside `engine.py` or modify the sequential structure of data frames.
2. Full Integration Verification: Every backend or frontend iteration must be audited against local simulation harnesses. Frontend mutations must pass clean type verification via `npx tsc --noEmit` before any staging deploy.
3. Clear Context Window Routine: Instruct the developer console to run `/clear` between every logical step to prevent context window saturation and preserve operational memory thresholds.