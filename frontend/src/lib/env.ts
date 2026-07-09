// Runtime config for the API seam.
//
// The app talks to the real backend same-origin: nginx proxies /auth, /v1, /agent to it,
// so API_BASE stays relative. Override the origin only for split-origin dev (e.g. Vite on
// :3000 hitting the API on :8080) with `VITE_API_BASE=http://localhost:8080`.

export const API_BASE: string = String(import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')
