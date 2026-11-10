import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { inspectAttr } from 'plugin-inspect-react-code'

// https://vite.dev/config/
export default defineConfig({
  // Absolute base so BrowserRouter deep links (/projects/:id) resolve hashed
  // assets correctly behind the nginx SPA fallback.
  base: '/',
  // The React Compiler memoizes components and hooks at build time, which is why the
  // codebase carries almost no hand-written `useMemo`/`useCallback`. The lint rules that
  // guard it (`react-hooks/*`) were already on; without the Babel plugin here they were
  // reporting on a transform that never ran, so a rule violation cost a red line and
  // changed nothing about the bundle.
  plugins: [
    inspectAttr(),
    react({ babel: { plugins: [['babel-plugin-react-compiler', {}]] } }),
  ],
  build: {
    rollupOptions: {
      output: {
        // Every screen is its own chunk (see App.tsx). Left alone, Rollup also gives each
        // icon a file of its own as soon as two screens use it: some thirty requests of a
        // few hundred bytes. The icons the app uses travel together instead.
        manualChunks(id) {
          if (id.includes('node_modules/lucide-react/')) return 'icons'
        },
        // Shared helpers of a few hundred bytes (a title, a chip, a formatter) are folded into
        // a neighbour instead of costing a request each. Kept low on purpose: a higher floor
        // starts folding whole screens into the chunks other screens depend on.
        experimentalMinChunkSize: 5_000,
      },
    },
  },
  server: {
    port: 3000,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
