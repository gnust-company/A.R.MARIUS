// Luật chọn sẵn runtime cho người chủ nhà (spec 003 FR-125).
//
// Đúng một runtime sẵn sàng thì không phải một lựa chọn, nên được chọn sẵn. Từ hai trở lên thì người
// dùng chọn, hệ thống không chọn hộ: chọn cái đầu tiên chính là luật FR-112 vừa bỏ.

import { describe, expect, it } from 'vitest'

import type { MachineDTO } from './api'
import { currentRuntimeChoice, initialRuntimeChoice, unavailableRuntimes } from './runtimeChoice'

const place = (id: string) => ({ id })

describe('initialRuntimeChoice', () => {
  it('picks nothing when no runtime is ready', () => {
    expect(initialRuntimeChoice([])).toBeNull()
  })

  it('picks the only ready runtime', () => {
    expect(initialRuntimeChoice([place('claude')])).toBe('claude')
  })

  it('picks nothing when two are ready, so the person has to', () => {
    expect(initialRuntimeChoice([place('claude'), place('gemini')])).toBeNull()
  })
})

describe('currentRuntimeChoice', () => {
  it('keeps what the person picked while it is still on offer', () => {
    expect(currentRuntimeChoice([place('claude'), place('gemini')], 'gemini')).toBe('gemini')
  })

  it('lets go of a pick whose runtime has gone away', () => {
    // Daemon dừng thì runtime biến khỏi danh sách; giữ lựa chọn cũ là gửi lên một chỗ không còn.
    expect(currentRuntimeChoice([place('claude'), place('codex')], 'gemini')).toBeNull()
  })

  it('falls back to the only runtime left once the picked one has gone', () => {
    expect(currentRuntimeChoice([place('claude')], 'gemini')).toBe('claude')
  })

  it('has nothing picked when nothing is ready, whatever was picked before', () => {
    expect(currentRuntimeChoice([], 'claude')).toBeNull()
  })
})

describe('unavailableRuntimes', () => {
  const machine = (over: Partial<MachineDTO>): MachineDTO => ({
    id: 'm1',
    display_name: 'laptop',
    platform: 'linux',
    daemon_version: '0.2.0',
    last_heartbeat_at: null,
    reachable: true,
    max_concurrent: 2,
    workplaces: [],
    ...over,
  })
  const workplace = (id: string, ready: boolean, reason: string | null = null) => ({
    id,
    cli_kind: id,
    cli_version: '1',
    ready,
    not_ready_reason: reason,
    agents: [],
  })

  it('lists only what is not on offer, with the reason the machine gave', () => {
    const machines = [
      machine({
        workplaces: [workplace('claude', true), workplace('gemini', false, 'cli_removed')],
      }),
    ]
    expect(unavailableRuntimes(machines, [place('claude')])).toEqual([
      { id: 'gemini', cliKind: 'gemini', machineName: 'laptop', reason: 'cli_removed' },
    ])
  })

  it('says the machine is unreachable when it went quiet without a reason', () => {
    const machines = [machine({ reachable: false, workplaces: [workplace('claude', false)] })]
    expect(unavailableRuntimes(machines, [])[0].reason).toBe('machine_unreachable')
  })

  it('never shows a runtime twice, ready and not ready', () => {
    // Hai lần đọc chạy song song có thể lệch nhau một nhịp; danh sách sẵn sàng thắng.
    const machines = [machine({ workplaces: [workplace('claude', false, 'daemon_stopped')] })]
    expect(unavailableRuntimes(machines, [place('claude')])).toEqual([])
  })
})
