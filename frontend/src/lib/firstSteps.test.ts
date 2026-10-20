// Bước *nối máy* biết mình đang ở phần nào (spec 003 FR-120, research R5).

import { describe, expect, it } from 'vitest'

import { connectProgress } from './firstSteps'

const withRuntimes = (count: number) => ({
  workplaces: Array.from({ length: count }, (_, i) => ({
    id: `w${i}`,
    cli_kind: 'claude_code',
    cli_version: '2',
    ready: false,
    not_ready_reason: 'daemon_stopped',
    agents: [],
  })),
})

describe('connectProgress', () => {
  it('has nothing done before any machine is approved', () => {
    expect(connectProgress([], false)).toEqual({ linked: false, running: false })
  })

  it('counts an approval heard on the channel before the machine row exists', () => {
    // Từ lúc duyệt tới lúc daemon nhận giấy tờ có vài giây chưa có dòng máy nào.
    expect(connectProgress([], true)).toEqual({ linked: true, running: false })
  })

  it('counts a linked machine whose daemon has not started as linked, not running', () => {
    expect(connectProgress([withRuntimes(0)], false)).toEqual({ linked: true, running: false })
  })

  it('counts a machine that reported runtimes as running, ready or not', () => {
    expect(connectProgress([withRuntimes(1)], false)).toEqual({ linked: true, running: true })
  })
})
