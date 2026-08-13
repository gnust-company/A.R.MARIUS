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
  server: {
    port: 3000,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
