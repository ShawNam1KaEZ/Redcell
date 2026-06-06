# HemoGrid Documentation

Generated: 2026-06-06 | Branch: main | Commit: 4e34dba (phase 2)

## Reading Order

Start with **SUMMARY.md** for a 5-minute overview of the entire project. Then drill into numbered docs as needed.

| File | Description |
|------|-------------|
| [SUMMARY.md](SUMMARY.md) | Single-page condensed digest — start here |
| [00-file-index.md](00-file-index.md) | Complete file tree with line counts and one-line descriptions |
| [01-overview.md](01-overview.md) | What the project is, the domain, the thesis, the users |
| [02-architecture.md](02-architecture.md) | Layered architecture, design principles, hybrid agency model, two-lock safety |
| [03-tech-stack-and-run.md](03-tech-stack-and-run.md) | All dependencies, env vars, run commands, what works with/without Ollama |
| [04-data.md](04-data.md) | All datasets, canonical models field-by-field, synthetic generation with seed order |
| [05-engine.md](05-engine.md) | Every engine function: signature, math, constants, desert model, candidate denominations |
| [06-agents-and-llm.md](06-agents-and-llm.md) | LangGraph topology, HITL mechanics, _agent_select loop, all LLM functions and fallbacks |
| [07-api.md](07-api.md) | Every endpoint with request/response JSON, decision logic audit |
| [08-frontend.md](08-frontend.md) | Every component, all React state, API client, hardcoded values flagged |
| [09-end-to-end.md](09-end-to-end.md) | Golden demo scenario step-by-step, generic walkthrough, sequence diagram, state machine |
| [10-data-flow-and-known-issues.md](10-data-flow-and-known-issues.md) | **HIGH PRIORITY** — full data path hop-by-hop, new-data root cause analysis, discrepancies, fragilities |
| [11-glossary.md](11-glossary.md) | Every ID, term, enum value, constant, acronym |

## Quick Navigation

**"Why doesn't new data appear in the UI?"** → [10-data-flow-and-known-issues.md §Candidate 1 and §Candidate 2](10-data-flow-and-known-issues.md)

**"How does the engine pick the lever?"** → [05-engine.md §choose_lever](05-engine.md#10-choose_lever)

**"How does the HITL gate work?"** → [06-agents-and-llm.md §HITL Mechanics](06-agents-and-llm.md#hitl-mechanics)

**"What are the exact endpoint request/response shapes?"** → [07-api.md](07-api.md)

**"What are the discrepancies between the code and CLAUDE.md?"** → [10-data-flow-and-known-issues.md §Discrepancies](10-data-flow-and-known-issues.md#discrepancies-between-code-and-claudemd)

**"What does BB-0036 mean and where is it defined?"** → [11-glossary.md §Bank IDs](11-glossary.md#canonical-entity-ids)
