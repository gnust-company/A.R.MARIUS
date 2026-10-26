// Mức suy nghĩ đi theo model đang chọn (FR-007k của đặc tả 002, sửa 2026-10-26).
//
// Hỏi thẳng Claude Code thì mỗi model nói nó nhận những mức nào: Opus 4.6 không có `xhigh`, Haiku
// 4.5 không nhận mức nào. Luật đến dưới dạng dữ liệu, viết bằng khoá của lựa chọn.

import { describe, expect, it } from 'vitest'

import type { PlacementOption } from '@/store/appStore'

import { choose, isClosed, labelOf, narrowedTo, offeredValues } from './runtimeOptions'

const level: PlacementOption = {
  key: 'thinking_level',
  values: ['low', 'medium', 'high', 'xhigh', 'max'],
  source: 'tool_declared',
}
const model: PlacementOption = {
  key: 'model',
  values: ['claude-opus-5-5', 'claude-opus-4-6', 'claude-haiku-4-5'],
  source: 'tool_listed',
  labels: { 'claude-opus-5-5': 'Opus 5.5', 'claude-opus-4-6': 'Opus 4.6' },
  narrows: {
    'claude-opus-4-6': { thinking_level: ['low', 'medium', 'high', 'max'] },
    'claude-haiku-4-5': { thinking_level: [] },
  },
}
const both = [level, model]

describe('offeredValues', () => {
  it('offers every level while no model is picked', () => {
    expect(offeredValues(both, {}, level)).toEqual(level.values)
  })

  it('offers only the levels the picked model takes', () => {
    expect(offeredValues(both, { model: 'claude-opus-4-6' }, level)).toEqual([
      'low',
      'medium',
      'high',
      'max',
    ])
  })

  it('offers no level for a model that takes none', () => {
    expect(offeredValues(both, { model: 'claude-haiku-4-5' }, level)).toEqual([])
  })

  it('narrows nothing for a model the list says nothing about, such as one typed by hand', () => {
    expect(narrowedTo(both, { model: 'claude-opus-4-1' }, 'thinking_level')).toBeNull()
  })
})

describe('choose', () => {
  it('puts a level the new model does not take back to blank', () => {
    expect(choose(both, { thinking_level: 'xhigh' }, 'model', 'claude-opus-4-6')).toEqual({
      model: 'claude-opus-4-6',
      thinking_level: '',
    })
  })

  it('leaves a level the new model takes alone', () => {
    expect(choose(both, { thinking_level: 'high' }, 'model', 'claude-opus-4-6')).toEqual({
      model: 'claude-opus-4-6',
    })
  })

  it('leaves a blank level blank rather than reporting it as a change', () => {
    expect(choose(both, { thinking_level: '' }, 'model', 'claude-haiku-4-5')).toEqual({
      model: 'claude-haiku-4-5',
    })
  })

  it('clears any level when the model takes none', () => {
    expect(choose(both, { thinking_level: 'low' }, 'model', 'claude-haiku-4-5')).toEqual({
      model: 'claude-haiku-4-5',
      thinking_level: '',
    })
  })
})

describe('labels and closed lists', () => {
  it('shows the name the tool gave, and the value when it gave none', () => {
    expect(labelOf(model, 'claude-opus-5-5')).toBe('Opus 5.5')
    expect(labelOf(model, 'claude-haiku-4-5')).toBe('claude-haiku-4-5')
  })

  it('lets a person type past a listed set but not past a declared one', () => {
    expect(isClosed(level)).toBe(true)
    expect(isClosed(model)).toBe(false)
    expect(isClosed({ key: 'model', values: ['opus'], source: 'tool_examples' })).toBe(false)
  })
})
