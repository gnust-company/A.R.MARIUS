// Agent của workspace nào thì chỉ hiện ở workspace ấy (FR-007q, issue #284).
//
// Store giữ agent của **mọi** workspace trong một danh sách, để màn chọn workspace đếm được số agent
// của từng cái. Mỗi trang đọc danh sách ấy cho **một** workspace phải tự lọc — và ba trang đã quên:
// trang Agents, tạo dự án, mời agent vào dự án. Lỗi lộ ra ngày 2026-10-12, khi workspace nào cũng tự có
// một agent mặc định tên Livia: workspace thứ hai hiện hai Livia.

import { describe, expect, it } from 'vitest'

import { agentsOf } from './workspaceScope'

const livia = (id: string, workspaceId: string) => ({ id, name: 'Livia', workspaceId })

describe('agentsOf', () => {
  const everyone = [livia('a1', 'personal'), livia('b1', 'ai-team'), livia('a2', 'personal')]

  it('keeps only the agents of the workspace asked about', () => {
    expect(agentsOf(everyone, 'ai-team').map((a) => a.id)).toEqual(['b1'])
    expect(agentsOf(everyone, 'personal').map((a) => a.id)).toEqual(['a1', 'a2'])
  })

  it('gives nobody when no workspace is known yet, rather than everybody', () => {
    // Trả về tất cả thì đúng lỗi cũ quay lại, chỉ ở một lúc khó thấy hơn: lúc app vừa mở.
    expect(agentsOf(everyone, null)).toEqual([])
    expect(agentsOf(everyone, undefined)).toEqual([])
    expect(agentsOf(everyone, '')).toEqual([])
  })

  it('gives nobody for a workspace that has no agents', () => {
    expect(agentsOf(everyone, 'home')).toEqual([])
  })
})
