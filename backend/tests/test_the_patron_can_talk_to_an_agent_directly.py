"""Người chủ nói chuyện thẳng với agent của mình, và màn agent nói nó làm ở đâu (FR-007p, FR-007o).

Người chủ yêu cầu 2026-09-24: tab Tổng quan của một agent phải có **khung chat trực tiếp** với
nó, và phải hiện **runtime hiện tại** — agent ấy là CLI nào, trên máy nào.

Những điều được đo, và đều đi qua app thật cùng cửa daemon thật:

  * một câu người chủ viết thành **một lượt chạy nằm trên kệ của máy agent làm việc**, và gói
    việc máy nhận mang cả **chỉ dẫn của agent** lẫn **câu người chủ vừa viết** — một lượt không
    gắn đầu việc nào chỉ nhận đúng chữ được ghi sẵn cùng nó, nên thiếu một trong hai là agent trả
    lời như người lạ, hoặc trả lời một câu không ai hỏi;
  * câu trả lời dựng lại từ **thứ máy ghi xuống**, và người chủ **thấy nó tới dần** chứ không
    nhìn một khung đứng im;
  * một lượt, một lúc: câu thứ hai trong lúc agent còn đang trả lời bị từ chối;
  * agent không liên lạc được thì **không viết cho nó được** — khung tắt, không xếp hàng;
  * **đọc** cuộc trò chuyện không tạo ra gì;
  * agent của người khác đọc **y như không tồn tại** (Hiến pháp I);
  * xoá agent thì cuộc trò chuyện đi theo;
  * dữ liệu agent mang **CLI và tên máy** nó làm ở đó, và trả `null` khi máy bị gỡ khỏi workspace.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.domain.entities.leader_chat import ChatState
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import AgentConversationModel, RunModel
from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import LinkedMachine, auth, link_machine

pytestmark = pytest.mark.anyio

_INSTRUCTIONS = "You are a careful archivist. Always answer in one short paragraph."


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class Talking:
    """An agent on a real machine, the machine's token, and the person who owns both."""

    def __init__(self, machine: LinkedMachine, marius_id: str) -> None:
        self.machine = machine
        self.marius_id = marius_id

    @property
    def chat(self) -> str:
        return f"/v1/workspaces/{self.machine.workspace_id}/mariuses/{self.marius_id}/chat"

    @property
    def as_machine(self) -> dict[str, str]:
        return auth(self.machine.token)


async def _an_agent(c: AsyncClient, *, online: bool = True, hostname: str = "thinkpad") -> Talking:
    machine = await link_machine(c, f"chat-{uuid4().hex[:8]}@acme.dev", hostname=hostname)
    agent = await invite_agent(
        c,
        machine.workspace_id,
        machine.headers,
        name=f"Sabine-{uuid4().hex[:4]}",
        workplace_id=machine.workplace_id,
        adapter_type=None,
        instructions=_INSTRUCTIONS,
    )
    if online:
        await app.state.container.liveness.record_signal(UUID(agent["id"]))
    return Talking(machine, agent["id"])


async def _conversation(marius_id: str) -> AgentConversationModel | None:
    async with get_sessionmaker()() as session:
        found = await session.execute(
            select(AgentConversationModel).where(
                AgentConversationModel.marius_id == UUID(marius_id)
            )
        )
        return found.scalar_one_or_none()


async def _driving_run(marius_id: str, *, attempts: int = 200) -> UUID:
    for _ in range(attempts):
        conversation = await _conversation(marius_id)
        if conversation is not None and conversation.driving_run_id is not None:
            return conversation.driving_run_id
        await asyncio.sleep(0.02)
    raise AssertionError("câu người chủ viết không được giao cho lượt chạy nào")


async def _settled(marius_id: str, *, attempts: int = 200) -> AgentConversationModel:
    for _ in range(attempts):
        conversation = await _conversation(marius_id)
        if conversation is not None and conversation.state != str(ChatState.THINKING):
            return conversation
        await asyncio.sleep(0.02)
    conversation = await _conversation(marius_id)
    assert conversation is not None
    return conversation


