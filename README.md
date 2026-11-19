# QuantSim

AI-assisted market simulation and portfolio risk analytics.

| Folder | Contents |
|---|---|
| `frontend/` | React + TypeScript web app (imported from the `develop-poc` proof of concept) |
| `services/` | Backend services, one folder each (added as the core modules are built) |
| `ci/` | CI/CD: Jenkins setup, pipeline scripts, the component list |
| `deploy/` | Compose stack, per-environment settings, encrypted secrets |
| `docs/` | Proposal documents, tech stack and implementation guide, CI/CD guide, presentation material |

## Run the frontend locally

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173
npm test           # unit tests
```

## How changes are shipped

`feature/*` → `develop` (DEV) → `test` (TEST) → `acceptance` (ACC) → `main` (PROD), through
a Jenkins pipeline. Start with [CONTRIBUTING.md](CONTRIBUTING.md) (daily routine and how to
ship), then the [CI/CD team guide](docs/ci-cd-team-guide.md).

## Documentation

- [Tech stack and implementation guide](docs/QuantSim_Tech_Stack_and_Implementation.md)
- [Contributing: staying up to date and shipping a change](CONTRIBUTING.md)
- [CI/CD team guide](docs/ci-cd-team-guide.md)
- [CI/CD technical reference](docs/ci-cd.md)
- [Jenkins setup](ci/jenkins/README.md)
- [Proposal documents](docs/proposal/)
