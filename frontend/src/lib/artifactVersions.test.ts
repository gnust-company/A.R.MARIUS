import { describe, expect, it } from 'vitest'

import { currentOnly, withVersions } from './artifactVersions'

// The real list from the calculator project of 2026-11-12, in the order the server gave it.
const published = ['index.html', 'style.css', 'script.js', 'report.md', 'style.css', 'script.js', 'report-v2.md'].map(
  (name, i) => ({ id: `a${i}`, name }),
)

describe('withVersions', () => {
  it('numbers each publish of a name and marks the newest', () => {
    const rows = withVersions(published)
    expect(rows.map((r) => `${r.artifact.name} ${r.version}/${r.of}${r.current ? ' current' : ''}`)).toEqual([
      'index.html 1/1 current',
      'style.css 1/2',
      'script.js 1/2',
      'report.md 1/1 current',
      'style.css 2/2 current',
      'script.js 2/2 current',
      'report-v2.md 1/1 current',
    ])
  })

  it('keeps every row: an older version is still there to be opened', () => {
    expect(withVersions(published)).toHaveLength(published.length)
  })
})

describe('currentOnly', () => {
  it('keeps the newest of each name, in the order the names first appeared', () => {
    expect(currentOnly(published).map((r) => `${r.artifact.name}:${r.artifact.id}`)).toEqual([
      'index.html:a0',
      'style.css:a4',
      'script.js:a5',
      'report.md:a3',
      'report-v2.md:a6',
    ])
  })

  it('has nothing to say about an empty list', () => {
    expect(currentOnly([])).toEqual([])
  })
})
