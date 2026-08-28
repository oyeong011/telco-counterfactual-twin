# Frontend Source Boundary

## Status

The production entry renders the TanStack Router operations console. The console keeps the demo token in memory, stores only session-scoped run IDs plus the exact submitted patch in `sessionStorage`, and presents the backend lifecycle as evidence-only review rather than network execution.

The primitive showcase remains available only from the development-only `/__showcase` entry gate.
