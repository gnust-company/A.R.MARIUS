"""Cùng một đầu việc, hai họ giao thức, một đường mã (T121, FR-035, FR-037, SC-008).

Đã có hai chốt tĩnh canh chuyện này ở `test_constitution_guards.py`: tầng nghiệp vụ không
được rẽ nhánh theo loại runtime, và không được biết việc chạy ở đâu. Cả hai đọc **mã nguồn**
— không có chữ `if` nào nhắc tới daemon, tới máy, tới loại CLI.

Chốt tĩnh với không tới đúng một chỗ, và đó là chỗ tệp này đứng: **mã không có một chữ `if`
nào vẫn có thể có hai con đường.** Hai lối hạ tầng khác nhau dựng ra hai gói việc khác nhau,
hai bảng tra khác nhau, hai lối đăng ký adapter khác nhau — không dòng nào phạm luật đặt tên,
mà agent ở hai loại CLI vẫn nhận hai thứ khác nhau. Cách duy nhất bắt được là **chạy cùng một
đầu việc hai lần và so kết quả**.

Vì sao là hai *họ giao thức* chứ không phải hai *loại CLI*: FR-039 cam kết hỗ trợ cả hai họ,
và ranh giới dễ vỡ nằm đúng giữa chúng. Hai CLI cùng họ đi qua cùng một bộ đọc, nên chúng
giống nhau vì lý do ít đáng tin hơn nhiều.

Mọi thứ khác được giữ **giống hệt** giữa hai lượt — tên agent, chỉ dẫn, kỹ năng, tên dự án,
tiêu đề đầu việc — để một khác biệt trong gói việc không thể đổ cho thứ gì ngoài loại CLI.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunEventModel, RunModel, TaskModel
from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


COOKBOOK = {
    "SKILL.md": "---\nname: cookbook\ndescription: How we cook\n---\n\n# Cookbook\n",
    "ref/stock.md": "Simmer for six hours.\n",
}

# Everything that is allowed to differ between the two runs, and nothing else. Each one is an
# identifier minted per run, per machine or per workspace — a difference that says *these are
# two runs*, never *these are two kinds of run*.
#
# `claim_expires_at` is here for a different reason and does not get off as lightly: it is a
# moment, so two runs a second apart can never carry the same one. What must not differ is the
# **length** of the hold, and that is checked on its own below rather than waved through.
MAY_DIFFER = frozenset(
    {"run_id", "task_id", "project_id", "workplace_id", "run_token", "claim_expires_at"}
)


async def _one_task_start_to_finish(
    c: AsyncClient, *, cli_kind: str, family: str, email: str
) -> dict[str, Any]:
    """Take one task all the way through, on a machine offering exactly one CLI.

    Every step goes through the real routes, in the real order a machine takes them: link,
    report the workplace, put an agent on it, shelve a run, ask for work, say the agent
    started, send what it did, say how it ended.
    """
    box = await link_machine(c, email, cli_kind=cli_kind, protocol_family=family)

    made = await c.post(
        f"/v1/workspaces/{box.workspace_id}/skills/manual",
        json={"name": "Cookbook", "description": ""},
        headers=box.headers,
    )
    assert made.status_code == 201, made.text
    skill = made.json()
    saved = await c.put(
        f"/v1/workspaces/{box.workspace_id}/skills/{skill['id']}",
        json={"files": COOKBOOK},
        headers=box.headers,
    )
    assert saved.status_code == 200, saved.text

    agent = await invite_agent(
        c,
        box.workspace_id,
        box.headers,
        name="Marin",
        workplace_id=box.workplace_id,
        instructions="Do the job.",
        skill_ids=[skill["id"]],
    )
    project_id = await a_project(box.workspace_id)
    task_id = await a_task(project_id, assigned_to=agent["id"])
    run_id = await shelve(marius_id=agent["id"], task_id=task_id)

    answered = await c.post(
        "/daemon/runs/claim",
        json={"workplace_ids": [box.workplace_id], "max": 1},
        headers=auth(box.token),
    )
    assert answered.status_code == 200, answered.text
    granted = answered.json()["runs"]
    assert [r["run_id"] for r in granted] == [str(run_id)], answered.text
    grant = granted[0]

    # The machine's own token, not the run's: `/daemon/*` is the machine's road, and the run
    # token opens the callback road the agent uses (FR-014a).
    run = auth(box.token)
    started = await c.post(
        f"/daemon/runs/{run_id}/start", json={"session_handle": ""}, headers=run
    )
    assert started.status_code == 200, started.text

    sent = await c.post(
        f"/daemon/runs/{run_id}/events",
        json={
            "events": [
                {
                    "seq": grant["first_seq"],
                    "type": "assistant.message",
                    "payload": {"text": "Done."},
                }
            ]
        },
        headers=run,
    )
    assert sent.status_code == 200, sent.text

    ended = await c.post(
        f"/daemon/runs/{run_id}/finish",
        json={"status": "completed"},
        headers=run,
    )
    assert ended.status_code == 200, ended.text

    async with get_sessionmaker()() as session:
        run_row = (
            await session.execute(select(RunModel).where(RunModel.id == run_id))
        ).scalar_one()
        task_row = (
            await session.execute(select(TaskModel).where(TaskModel.id == task_id))
        ).scalar_one()
        events = (
            await session.execute(
                select(RunEventModel)
                .where(RunEventModel.run_id == run_id)
                .order_by(RunEventModel.seq)
            )
        ).scalars().all()

    return {
        "grant": grant,
        "run_status": run_row.status,
        "task_status": task_row.status,
        "event_types": [e.type for e in events],
        "event_payloads": [e.payload for e in events],
        "run_id": run_id,
    }


def _comparable(grant: dict[str, Any]) -> dict[str, Any]:
    """The packet minus the identifiers, which is everything that is allowed to be the same."""
    return {k: v for k, v in grant.items() if k not in MAY_DIFFER}


# ── the packet ────────────────────────────────────────────────────────────────


async def test_the_same_task_is_handed_over_identically_on_both_families() -> None:
    """Gói việc giao xuống chỉ khác nhau ở mấy cái định danh, không khác gì nữa.

    So cả gói một lượt thay vì điểm từng trường: một trường mới thêm vào mà có rẽ nhánh theo
    loại CLI sẽ đỏ ở đây mà không ai phải nhớ bổ sung dòng kiểm.
    """
    async with _client() as c:
        one_shot = await _one_task_start_to_finish(
            c, cli_kind="claude_code", family="one_shot", email="two-clis-oneshot@armarius.dev"
        )
        acp = await _one_task_start_to_finish(
            c, cli_kind="gemini", family="acp", email="two-clis-acp@armarius.dev"
        )

    assert _comparable(one_shot["grant"]) == _comparable(acp["grant"]), (
        "cùng một đầu việc mà hai họ giao thức nhận hai gói khác nhau — "
        "khác biệt phải nằm sau hợp đồng ở tầng dưới cùng, không lọt lên đây"
    )
    # Named as well as compared, because an empty packet on both sides would satisfy an
    # equality check while proving nothing at all.
    assert one_shot["grant"]["prompt"], "gói việc không mang câu nào cho agent đọc"
    assert [s["files"] for s in one_shot["grant"]["skills"]] == [COOKBOOK]

    # The one field left out of the comparison, checked as what it actually is. Two runs
    # seconds apart cannot hold the same moment; they must hold the same *lease*, and a lease
    # that depended on the kind of CLI would show up here as minutes, not milliseconds.
    held_for = abs(
        datetime.fromisoformat(one_shot["grant"]["claim_expires_at"])
        - datetime.fromisoformat(acp["grant"]["claim_expires_at"])
    )
    assert held_for < timedelta(seconds=30), (
        f"hai họ giao thức được giữ việc với hai thời hạn khác nhau, lệch {held_for}"
    )


async def test_the_same_task_ends_the_same_way_on_both_families() -> None:
    """Bắt đầu, kể lại, kết thúc — cả ba để lại cùng một dấu vết.

    Nửa mà gói việc không phủ. Hai lượt có thể nhận cùng một gói rồi vẫn được ghi lại khác
    nhau, và người xem lại một lượt chạy đọc chính chỗ ghi ấy chứ không đọc cái gói.
    """
    async with _client() as c:
        one_shot = await _one_task_start_to_finish(
            c, cli_kind="claude_code", family="one_shot", email="two-clis-end-oneshot@armarius.dev"
        )
        acp = await _one_task_start_to_finish(
            c, cli_kind="gemini", family="acp", email="two-clis-end-acp@armarius.dev"
        )

    assert one_shot["run_status"] == acp["run_status"]
    assert one_shot["task_status"] == acp["task_status"]
    assert one_shot["event_types"] == acp["event_types"], (
        "một lượt chạy trên hai loại CLI để lại hai dãy sự kiện khác nhau"
    )
    assert one_shot["event_types"], (
        "không sự kiện nào được ghi, nên phép so trên không chứng minh gì"
    )


async def test_no_word_about_which_cli_it_was_reaches_the_run() -> None:
    """Loại CLI chỉ được nhắc ở đúng một chỗ: hàng chỗ làm.

    Đây là SC-008 nói bằng một câu. Thêm một loại agent CLI chỉ đụng tầng dưới cùng — nên tên
    của nó không được có mặt trong lượt chạy, trong sự kiện, hay trong câu gửi cho agent. Có
    mặt ở đó nghĩa là một thứ phía trên đã học được nó, và thứ ấy sẽ phải mở ra sửa vào ngày
    có loại thứ tư.
    """
    async with _client() as c:
        acp = await _one_task_start_to_finish(
            c, cli_kind="gemini", family="acp", email="two-clis-silent@armarius.dev"
        )

    written = " ".join(
        [acp["grant"]["prompt"], str(acp["event_payloads"]), str(acp["grant"]["runtime_options"])]
    ).lower()
    for word in ("gemini", "claude_code", "one_shot", "acp", "daemon", "workplace"):
        assert word not in written, (
            f"chữ {word!r} đi theo lượt chạy — tầng trên đã học được việc chạy bằng gì và ở đâu"
        )
