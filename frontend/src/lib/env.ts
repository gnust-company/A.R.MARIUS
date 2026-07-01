// Runtime flags for the data seam (Sprint 6 — FE mock → real API).
//
// MOCK on  → the frozen in-memory demo (zero backend). Opt in with `.env.local`:
//              VITE_MOCK=true
// MOCK off → the real API (the Sprint-6 default). Same-origin: nginx proxies
//            /auth, /v1, /agent to the backend, so API_BASE stays relative.
//
// Override the origin only for split-origin dev (e.g. Vite on :3000 hitting the API
// on :8080) with `VITE_API_BASE=http://localhost:8080`.

export const MOCK: boolean = import.meta.env.VITE_MOCK === 'true'

export const API_BASE: string = String(import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')
