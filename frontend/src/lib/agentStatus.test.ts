import { describe, expect, it } from 'vitest'

import { agentStatusOf } from './mappers'

describe('agentStatusOf', () => {
  it('shows an agent carrying out a run as working', () => {
    expect(agentStatusOf({ liveness: 'online', running: true })).toBe('working')
  })

  it('leaves a reachable agent with no run in hand as it was', () => {
    expect(agentStatusOf({ liveness: 'online', running: false })).toBe('online')
    expect(agentStatusOf({ liveness: 'checking', running: false })).toBe('idle')
  })

  it('reads an older server, which says nothing about runs, as not working', () => {
    expect(agentStatusOf({ liveness: 'online' })).toBe('online')
  })

  it('never shows an unreachable agent as working, whatever its last run says', () => {
    expect(agentStatusOf({ liveness: 'offline', running: true })).toBe('offline')
    expect(agentStatusOf({ liveness: 'hung', running: true })).toBe('offline')
  })
})
