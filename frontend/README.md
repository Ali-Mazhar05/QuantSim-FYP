# QuantSim — Interactive POC

A high-fidelity, click-through proof of concept for QuantSim: an AI-assisted
market simulation and portfolio risk analytics platform.

This is a **UI/UX and interaction POC**, not the real implementation. There is
no backend, no database, no message bus, and no real Monte Carlo, ML, TDA or
stress-testing computation — every number comes from a centralized mock data
layer (`src/services/mock`) and a small frontend state machine
(`src/demo/demoState.ts`) that drives the core flow:

```
Market → Simulation → Trading Strategy → Portfolio → Risk Analysis
  (Stress Testing / TDA / ML) → Explainability → Composite Risk → Alert
```

## Running locally

```bash
npm install
npm run dev
```

## Structure

- `src/components` — reusable layout, navigation, chart, table, modal and
  status components.
- `src/pages` — one folder per product area (dashboard, market, simulation,
  trading, risk, tda, ml, explainability, alerts, administration, …).
- `src/demo` — the frontend-only state machine, role/permission model, demo
  orchestration ("Run Full Demo"), and notification store.
- `src/services/mock` — the single source of truth for demo data, plus
  deterministic generators for charts (Monte Carlo paths, correlation
  matrices, persistence diagrams, etc.).

## Demo mode

A **Run Full Demo** control in the top bar walks through the entire flow
end-to-end; **Reset Demo** returns to the initial dashboard state. The
presenter can also jump to any stage directly via the sidebar or the demo
progress indicator.
