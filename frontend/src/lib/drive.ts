// Cái đang chờ, nói bằng lời cho người chủ đọc.
//
// Máy chủ giữ **mã**, không giữ câu: cùng một sự thật ấy còn phải đưa cho agent bằng tiếng
// Anh, mà một câu lưu sẵn thì chỉ nói được một thứ tiếng (Hiến pháp — Điều VII). Đây là bảng
// tra phía màn hình, y hệt cách `stall.ts` làm với phán quyết đình trệ.
//
// Chỉ hai cái chờ có nhãn, và cả hai đều là **trạng thái vận hành bình thường**, không phải
// cảnh báo (FR-008b). Cái hỏng đã có ô đình trệ màu đỏ riêng của nó ở trên; thêm màu vào đây
// là dạy người đọc rằng chờ máy rảnh cũng là một thứ phải đi chữa.

import type { TFunction } from 'i18next'

/** Ready to go, and every machine it could run on is busy. Nothing is wrong (FR-008a). */
export const WAITING_FOR_A_MACHINE = 'blocked_on_capacity'
/** Called for, and nobody has picked it up yet (FR-057). */
export const NOBODY_HAS_TAKEN_IT = 'wake_scheduled'

/** One of the two waits, or nothing at all — no label is the common case. */
export type WaitKind = typeof WAITING_FOR_A_MACHINE | typeof NOBODY_HAS_TAKEN_IT

/**
 * Which wait this task is in, if it is in one of the two worth naming.
 *
 * `blocked_by_task` covers two waits that a reader answers differently: behind another task
 * you go and chase that task, behind a busy machine you leave it alone. So the *kind* alone
 * is not enough — the shape decides (FR-008a, FR-008b).
 *
 * A stalled task is not asked about at all: the stall block says the system dropped it, and
 * a second line underneath saying it is calmly waiting would contradict it.
 */
export function waitKind(task: {
  drive?: string
  driveCode?: string
  stalled?: boolean
}): WaitKind | undefined {
  if (task.stalled) return undefined
  if (task.drive === 'blocked_by_task' && task.driveCode === WAITING_FOR_A_MACHINE) {
    return WAITING_FOR_A_MACHINE
  }
  if (task.drive === NOBODY_HAS_TAKEN_IT) return NOBODY_HAS_TAKEN_IT
  return undefined
}

/** The patron's own wording for that wait. */
export function waitText(kind: WaitKind, t: TFunction): string {
  return kind === WAITING_FOR_A_MACHINE
    ? t('board.waitingForMachine')
    : t('board.nobodyHasTakenIt')
}
