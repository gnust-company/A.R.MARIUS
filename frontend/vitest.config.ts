// Where the frontend's tests run (T142).
//
// Separate from `vite.config.ts` rather than a `test` key inside it, because the two want
// different things. The app build runs the React Compiler through Babel on every file; a
// test of a parser does not need it, and paying for it on every run is how a test suite
// stops being run.
//
// `environment: 'node'` for the same reason: what is under test here is a reader over a
// `ReadableStream`, and Node has had `fetch`, streams and `TextDecoder` as globals for
// several majors. A DOM would be a second dependency bought for nothing. The day a
// component test lands, that test brings its own environment.
import path from 'path'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    setupFiles: ['./src/test/setup.ts'],
  },
})
