"""Câu tuyên đình trệ là **mã**, không phải câu tiếng Việt lưu trong sổ (T200, Hiến pháp VII).

Cờ đình trệ nói *vì sao* một đầu việc bị bỏ rơi. Câu ấy đi ba đường cùng lúc: hiện trên thẻ
việc cho người chủ, nằm trong hồ sơ leo thang đưa cho Trưởng dự án, và theo phản hồi ra tới
agent. Ba người đọc, hai thứ tiếng — nên nó không được là một câu dựng sẵn ở máy chủ, đúng
cùng lý do lời từ chối không được (T184).

Nặng hơn T193/T194 ở một điểm: nó là **cột dữ liệu**, không phải chuỗi dựng lúc phát. Câu
tiếng Việt đã nằm sẵn trong cơ sở dữ liệu, nên đổi cách viết thôi chưa đủ — phải có bản di
trú, và bảng mã phải phủ **mọi** loại động cơ đẩy chứ không phải bốn loại rồi rơi vào một
chuỗi f-string.
"""

from __future__ import annotations

import pathlib
import re
from datetime import datetime, timedelta
from uuid import UUID

from armarius.domain.entities.task import TaskDrive
from armarius.domain.services.push_reason_rules import (
    STALL_ENGLISH,
    STALL_ORPHANED,
    STALL_UNKNOWN,
    PushReason,
    stall_reason,
    stall_text_en,
)
from armarius.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from armarius.presentation.schemas import TaskOut
from tests.support.planning import client, operating_project

VIETNAMESE = "ăâđêôơưàáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ"
_I18N = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"

_T0 = datetime(2026, 8, 18, 9, 0)


def _screen_codes(language: str) -> set[str]:
    source = (_I18N / f"{language}.ts").read_text(encoding="utf-8")
    block = re.search(r"\n  stall: \{\n(.*?)\n  \},\n", source, re.S)
    assert block, f"{language}.ts không có khối stall"
    return set(re.findall(r"^    ([a-z0-9_]+):", block.group(1), re.M))


# ── the verdict itself ────────────────────────────────────────────────────────


def test_the_verdict_is_a_code_the_table_knows() -> None:
    """Mỗi lối ra của phép tuyên đều là một mã có câu, kể cả lối không có động cơ đẩy nào."""
    assert stall_reason(None, now=_T0) == STALL_ORPHANED
    for kind in TaskDrive:
        expired = PushReason(kind=kind, expires_at=_T0 - timedelta(minutes=1))
        verdict = stall_reason(expired, now=_T0)
        assert verdict in STALL_ENGLISH, f"{kind} tuyên ra mã lạ: {verdict!r}"


def test_a_live_drive_is_not_a_verdict_at_all() -> None:
    alive = PushReason(kind=TaskDrive.RUN_ACTIVE, expires_at=_T0 + timedelta(minutes=5))
    assert stall_reason(alive, now=_T0) is None


def test_the_two_clockless_drives_still_have_words_when_they_expire() -> None:
    """`provisional_drive` gắn đồng hồ cho cả hai loại vốn không có, nên chúng *tới được*
    bảng này. Trước T200 chúng rơi vào một chuỗi f-string ghép tên động cơ đẩy vào câu."""
    for status_drive in (TaskDrive.WAITING_PATRON, TaskDrive.BLOCKED_BY_TASK):
        expired = PushReason(kind=status_drive, expires_at=_T0 - timedelta(minutes=1))
        assert stall_reason(expired, now=_T0) != STALL_UNKNOWN


def test_the_agents_copy_of_the_verdict_has_no_vietnamese_in_it() -> None:
    for code, sentence in STALL_ENGLISH.items():
        lowered = sentence.lower()
        assert not any(ch in lowered for ch in VIETNAMESE), code


def test_an_unknown_verdict_still_reads_as_words() -> None:
    """Một mã do bản cũ ghi lại vẫn phải ra chữ: mất chi tiết còn hơn mất cả lời cảnh báo."""
    assert stall_text_en("stall_from_an_older_build") == STALL_ENGLISH[STALL_UNKNOWN]
    assert stall_text_en(None) == STALL_ENGLISH[STALL_UNKNOWN]


# ── the two readers ───────────────────────────────────────────────────────────


def test_the_wire_carries_both_readings_of_one_stored_code() -> None:
    """Đúng hình dạng của một lời từ chối: `detail` là bản tiếng Anh máy chủ dựng, `code` là
    thứ màn hình dựng câu của người chủ từ đó."""
    dto = TaskOut.model_validate(
        {"id": "0" * 8 + "-0000-0000-0000-" + "0" * 12, "title": "X", "status": "todo",
         "stalled": True, "stalled_reason": STALL_ORPHANED}
    )
    assert dto.stalled_reason_code == STALL_ORPHANED
    assert dto.stalled_reason == STALL_ENGLISH[STALL_ORPHANED]


def test_a_task_nobody_dropped_carries_neither() -> None:
    dto = TaskOut.model_validate(
        {"id": "0" * 8 + "-0000-0000-0000-" + "0" * 12, "title": "X", "status": "todo"}
    )
    assert dto.stalled_reason is None and dto.stalled_reason_code is None


def test_every_verdict_the_server_can_store_has_a_phrase_on_screen() -> None:
    for language in ("en", "vi"):
        missing = sorted(set(STALL_ENGLISH) - _screen_codes(language))
        assert not missing, f"{language}.ts thiếu câu cho: {missing}"


def test_the_screen_has_no_phrase_for_a_verdict_the_server_never_stores() -> None:
    for language in ("en", "vi"):
        orphans = sorted(_screen_codes(language) - set(STALL_ENGLISH))
        assert not orphans, f"{language}.ts còn câu thừa cho: {orphans}"


# ── through the running server ────────────────────────────────────────────────


async def test_a_stalled_task_answers_with_the_code_and_an_english_reading() -> None:
    async with client() as c:
        p = await operating_project(c, "stall-verdict@example.com")
        made = await c.post(
            f"/agent/projects/{p.project_id}/tasks",
            headers=p.leader_headers,
            json={
                "title": "Kết xuất báo cáo tháng",
                "description": "Gom số liệu rồi kết xuất ra tệp bảng tính.",
                "assignee_marius_id": p.worker_id,
                "plan_item_id": p.item_id(),
            },
        )
        assert made.status_code == 201, made.text
        task_id = made.json()["id"]

        async with SqlAlchemyUnitOfWork() as uow:
            task = await uow.tasks.get(UUID(task_id))
            assert task is not None
            task.stalled = True
            task.stalled_reason = STALL_ORPHANED
            await uow.tasks.update(task)
            await uow.commit()

        got = await c.get(f"/v1/tasks/{task_id}", headers=p.headers)
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["stalled_reason_code"] == STALL_ORPHANED
        assert body["stalled_reason"] == STALL_ENGLISH[STALL_ORPHANED]
        lowered = body["stalled_reason"].lower()
        assert not any(ch in lowered for ch in VIETNAMESE)
