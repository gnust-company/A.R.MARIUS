// The reload onto a new build after a deploy (PR #293 review): it must belong to a screen
// somebody is opening, never to the idle warm-up, and it must not loop.

import { describe, expect, it, vi } from 'vitest'

import { claimReload, screenLoader } from './chunkReload'

function memoryStore() {
  const kept = new Map<string, string>()
  return {
    getItem: (key: string) => kept.get(key) ?? null,
    setItem: (key: string, value: string) => void kept.set(key, value),
  }
}

const brokenStore = {
  getItem: (): string | null => {
    throw new Error('storage is blocked')
  },
  setItem: () => {
    throw new Error('storage is blocked')
  },
}

function surroundings(over: Partial<Parameters<typeof screenLoader>[1] & object> = {}) {
  const store = memoryStore()
  return { store: () => store, now: () => 1_000_000, online: () => true, reload: vi.fn(), ...over }
}

/** Resolves to 'pending' when the promise has not settled by the next macrotask. */
const settled = <T>(promise: Promise<T>) =>
  Promise.race([promise.then(() => 'resolved', () => 'rejected'), new Promise((done) => setTimeout(() => done('pending'), 0))])

describe('claimReload', () => {
  it('allows the first reload and records it', () => {
    const store = memoryStore()
    expect(claimReload(store, 1_000_000)).toBe(true)
    expect(claimReload(store, 1_000_001)).toBe(false)
  })

  it('refuses a second reload inside the same minute and allows one after it', () => {
    const store = memoryStore()
    claimReload(store, 1_000_000)
    expect(claimReload(store, 1_059_999)).toBe(false)
    expect(claimReload(store, 1_060_000)).toBe(true)
  })

  it('refuses when reloads cannot be counted', () => {
    expect(claimReload(brokenStore, 1_000_000)).toBe(false)
  })
})

describe('screenLoader', () => {
  it('passes a loaded screen through untouched', async () => {
    const around = surroundings()
    await expect(screenLoader(() => Promise.resolve('screen'), around)()).resolves.toBe('screen')
    expect(around.reload).not.toHaveBeenCalled()
  })

  it('reloads when the chunk of a screen being opened is gone, and keeps the loading state', async () => {
    const around = surroundings()
    const opening = screenLoader(() => Promise.reject(new Error('chunk is gone')), around)()
    expect(await settled(opening)).toBe('pending')
    expect(around.reload).toHaveBeenCalledTimes(1)
  })

  it('hands the failure to the error boundary instead of reloading twice in a minute', async () => {
    const around = surroundings()
    const load = screenLoader(() => Promise.reject(new Error('chunk is gone')), around)
    void load()
    await expect(load()).rejects.toThrow('chunk is gone')
    expect(around.reload).toHaveBeenCalledTimes(1)
  })

  it('does not reload while offline: the reload would lose the page as well', async () => {
    const around = surroundings({ online: () => false })
    await expect(screenLoader(() => Promise.reject(new Error('offline')), around)()).rejects.toThrow('offline')
    expect(around.reload).not.toHaveBeenCalled()
  })

  it('does not reload when the browser has nowhere to count reloads', async () => {
    const around = surroundings({ store: () => null })
    await expect(screenLoader(() => Promise.reject(new Error('chunk is gone')), around)()).rejects.toThrow('chunk is gone')
    expect(around.reload).not.toHaveBeenCalled()
  })
})
