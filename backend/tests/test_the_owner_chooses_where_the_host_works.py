"""Người chủ chọn runtime cho người chủ nhà; hệ thống không chọn hộ (spec 003, sửa 2026-10-12).

FR-112, FR-125, FR-126, FR-127, FR-128, cùng FR-124 và FR-115 cho chỉ dẫn mặc định.

Người chủ gặp đúng ca này ngày 2026-10-12: máy có cả claude lẫn gemini, Livia tự bị đặt vào
gemini vì id của gemini nhỏ hơn, rồi FR-007 khoá luôn — không chat được, không đổi được. Từ lần
sửa này không gì đặt người chủ nhà vào chỗ làm ngoài **một cửa riêng**, và cửa ấy là một người
đang chọn.

Mọi bài đi qua **cửa thật**: máy xin vào, người duyệt, máy khai runtime, người chọn.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.application.use_cases.workspace_agent import (
    HOST_DEFAULT_INSTRUCTIONS,
    HOST_INSTRUCTIONS,
)
from armarius.infrastructure.daemon.models import AgentWorkplaceBindingModel
from armarius.infrastructure.database.engine import get_sessionmaker, init_db
from armarius.main import app
from tests.support.machines import (
    LinkedMachine,
    auth,
    link_machine,
    link_machine_to,
    put_host_to_work,
    the_host,
)


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict[str, str], str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Vũ", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    headers = auth(r.json()["tokens"]["access_token"])
    workspaces = await c.get("/v1/workspaces", headers=headers)
    return headers, workspaces.json()[0]["id"]


async def _bound_to(marius_id: str) -> UUID | None:
    async with get_sessionmaker()() as session:
        return (
            await session.execute(
                select(AgentWorkplaceBindingModel.workplace_id).where(
                    AgentWorkplaceBindingModel.marius_id == UUID(marius_id)
                )
            )
        ).scalar_one_or_none()


async def _two_runtimes(
    c: AsyncClient, email: str
) -> tuple[dict[str, str], str, LinkedMachine, LinkedMachine]:
    """Một không gian làm việc có hai runtime sẵn sàng, trên hai máy.

    Loại CLI thứ hai chỉ là một lời khai qua HTTP: không binary nào chạy (research R10).
    """
    headers, ws = await _register(c, email)
    first = await link_machine_to(c, headers, ws, hostname="may-mot", cli_kind="claude_code")
    second = await link_machine_to(c, headers, ws, hostname="may-hai", cli_kind="gemini")
    return headers, ws, first, second


# ── FR-112: không còn tự đặt chỗ ────────────────────────────────────────────────


async def test_a_machine_reporting_runtimes_does_not_place_the_host() -> None:
    async with _client() as c:
        headers, ws, _first, _second = await _two_runtimes(c, "no-auto-place@armarius.dev")

        host = await the_host(c, headers, ws)
        assert host["offline_reason"] == "not_placed", host
        assert host["runtime"] is None, host
        assert await _bound_to(host["id"]) is None


# ── FR-125, FR-126: người chủ chọn ──────────────────────────────────────────────


async def test_the_host_works_where_its_owner_chose_not_where_the_smallest_id_is() -> None:
    """Đúng ca của người chủ: hai runtime, và cái được chọn **không** phải cái id nhỏ nhất."""
    async with _client() as c:
        headers, ws, first, second = await _two_runtimes(c, "owner-chooses@armarius.dev")
        chosen = max((first, second), key=lambda m: m.workplace_id)

        placed = await put_host_to_work(
            c, headers, ws, chosen.workplace_id, instructions="Trả lời ngắn thôi."
        )
        assert placed.status_code == 200, placed.text
        body = placed.json()

        assert await _bound_to(body["id"]) == UUID(chosen.workplace_id)
        expected = "gemini" if chosen is second else "claude_code"
        assert body["runtime"]["cli_kind"] == expected, body
        # Chữ người dùng tự viết giữ nguyên thứ tiếng của họ (FR-115).
        assert body["instructions"] == "Trả lời ngắn thôi."
        # Kiểm ngay lúc được đặt chỗ (FR-006e, FR-126), không đợi vòng kiểm định kỳ.
        assert body["liveness"] == "online", body


async def test_without_instructions_the_host_keeps_the_ones_it_has() -> None:
    """Trang người chủ nhà chọn runtime mà không gửi chỉ dẫn (FR-128): chỉ dẫn đứng yên."""
    async with _client() as c:
        machine = await link_machine(c, "keeps-instructions@armarius.dev")

        placed = await put_host_to_work(
            c, machine.headers, machine.workspace_id, machine.workplace_id
        )
        assert placed.status_code == 200, placed.text
        assert placed.json()["instructions"] == HOST_DEFAULT_INSTRUCTIONS


async def test_an_empty_box_is_saved_as_no_instructions_and_the_job_stays() -> None:
    """Xoá trắng ô chỉ dẫn là một câu trả lời thật, và nó không lấy mất việc của người chủ nhà."""
    async with _client() as c:
        machine = await link_machine(c, "empty-box@armarius.dev")

        placed = await put_host_to_work(
            c, machine.headers, machine.workspace_id, machine.workplace_id, instructions=""
        )
        assert placed.status_code == 200, placed.text
        assert placed.json()["instructions"] == ""
        assert placed.json()["system_instructions"] == HOST_INSTRUCTIONS


# ── FR-124, FR-115: chỉ dẫn mặc định ───────────────────────────────────────────


async def test_a_new_host_starts_with_the_default_instructions_beside_its_system_prompt() -> None:
    async with _client() as c:
        headers, ws = await _register(c, "default-instructions@armarius.dev")

        host = await the_host(c, headers, ws)
        assert host["instructions"] == HOST_DEFAULT_INSTRUCTIONS
        assert host["system_instructions"] == HOST_INSTRUCTIONS
        # Hai nửa tách nhau: nửa người sửa được không chép lại việc của nửa kia.
        assert HOST_INSTRUCTIONS not in HOST_DEFAULT_INSTRUCTIONS


async def test_asking_for_the_host_again_does_not_reset_what_its_owner_wrote() -> None:
    """Cửa tạo người chủ nhà gọi lại được (FR-113), và gọi lại không ghi đè chữ của người chủ."""
    async with _client() as c:
        headers, ws = await _register(c, "not-reset@armarius.dev")
        host = await the_host(c, headers, ws)
        edited = await c.patch(
            f"/v1/workspaces/{ws}/mariuses/{host['id']}",
            headers=headers,
            json={"instructions": "Của tôi."},
        )
        assert edited.status_code == 200, edited.text

        await app.state.container.workspace_agent.provide_host(UUID(ws))

        assert (await the_host(c, headers, ws))["instructions"] == "Của tôi."


# ── FR-127: đã có chỗ làm thì không đổi ─────────────────────────────────────────


async def test_a_host_that_already_works_somewhere_is_not_moved_and_says_where() -> None:
    async with _client() as c:
        headers, ws, first, second = await _two_runtimes(c, "already-placed@armarius.dev")
        assert (await put_host_to_work(c, headers, ws, first.workplace_id)).status_code == 200

        again = await put_host_to_work(c, headers, ws, second.workplace_id, instructions="x")
        assert again.status_code == 409, again.text
        assert again.json()["code"] == "agent_already_placed"
        # Cửa sổ tới sau nói được người chủ nhà đã chạy ở đâu.
        assert again.json()["params"] == {"cli_kind": "claude_code", "machine_name": "may-mot"}

        host = await the_host(c, headers, ws)
        assert await _bound_to(host["id"]) == UUID(first.workplace_id)
        assert host["instructions"] == HOST_DEFAULT_INSTRUCTIONS, "lỗi thì không gì được đổi"


# ── chỉ người chủ nhà ───────────────────────────────────────────────────────────


async def test_an_ordinary_agent_cannot_be_given_a_runtime_through_this_door() -> None:
    async with _client() as c:
        machine = await link_machine(c, "ordinary-agent@armarius.dev")
        created = await c.post(
            f"/v1/workspaces/{machine.workspace_id}/mariuses",
            headers=machine.headers,
            json={"name": "Cassia", "workplace_id": machine.workplace_id},
        )
        assert created.status_code == 201, created.text

        refused = await c.post(
            f"/v1/workspaces/{machine.workspace_id}/mariuses/{created.json()['id']}/placement",
            headers=machine.headers,
            json={"workplace_id": machine.workplace_id},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "placement_is_fixed"


async def test_an_ordinary_agent_that_lost_its_machine_stays_without_one() -> None:
    """K7: gỡ máy thì agent thường mất chỗ làm, và cửa này không được thành đường lén nới FR-007."""
    async with _client() as c:
        headers, ws = await _register(c, "lost-machine@armarius.dev")
        gone = await link_machine_to(c, headers, ws, hostname="may-cu")
        created = await c.post(
            f"/v1/workspaces/{ws}/mariuses",
            headers=headers,
            json={"name": "Decima", "workplace_id": gone.workplace_id},
        )
        assert created.status_code == 201, created.text
        removed = await c.delete(f"/v1/workspaces/{ws}/machines/{gone.machine_id}", headers=headers)
        assert removed.status_code == 204, removed.text
        fresh = await link_machine_to(c, headers, ws, hostname="may-moi")

        refused = await c.post(
            f"/v1/workspaces/{ws}/mariuses/{created.json()['id']}/placement",
            headers=headers,
            json={"workplace_id": fresh.workplace_id},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "placement_is_fixed"
        assert await _bound_to(created.json()["id"]) is None


async def test_a_host_that_lost_its_machine_can_be_given_another() -> None:
    """Không phải đổi chỗ làm: chỗ làm cũ đã không còn (spec 003, edge case máy bị gỡ)."""
    async with _client() as c:
        headers, ws = await _register(c, "host-lost-machine@armarius.dev")
        gone = await link_machine_to(c, headers, ws, hostname="may-cu")
        assert (await put_host_to_work(c, headers, ws, gone.workplace_id)).status_code == 200
        removed = await c.delete(f"/v1/workspaces/{ws}/machines/{gone.machine_id}", headers=headers)
        assert removed.status_code == 204, removed.text
        assert (await the_host(c, headers, ws))["offline_reason"] == "not_placed"

        fresh = await link_machine_to(c, headers, ws, hostname="may-moi")
        placed = await put_host_to_work(c, headers, ws, fresh.workplace_id)
        assert placed.status_code == 200, placed.text
        assert placed.json()["runtime"]["machine_name"] == "may-moi"


# ── chỗ làm không nhận được ─────────────────────────────────────────────────────


async def test_a_runtime_that_cannot_take_work_is_refused_and_nothing_changes() -> None:
    """Edge case *runtime tắt trước khi bấm xong*: từ chối, nói vì sao, không đặt vào đâu cả."""
    async with _client() as c:
        headers, ws = await _register(c, "not-ready@armarius.dev")
        shut = await link_machine_to(c, headers, ws, symlink_capable=False)

        refused = await put_host_to_work(c, headers, ws, shut.workplace_id, instructions="x")
        assert refused.status_code == 400, refused.text
        assert refused.json()["code"] == "placement_not_ready"
        assert refused.json()["params"]["reason"], refused.json()

        host = await the_host(c, headers, ws)
        assert await _bound_to(host["id"]) is None
        assert host["instructions"] == HOST_DEFAULT_INSTRUCTIONS


async def test_a_runtime_of_another_workspace_is_not_found() -> None:
    async with _client() as c:
        headers, ws = await _register(c, "foreign-runtime@armarius.dev")
        made = await c.post("/v1/workspaces", headers=headers, json={"name": "Xưởng hai"})
        other = await link_machine_to(c, headers, made.json()["id"], hostname="may-khac")

        refused = await put_host_to_work(c, headers, ws, other.workplace_id)
        assert refused.status_code == 404, refused.text
        assert refused.json()["code"] == "placement_not_found"


# ── Điều I: không phải của mình thì là không có ────────────────────────────────


async def test_somebody_elses_workspace_reads_as_missing() -> None:
    async with _client() as c:
        owner = await link_machine(c, "owner-of-host@armarius.dev")
        host = await the_host(c, owner.headers, owner.workspace_id)
        stranger, _ws = await _register(c, "stranger-to-host@armarius.dev")

        refused = await c.post(
            f"/v1/workspaces/{owner.workspace_id}/mariuses/{host['id']}/placement",
            headers=stranger,
            json={"workplace_id": owner.workplace_id},
        )
        assert refused.status_code == 404, refused.text
        assert await _bound_to(host["id"]) is None


async def test_an_agent_of_another_workspace_is_not_found_here() -> None:
    async with _client() as c:
        machine = await link_machine(c, "two-hosts@armarius.dev")
        made = await c.post("/v1/workspaces", headers=machine.headers, json={"name": "Xưởng hai"})
        other_host = await the_host(c, machine.headers, made.json()["id"])

        refused = await c.post(
            f"/v1/workspaces/{machine.workspace_id}/mariuses/{other_host['id']}/placement",
            headers=machine.headers,
            json={"workplace_id": machine.workplace_id},
        )
        assert refused.status_code == 404, refused.text
        assert refused.json()["code"] == "agent_not_found"
