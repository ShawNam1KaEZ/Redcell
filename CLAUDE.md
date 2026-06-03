# HemoGrid — project ground truth for Claude Code

Predictive blood-infrastructure system. Hackathon project. Deterministic core, LLM only at edges.

## Repo layout
- hemogrid/ — backend (models/, sources/, engine.py, enrichment.py, profiler.py, storage.py, llm.py, api/main.py)
- frontend/ — Vite + React + TypeScript + Leaflet (sibling of hemogrid/, NOT inside it)
- data/ — blood-banks.xls, uci_blood_transfusion.csv

## Run
- Backend: `uvicorn hemogrid.api.main:app --reload --port 8000` (from repo root)
- Frontend: `cd frontend && npm run dev` (port 5173)
- Both must be running for the browser to work. Servers do not persist across your shell calls — the USER runs them in their own terminals.

## Hard facts — do not rediscover, do not "fix"
- data/blood-banks.xls is cp1252-encoded CSV with a misleading .xls extension. Read with pd.read_csv(encoding='cp1252'), NOT read_excel/xlrd. This is correct and intentional.
- K-negative ≈ 0.97 in India (NOT 0.91 — that's the Caucasian figure). Do not change.
- Antibodies only generated against antigens a person LACKS (anti-K only if K-negative).
- ABO/Rh PRBC recipient-side: O→O; A→A,O; B→B,O; AB→all; Rh-neg recipient must get Rh-neg.
- Data is deterministic: SyntheticSource().load() uses np.random.default_rng(seed=42). Demo seeding is appended AFTER _generate_inventory so the seeded sequence (and golden objects) is undisturbed. Preserve this placement.

## Golden scenario (everything is built backwards from this — must always hold)
- PAT-0001 (Aarav): B+, K-negative, anti-K POSITIVE, clinic CLN-GNT-01, due ~5 days.
- choose_lever(PAT-0001) → INVENTORY → BB-0036 (B+ K-neg PRBC, ~0.7km, ~3-day expiry).
- Inventory cleared → DONOR → DON-0002 (B+ K-neg, ~2.4km, bonded, score ≈0.914).

## Known fragilities (re-verify if you touch the relevant area)
- DON-0002's identity is sequence-coupled to donor generation. If you change donor generation, re-confirm DON-0002 is still B+/K-neg/bonded to PAT-0001.
- Guntur lever win is EXPIRY-GATED: BB-0036's 3-day unit beats the CLOSER BB-0037's 14-day units only via the soonest-expiry sort. If you touch expiries or nearby inventory, re-verify BB-0036 still wins.

## Architecture rules (non-negotiable)
- Deterministic core: ALL math (compatibility, eligibility, distance, forecasting, scoring, lever choice) lives in engine.py — pure, no LLM, no I/O, no randomness. The engine is the single source of truth for all decision/ranking math.
- API (hemogrid/api/) reads canonical objects through repositories on app.state, never the source directly. API serializes engine output; it contains NO decision logic.
- Frontend reads ONLY from the HTTP API. No hardcoded data.
- Canonical schema + adapter: engine/API/UI read only canonical objects. OrganizerAdapter is the only file touched on hackathon day.
- No autonomous actions (human-in-the-loop). No secrets in code.

## Working style
- One step at a time. Do only what the current prompt asks; do not scaffold ahead.
- Always end by verifying the golden scenario still holds, printing REAL values (not "tests pass").
- Never edit seed data / tests to make a check pass — fix the logic. Flag it if you're tempted.
- End each task with a structured report, then stop.