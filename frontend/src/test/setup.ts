// The one thing a browser has that Node does not, and that this code reaches for.
//
// `getToken()` reads the access token out of `localStorage` on every connect. Stubbed rather
// than mocked away: the reader should go through its real path to the token, so that a change
// making it read from somewhere else is a change these tests see.
const kept = new Map<string, string>()

Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    getItem: (key: string) => kept.get(key) ?? null,
    setItem: (key: string, value: string) => void kept.set(key, String(value)),
    removeItem: (key: string) => void kept.delete(key),
    clear: () => kept.clear(),
    key: (i: number) => [...kept.keys()][i] ?? null,
    get length() {
      return kept.size
    },
  },
})