async def _machine_takes(t: Talking, c: AsyncClient, run_id: UUID) -> dict:
    claimed = await c.post(
        "/daemon/runs/claim",
        headers=t.as_machine,
        json={"workplace_ids": [t.machine.workplace_id], "free_slots": 1},
    )
    assert claimed.status_code == 200, claimed.text
    mine = [r for r in claimed.json()["runs"] if r["run_id"] == str(run_id)]
    assert mine, f"cửa nhận việc không đưa ra lượt chạy {run_id}: {claimed.text}"
    started = await c.post(
        f"/daemon/runs/{run_id}/start", headers=t.as_machine, json={"session_handle": ""}
    )
    assert started.status_code == 200, started.text
    return mine[0]


async def _machine_says(t: Talking, c: AsyncClient, run_id: UUID, seq: int, text: str) -> None:
    said = await c.post(
        f"/daemon/runs/{run_id}/events",
        headers=t.as_machine,
        json={"events": [{"seq": seq, "type": "assistant.message", "payload": {"text": text}}]},
    )
    assert said.status_code in (200, 202), said.text


async def _machine_finishes(
    t: Talking, c: AsyncClient, run_id: UUID, *, status: str = "completed"
) -> None:
    done = await c.post(
        f"/daemon/runs/{run_id}/finish", headers=t.as_machine, json={"status": status}
    )
    assert done.status_code == 200, done.text


async def _write(c: AsyncClient, t: Talking, text: str):
    """The patron writes to the agent, through the route the chat box uses."""
    return await c.post(f"{t.chat}/messages", headers=t.machine.headers, json={"message": text})


def _heard(marius_id: str) -> list[tuple[str, dict]]:
    bus = app.state.container.control_bus
    return [(e.type, e.data) for e in bus.backlog(f"agent-chat:{marius_id}")]


# ── a message becomes a turn where the agent works ────────────────────────────────


