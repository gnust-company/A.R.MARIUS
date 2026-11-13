import { describe, expect, it } from 'vitest'

import { leaderHasSigned, standing } from './signatures'

const sig = (signer_kind: string, result: string, superseded = false) => ({ signer_kind, result, superseded })

describe('leaderHasSigned', () => {
  it('is false until the Leader approves', () => {
    expect(leaderHasSigned([])).toBe(false)
    expect(leaderHasSigned([sig('leader', 'reject')])).toBe(false)
    expect(leaderHasSigned([sig('patron', 'approve')])).toBe(false)
  })

  it('is true once the Leader approves what is in review', () => {
    expect(leaderHasSigned([sig('leader', 'approve')])).toBe(true)
  })

  // The case that locked the patron out: one rejection, then the Leader passes the redone
  // work. Counting rejections to find "the current round" found no signature in it.
  it('still sees the Leader after an earlier rejection sent the work back', () => {
    const history = [
      sig('leader', 'approve', true),
      sig('patron', 'reject', true),
      sig('leader', 'approve'),
    ]
    expect(leaderHasSigned(history)).toBe(true)
  })

  it('does not count a signature given for work that has since gone back', () => {
    expect(leaderHasSigned([sig('leader', 'approve', true), sig('patron', 'reject', true)])).toBe(false)
  })

  // A server from before the field was sent: every signature is standing, as it was then.
  it('treats a missing mark as standing', () => {
    expect(leaderHasSigned([{ signer_kind: 'leader', result: 'approve' }])).toBe(true)
  })
})

describe('standing', () => {
  it('keeps the order and drops only what was retired', () => {
    const history = [sig('leader', 'approve', true), sig('patron', 'reject', true), sig('leader', 'approve')]
    expect(standing(history)).toEqual([sig('leader', 'approve')])
  })
})
