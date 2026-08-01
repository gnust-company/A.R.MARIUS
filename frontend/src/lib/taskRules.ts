/**
 * Đầu việc — bảng chuyển trạng thái và năm cổng chặn, bản dành cho giao diện (spec 001 §E).
 *
 * Máy chủ mới là nơi cưỡng chế; chỗ này chỉ để **không mời người dùng bấm một nút chắc chắn
 * bị từ chối**. Giữ đúng một bản sao ở đây, khớp từng dòng với
 * `backend/armarius/domain/entities/task.py`. Nếu hai bên lệch nhau thì máy chủ đúng: nó vẫn
 * chặn, chỉ là người dùng phải nhận một thông báo lỗi thay vì thấy nút đã mờ sẵn.
 */

export type TaskPhase =
  | 'draft'
  | 'backlog'
  | 'todo'
  | 'in_progress'
  | 'in_review'
  | 'blocked'
  | 'done'
  | 'cancelled'

/** Đường đi thường ngày. *Xong* và *huỷ* là trạng thái đóng — ra bằng thao tác mở lại. */
export const ALLOWED_MOVES: Record<TaskPhase, TaskPhase[]> = {
  draft: ['todo', 'backlog', 'cancelled'],
  backlog: ['todo', 'cancelled'],
  todo: ['in_progress', 'blocked', 'backlog', 'cancelled'],
  in_progress: ['in_review', 'blocked', 'todo', 'cancelled'],
  in_review: ['done', 'in_progress', 'blocked', 'cancelled'],
  blocked: ['in_progress', 'todo', 'backlog', 'cancelled'],
  done: [],
  cancelled: [],
}

/** Vào đây phải nêu lý do (FR-030). */
export const REASON_REQUIRED: TaskPhase[] = ['blocked', 'cancelled']

/** Trả lại sửa cũng phải nêu lý do — thợ cần biết sửa cái gì. */
const REASON_REQUIRED_MOVES: [TaskPhase, TaskPhase][] = [['in_review', 'in_progress']]

/** Chỉ hai trạng thái này nhận đầu việc mới; tạo thẳng vào *xong* là một lối tắt. */
export const CREATABLE_PHASES: TaskPhase[] = ['backlog', 'todo']

export const CLOSED_PHASES: TaskPhase[] = ['done', 'cancelled']

export function canMove(from: TaskPhase, to: TaskPhase): boolean {
  return (ALLOWED_MOVES[from] ?? []).includes(to)
}

export function isClosed(phase: TaskPhase): boolean {
  return CLOSED_PHASES.includes(phase)
}

export function needsReason(from: TaskPhase, to: TaskPhase): boolean {
  if (REASON_REQUIRED.includes(to)) return true
  return REASON_REQUIRED_MOVES.some(([a, b]) => a === from && b === to)
}

/** Khoá i18n giải thích vì sao một đường bị chặn — hoặc null nếu đường đó đi được. */
export function blockedReasonKey(
  from: TaskPhase,
  to: TaskPhase,
  opts: { hasArtifact: boolean; stalled: boolean; depsSatisfied: boolean },
): string | null {
  if (isClosed(from)) return 'taskRules.blocked.closed'
  if (to === 'done' && opts.stalled) return 'taskRules.blocked.stalled'
  if (from === 'in_progress' && to === 'done') return 'taskRules.blocked.reviewFirst'
  if (!canMove(from, to)) return 'taskRules.blocked.illegal'
  if ((to === 'in_review' || to === 'done') && !opts.hasArtifact) {
    return 'taskRules.blocked.needsArtifact'
  }
  if ((to === 'todo' || to === 'in_progress') && !opts.depsSatisfied) {
    return 'taskRules.blocked.needsDependencies'
  }
  return null
}
