// The shared geometry and material caches are counted per scene (PR #293 review): the first
// scene to leave must not empty what another is still drawing with.

import { describe, expect, it } from 'vitest'

import { material, releaseCaches, retainCaches } from './primitives'

describe('shared scene caches', () => {
  it('keeps the caches while a scene still holds them, and empties them with the last', () => {
    retainCaches()
    retainCaches()
    const first = material('#aabbcc')
    expect(material('#aabbcc')).toBe(first)

    releaseCaches()
    expect(material('#aabbcc')).toBe(first)

    releaseCaches()
    expect(material('#aabbcc')).not.toBe(first)
  })

  it('ignores a release nobody took a hold for', () => {
    releaseCaches()
    retainCaches()
    const kept = material('#112233')
    expect(material('#112233')).toBe(kept)
    releaseCaches()
  })
})
