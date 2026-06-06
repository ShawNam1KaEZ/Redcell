# 03 — Tech Stack and Run Instructions

## Backend Dependencies (installed, verified versions)

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.111.0 | HTTP framework |
| `uvicorn` | 0.30.1 | ASGI server |
| `pydantic` | 2.8.2 | Data validation, canonical models |
| `langgraph` | 0.3.34 | Agent graph / HITL checkpoint |
| `numpy` | 1.26.4 | RNG, array ops for synthetic generation |
| `pandas` | 3.0.3 | CSV loading, blood bank parsing |
| `scikit-learn` | 1.9.0 | Logistic regression for reliability scorer |
| `httpx` | 0.27.0 | HTTP client for Ollama (preferred; falls back to `requests`, then `urllib`) |

No `requirements.txt` was found in the repository. Dependencies must be determined from imports and the installed environment. There is no pinned requirements file — **this is a fragility** (see [docs/10](10-data-flow-and-known-issues.md)).

## Frontend Dependencies (from `frontend/package.json`)

### Runtime
| Package | Version | Purpose |
|---------|---------|---------|
| `react` | ^19.2.6 | UI framework |
| `react-dom` | ^19.2.6 | DOM renderer |
| `leaflet` | ^1.9.4 | Map library |
| `react-leaflet` | ^5.0.0 | React bindings for Leaflet |
| `@types/leaflet` | ^1.9.21 | TypeScript types for Leaflet |

### Dev
| Package | Version | Purpose |
|---------|---------|---------|
| `vite` | ^8.0.12 | Build tool / dev server |
| `typescript` | ~6.0.2 | TypeScript compiler |
| `@vitejs/plugin-react` | ^6.0.1 | Vite React plugin (Babel/SWC) |
| `eslint` | ^10.3.0 | Linter |
| `eslint-plugin-react-hooks` | ^7.1.1 | React hooks rules |
| `eslint-plugin-react-refresh` | ^0.5.2 | Fast-refresh rules |
| `typescript-eslint` | ^8.59.2 | ESLint TypeScript rules |
| `globals` | ^17.6.0 | ESLint browser globals |
| `@types/react` | ^19.2.14 | TypeScript types for React |
| `@types/react-dom` | ^19.2.3 | TypeScript types for React DOM |
| `@types/node` | ^24.12.3 | TypeScript types for Node.js |

## Environment Variables

All variables are read from the process environment at runtime. No `.env` file was found in the repository.

| Variable | Default | Read in | Purpose |
|----------|---------|---------|---------|
| `HEMOGRID_USE_LIVE_DATA` | `"true"` | `hemogrid/api/main.py:_build_dataset()` | `"false"` → use `SyntheticSource(seed=42)`; any other value → use `LiveHybridSource` |
| `HEMOGRID_LLM_PROVIDER` | `"ollama"` | `hemogrid/llm.py:generate()` | `"ollama"` (default), `"off"`, `"none"`, `"stub"` (last three → raise `LLMUnavailable`) |
| `HEMOGRID_LLM_MODEL` | `"qwen2.5:7b"` | `hemogrid/llm.py:_ollama_generate()` | Ollama model name |
| `OLLAMA_HOST` | `"http://localhost:11434"` | `hemogrid/llm.py:_ollama_generate()` | Ollama server base URL |
| `HEMOGRID_LLM_TIMEOUT` | `"20.0"` | `hemogrid/llm.py:_ollama_generate()` | HTTP timeout in seconds (float) |

Note: `HEMOGRID_USE_LIVE_DATA` is read twice — in `_build_dataset()` (uses `"false"` check) and in the lifespan to set `app.state.live_mode` (same logic). The live mode flag is also returned in `GET /api/health`.

## Running the Backend

```bash
# From the project root (c:\Users\Shawn\hackathon-project)
uvicorn hemogrid.api.main:app --reload --port 8000
```

On startup, the lifespan context manager:
1. Calls `_build_dataset()` which defaults to `LiveHybridSource().load()` (unless `HEMOGRID_USE_LIVE_DATA=false`)
2. Constructs `InMemoryRepository` instances for each canonical type
3. Populates each repo from the loaded dataset
4. Sets `app.state.dataset` (for engine batch calls)
5. Calls `_reset_demo_cache()` to initialise `_DEMO_CACHE`

Startup log (captured from `uvicorn_out.txt`, from `SyntheticSource` path):
```
[SyntheticSource] blood banks: 2817 loaded (6 (Repeated) dropped)
[SyntheticSource] reliability scorer  AUC=0.755  mean(donors)=0.304  mean(non-donors)=0.217
[SyntheticSource] clinics: 9 generated
[SyntheticSource] donors: 900 generated
[SyntheticSource] patients: 200 generated
[SyntheticSource] bonds: 237 donors bonded to patients
[SyntheticSource] inventory: 1295 units across 358 banks
```

To force synthetic data:
```bash
HEMOGRID_USE_LIVE_DATA=false uvicorn hemogrid.api.main:app --reload --port 8000
```

## Running the Frontend

```bash
cd frontend
npm install   # first time only
npm run dev
```

The dev server runs on port 5173 (`http://localhost:5173`). The API base URL is hardcoded in `frontend/src/api.ts` line 1:
```typescript
const API_BASE = 'http://localhost:8000'
```

There is **no Vite proxy configured** in `vite.config.ts`. The frontend makes direct cross-origin requests to `http://localhost:8000`. CORS is configured in the backend:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

## Running Ollama (Optional)

The system works fully without Ollama. All LLM calls catch `LLMUnavailable` and return deterministic fallback text.

To enable live LLM narration:
```bash
# Install Ollama for your OS, then:
ollama serve
ollama pull qwen2.5:7b
```

The backend auto-detects Ollama availability at each `generate()` call. If the call fails or times out (default 20 seconds), it falls back silently to the template strings.

## Chaos Mode (Stage Demo)

The stage-demo chaos intercept can force LLM fallback regardless of Ollama state:
- **Frontend**: `Ctrl+Shift+X` in the browser toggles chaos mode (sets `_chaosActive = true` in `api.ts`). This adds header `X-HemoGrid-Chaos: inject-timeout` to `/api/deserts`, `/api/patients/{id}/activity`, and `/api/patients/{id}/propose` requests.
- **Backend query param**: `?simulate_timeout=true` on `/api/deserts`, `/api/patients/{id}/activity`, `/api/patients/{id}/propose`.
- **Backend header**: `X-HemoGrid-Chaos: inject-timeout` on same endpoints.

When chaos is active, `set_chaos_mode(True)` is called before the endpoint logic and `set_chaos_mode(False)` in the `finally` block. `generate()` checks `_CHAOS_MODE` first and raises `LLMUnavailable("Simulated Stage Chaos Event")`.

## What Works With Ollama OFF vs ON

| Feature | Ollama OFF | Ollama ON |
|---------|-----------|----------|
| Engine (all matching, ranking, desert) | ✓ identical | ✓ identical |
| `GET /api/deserts` structural recommendations | ✓ deterministic template | LLM-generated prose |
| `GET /api/patients/{id}/activity` narration | ✓ deterministic template | LLM-generated prose |
| `POST /api/patients/{id}/propose` narration + donor message | ✓ deterministic template | LLM-generated prose |
| PAT-0001 / PAT-EMERG-99 golden fallback | ✓ pre-intercepted (hardcoded) | Same hardcoded text (pre-intercept fires before LLM for these IDs) |
| Agent inventory selection | ✓ engine fallback | LLM selects from certified set |
