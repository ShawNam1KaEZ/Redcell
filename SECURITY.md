# Security Policy

## Scope

This policy applies to the HemoGrid source code in this repository. It does not cover data security in any deployed instance — operators are responsible for securing their own deployments.

## Known limitations (by design)

The following are intentional constraints of the current hackathon prototype, not security vulnerabilities:

- **No authentication or authorisation.** CORS is set to `allow_origins=["*"]`. All endpoints are publicly accessible. This must be addressed before any production deployment.
- **SQLite simulation database.** `data/working_sim.db` is a local flat file with no access controls. For a real clinical deployment, replace with a properly secured database.
- **Synthetic patient data.** The `data/build/` CSVs contain entirely synthetic or anonymised records. No real patient data is included in this repository.
- **Ollama runs locally.** The AI explanation endpoint calls a locally-hosted model. No patient data is sent to any external service by default.

## Reporting a vulnerability

If you discover a security vulnerability in the source code (e.g. a code-injection path, a way to corrupt simulation state without proper authentication, or a dependency with a known CVE that affects this project), please **do not open a public GitHub Issue**.

Instead, report it privately:

<!-- TODO: Replace with your preferred contact method for security reports -->
**Email:** <!-- TODO: your-security-email@example.com -->

Please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce
- Any suggested mitigations, if you have them

You will receive an acknowledgement within 72 hours. We aim to resolve confirmed vulnerabilities within 14 days and will credit reporters in the fix commit unless you prefer to remain anonymous.

## Dependency security

Backend dependencies are listed in `requirements.txt`. Frontend dependencies are in `frontend/package.json` / `frontend/package-lock.json`. We recommend running `pip audit` and `npm audit` periodically to check for known vulnerabilities.

```bash
# Check backend dependencies
pip install pip-audit && pip-audit

# Check frontend dependencies
cd frontend && npm audit
```