async def test_a_message_becomes_a_run_on_the_agents_machine_carrying_who_it_is() -> None:
    async with _client() as c:
        t = await _an_agent(c)
        sent = await c.post(
            f"{t.chat}/messages", headers=t.machine.headers, json={"message": "Chào Sabine"}
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["state"] == "thinking"

        run_id = await _driving_run(t.marius_id)
        run = await _run(run_id)
        assert run.status == "queued", "lượt nói phải nằm chờ trên kệ cho tới khi máy nhận"
        assert run.task_id is None and run.project_id is None, (
            "cuộc trò chuyện trực tiếp không thuộc dự án hay đầu việc nào"
        )
        assert [c["code"] for c in run.trigger_causes] == ["agent_chat_message"]

        granted = await _machine_takes(t, c, run_id)
        prompt = granted["prompt"]
        assert _INSTRUCTIONS in prompt, (
            "gói việc không mang chỉ dẫn của agent — nó sẽ trả lời như một người lạ"
        )
        assert "Chào Sabine" in prompt, "gói việc không mang câu người chủ vừa viết"


async def _run(run_id: UUID) -> RunModel:
    async with get_sessionmaker()() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None
        return run


async def test_the_reply_is_what_the_machine_wrote_down_and_arrives_as_it_is_written() -> None:
    async with _client() as c:
        t = await _an_agent(c)
        await _write(c, t, "Hôm nay thế nào?")
        run_id = await _driving_run(t.marius_id)
        granted = await _machine_takes(t, c, run_id)
        await _machine_says(t, c, run_id, granted["first_seq"], "Mọi thứ vẫn ổn.")
        await _machine_finishes(t, c, run_id)

        conversation = await _settled(t.marius_id)
        assert conversation.state == str(ChatState.IDLE)
        assert [(turn["role"], turn["text"]) for turn in conversation.transcript] == [
            ("patron", "Hôm nay thế nào?"),
            ("agent", "Mọi thứ vẫn ổn."),
        ]
        heard = _heard(t.marius_id)
        assert ("assistant.delta", {"text": "Mọi thứ vẫn ổn."}) in heard, (
            "người chủ không thấy câu trả lời tới dần — khung đứng im tới khi xong hẳn"
        )
        assert ("agent.message", {"text": "Mọi thứ vẫn ổn."}) in heard

        shown = await c.get(t.chat, headers=t.machine.headers)
        assert shown.json()["state"] == "idle"
        assert [turn["role"] for turn in shown.json()["transcript"]] == ["patron", "agent"]


async def test_a_second_message_waits_for_the_first_answer() -> None:
    async with _client() as c:
        t = await _an_agent(c)
        first = await _write(c, t, "Một")
        assert first.status_code == 200
        second = await _write(c, t, "Hai")
        assert second.status_code == 409, second.text
        assert second.json()["code"] == "agent_still_replying"


async def test_a_failed_turn_gives_the_box_back() -> None:
    async with _client() as c:
        t = await _an_agent(c)
        await _write(c, t, "Một")
        run_id = await _driving_run(t.marius_id)
        await _machine_takes(t, c, run_id)
        await _machine_finishes(t, c, run_id, status="failed")

        conversation = await _settled(t.marius_id)
        assert conversation.state == str(ChatState.FAILED)
        again = await _write(c, t, "Hai")
        assert again.status_code == 200, (
            "một lượt hỏng mà khoá luôn khung chat thì người chủ không thử lại được"
        )


# ── who may write, and what reading does ──────────────────────────────────────────


async def test_an_agent_that_cannot_be_reached_cannot_be_written_to() -> None:
    async with _client() as c:
        t = await _an_agent(c, online=False)
        shown = await c.get(t.chat, headers=t.machine.headers)
        assert shown.status_code == 200
        assert shown.json()["agent_online"] is False
        sent = await _write(c, t, "Alo")
        assert sent.status_code == 409, sent.text
        assert sent.json()["code"] == "agent_offline"
        assert await _conversation(t.marius_id) is None, "câu bị từ chối vẫn để lại một hàng"


async def test_reading_a_conversation_creates_nothing() -> None:
    async with _client() as c:
        t = await _an_agent(c)
        shown = await c.get(t.chat, headers=t.machine.headers)
        assert shown.status_code == 200
        assert shown.json()["transcript"] == []
        assert shown.json()["agent_online"] is True
        assert await _conversation(t.marius_id) is None, "mở trang agent mà ghi vào CSDL"


async def test_someone_elses_agent_reads_as_not_there() -> None:
    async with _client() as c:
        t = await _an_agent(c)
        stranger = await link_machine(c, f"stranger-{uuid4().hex[:8]}@acme.dev")
        for how, path in (
            ("GET", t.chat),
            ("POST", f"{t.chat}/messages"),
            ("GET", f"{t.chat}/stream"),
        ):
            body = {"message": "x"} if how == "POST" else None
            answer = await c.request(how, path, headers=stranger.headers, json=body)
            assert answer.status_code == 404, f"{how} {path} → {answer.status_code}"
        # Nor through the stranger's own workspace id: the agent is not there either.
        wrong_home = f"/v1/workspaces/{stranger.workspace_id}/mariuses/{t.marius_id}/chat"
        assert (await c.get(wrong_home, headers=stranger.headers)).status_code == 404


async def test_removing_an_agent_takes_its_conversation_with_it() -> None:
    async with _client() as c:
        t = await _an_agent(c)
        await _write(c, t, "Một")
        assert await _conversation(t.marius_id) is not None
        gone = await c.delete(
            f"/v1/workspaces/{t.machine.workspace_id}/mariuses/{t.marius_id}",
            headers=t.machine.headers,
        )
        assert gone.status_code == 204, gone.text
        assert await _conversation(t.marius_id) is None, "xoá agent mà cuộc trò chuyện ở lại"


# ── the agent says where it works ─────────────────────────────────────────────────


async def test_an_agent_says_which_cli_on_which_machine_it_works_at() -> None:
    async with _client() as c:
        t = await _an_agent(c, hostname="studio-mac")
        listed = await c.get(
            f"/v1/workspaces/{t.machine.workspace_id}/mariuses", headers=t.machine.headers
        )
        mine = next(a for a in listed.json() if a["id"] == t.marius_id)
        assert mine["runtime"] == {"cli_kind": "claude_code", "machine_name": "studio-mac"}

        removed = await c.delete(
            f"/v1/workspaces/{t.machine.workspace_id}/machines/{t.machine.machine_id}",
            headers=t.machine.headers,
        )
        assert removed.status_code == 204, removed.text
        listed = await c.get(
            f"/v1/workspaces/{t.machine.workspace_id}/mariuses", headers=t.machine.headers
        )
        mine = next(a for a in listed.json() if a["id"] == t.marius_id)
        assert mine["runtime"] is None, "máy đã gỡ mà agent vẫn khai là làm ở đó"
