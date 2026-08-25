"""Một cái máy còn thở không chứng minh được agent trên nó chạy được (T076, FR-055b, FR-006a).

Đây là chỗ dễ nhầm nhất của cả mô hình daemon, và cái nhầm ấy không kêu: nhịp của máy đều
đặn, biểu đồ xanh, mà agent CLI thì đã bị gỡ khỏi máy từ lâu. Nếu nhịp được tính là dấu hiệu
sống của agent, cái máy ấy trông khoẻ mãi mãi và FR-006a không bao giờ thành hiện thực.

Nên hai thứ được đo tách bạch ở đây:

  * **Nhịp chứng minh liên lạc tới máy.** Nó không ghi bất cứ gì lên agent — không đổi
    liveness, không dịch `last_seen_at`.
  * **Chỗ làm sẵn sàng hay không là câu trả lời của một cú gọi khác.** Chỉ cú ấy mới biết CLI
    còn trên máy hay đã đi.

Mọi đường đứt trong chuỗi — chưa đặt agent vào đâu, CLI bị gỡ, máy tắt hẳn — đều rơi về đúng
một kết luận cho tầng trên: agent ngoại tuyến (FR-006a). Bài kiểm đi qua app thật và ngồi
xuống tận `DaemonLivenessProbe`, vì kết luận ấy là thứ duy nhất tầng trên được nhìn thấy.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from armarius.infrastructure.daemon.liveness import DaemonLivenessProbe
from armarius.infrastructure.daemon.models import MachineModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.persistence.unit_of_work import make_uow
from armarius.main import app
from armarius.shared.clock import utcnow

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _machine_with_one_cli(
    c: AsyncClient, email: str, *, cli: str = "claude_code"
) -> tuple[str, str, str]:
    """Một người, một workspace, một máy đã nối, một agent CLI đã khai.

    Trả về (token của máy, workspace, id chỗ làm). Không đi tắt đoạn nào: token này đúng là
    thứ một daemon thật đang cầm.
    """
    registered = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    person = registered.json()["tokens"]["access_token"]
    workspace = (await c.get("/v1/workspaces", headers=_auth(person))).json()[0]["id"]

    started = await c.post(
        "/daemon/link/start",
        json={"platform": "linux", "daemon_version": "0.1.0", "hostname": "box"},
    )
    code = started.json()["code"]
    await c.post(
        f"/v1/machines/link/{code}/approve",
        json={"workspace_id": workspace},
        headers=_auth(person),
    )
    machine = (await c.post("/daemon/link/poll", json={"code": code})).json()["token"]

    synced = await c.put(
        "/daemon/workplaces",
        json={
            "workplaces": [
                {
                    "cli_kind": cli,
                    "cli_version": "1.0.0",
                    "protocol_family": "one_shot",
                    "capabilities": {},
                }
            ],
            "symlink_capable": True,
        },
        headers=_auth(machine),
    )
    assert synced.status_code == 200, synced.text
    return machine, workspace, synced.json()["workplaces"][0]["id"]


async def _an_agent(c: AsyncClient, person: str, workspace: str, workplace: str) -> dict:
    made = await c.post(
        f"/v1/workspaces/{workspace}/mariuses",
        json={"name": "Marin", "workplace_id": workplace},
        headers=_auth(person),
    )
    assert made.status_code == 201, made.text
    return made.json()


async def _person(c: AsyncClient, email: str) -> str:
    registered = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    return registered.json()["tokens"]["access_token"]


async def _beat(c: AsyncClient, machine: str) -> None:
    beaten = await c.post(
        "/daemon/heartbeat",
        json={"free_slots": 1, "running": []},
        headers=_auth(machine),
    )
    assert beaten.status_code == 200, beaten.text


async def _alive(marius_id: str) -> bool:
    """Đúng câu hỏi mà tầng trên được phép hỏi, hỏi qua đúng cái cổng nó hỏi."""
    async with make_uow() as uow:
        marius = await uow.mariuses.get(UUID(marius_id))
    assert marius is not None
    return await DaemonLivenessProbe(make_uow).probe(marius)


async def _stop_beating(workspace: str, *, silent_for: timedelta) -> None:
    """Đẩy nhịp cuối của mọi máy trong workspace lùi về quá khứ.

    Lùi đồng hồ của dữ liệu chứ không lùi đồng hồ của tiến trình: cái cần đo là *khoảng
    lặng*, và một bài kiểm phải chờ 45 giây thật là một bài kiểm không ai chạy.
    """
    async with get_sessionmaker()() as session:
        await session.execute(
            update(MachineModel)
            .where(MachineModel.workspace_id == UUID(workspace))
            .values(last_heartbeat_at=utcnow() - silent_for)
        )
        await session.commit()


# ── 1. nhịp không chạm vào agent ──────────────────────────────────────────────


async def test_a_beat_does_not_touch_the_agent_at_all() -> None:
    """Nhịp là chuyện của máy. Nó không được để lại dấu vết nào trên agent (FR-055b)."""
    async with _client() as c:
        person = await _person(c, "beat-untouched@example.com")
        machine, workspace, workplace = await _machine_with_one_cli(
            c, "beat-untouched-m@example.com"
        )
        # Người vừa đăng ký ở trên không phải chủ workspace của máy — lấy đúng chủ ấy.
        person = (
            await c.post(
                "/auth/login",
                json={"email": "beat-untouched-m@example.com", "password": "password1234"},
            )
        ).json()["tokens"]["access_token"]
        agent = await _an_agent(c, person, workspace, workplace)

        before = (
            await c.get(f"/v1/workspaces/{workspace}/mariuses", headers=_auth(person))
        ).json()[0]

        for _ in range(3):
            await _beat(c, machine)

        after = (
            await c.get(f"/v1/workspaces/{workspace}/mariuses", headers=_auth(person))
        ).json()[0]

        assert after["id"] == agent["id"]
        assert after["liveness"] == before["liveness"]
        assert after["last_seen_at"] == before["last_seen_at"]


# ── 2. máy sống, CLI đã đi ────────────────────────────────────────────────────


async def test_a_beating_machine_whose_cli_is_gone_still_leaves_the_agent_offline() -> None:
    """Đây là ca chính của FR-055b. Máy thở đều, CLI không còn, agent phải ngoại tuyến."""
    async with _client() as c:
        machine, workspace, workplace = await _machine_with_one_cli(
            c, "beat-cli-gone@example.com"
        )
        person = (
            await c.post(
                "/auth/login",
                json={"email": "beat-cli-gone@example.com", "password": "password1234"},
            )
        ).json()["tokens"]["access_token"]
        agent = await _an_agent(c, person, workspace, workplace)

        assert await _alive(agent["id"]) is True

        # Người dùng gỡ CLI. Lượt khai kế tiếp của máy không còn nó nữa.
        await c.put(
            "/daemon/workplaces",
            json={"workplaces": [], "symlink_capable": True},
            headers=_auth(machine),
        )
        # Và cái máy vẫn khoẻ, vẫn báo nhịp đều như chưa có chuyện gì.
        for _ in range(3):
            await _beat(c, machine)

        assert await _alive(agent["id"]) is False

        shown = (
            await c.get(f"/v1/workspaces/{workspace}/mariuses", headers=_auth(person))
        ).json()[0]
        assert shown["offline_reason"] == "cli_removed"


# ── 3. máy im hẳn ─────────────────────────────────────────────────────────────


async def test_a_machine_that_stops_beating_takes_every_agent_on_it_offline() -> None:
    """Đường đứt thứ hai của FR-006a, và nó phải ra đúng cùng một kết luận."""
    async with _client() as c:
        machine, workspace, workplace = await _machine_with_one_cli(
            c, "beat-silence@example.com"
        )
        person = (
            await c.post(
                "/auth/login",
                json={"email": "beat-silence@example.com", "password": "password1234"},
            )
        ).json()["tokens"]["access_token"]
        agent = await _an_agent(c, person, workspace, workplace)
        await _beat(c, machine)
        assert await _alive(agent["id"]) is True

        await _stop_beating(workspace, silent_for=timedelta(minutes=5))

        assert await _alive(agent["id"]) is False

        shown = (
            await c.get(f"/v1/workspaces/{workspace}/mariuses", headers=_auth(person))
        ).json()[0]
        # Chỗ làm vẫn ghi là sẵn sàng — nó được ghi lúc máy còn nói chuyện được, và không ai
        # về sửa lại được nữa. Lý do phải tới từ khoảng lặng, không từ hàng cũ ấy.
        assert shown["offline_reason"] == "machine_unreachable"


async def test_one_missed_beat_is_not_a_death() -> None:
    """Ngưỡng là ba nhịp lỡ, không phải một. Máy nào cũng có lúc trả lời chậm."""
    async with _client() as c:
        machine, workspace, workplace = await _machine_with_one_cli(
            c, "beat-hiccup@example.com"
        )
        person = (
            await c.post(
                "/auth/login",
                json={"email": "beat-hiccup@example.com", "password": "password1234"},
            )
        ).json()["tokens"]["access_token"]
        agent = await _an_agent(c, person, workspace, workplace)
        await _beat(c, machine)

        await _stop_beating(workspace, silent_for=timedelta(seconds=20))

        assert await _alive(agent["id"]) is True


# ── 4. hai đường đứt cùng lúc ─────────────────────────────────────────────────


async def test_a_gone_cli_outranks_a_quiet_machine_when_both_are_true() -> None:
    """Cùng lúc tắt máy và gỡ CLI thì người đọc cần biết cái họ phải đi cài lại.

    Bảo họ mỗi chuyện "máy đang tắt" là đẩy họ đi bật máy lên rồi thấy y nguyên như cũ. Mã
    `cli_removed` được ghi bởi một lượt quét đã thật sự chạy trên máy ấy, nên nó là dữ kiện
    đo được; còn máy im là sự kiện mới hơn nhưng mơ hồ hơn.
    """
    async with _client() as c:
        machine, workspace, workplace = await _machine_with_one_cli(
            c, "beat-both@example.com"
        )
        person = (
            await c.post(
                "/auth/login",
                json={"email": "beat-both@example.com", "password": "password1234"},
            )
        ).json()["tokens"]["access_token"]
        agent = await _an_agent(c, person, workspace, workplace)

        await c.put(
            "/daemon/workplaces",
            json={"workplaces": [], "symlink_capable": True},
            headers=_auth(machine),
        )
        await _stop_beating(workspace, silent_for=timedelta(minutes=5))

        assert await _alive(agent["id"]) is False
        shown = (
            await c.get(f"/v1/workspaces/{workspace}/mariuses", headers=_auth(person))
        ).json()[0]
        assert shown["offline_reason"] == "cli_removed"


# ── 5. máy của người khác ─────────────────────────────────────────────────────


async def test_a_machine_beating_elsewhere_does_nothing_for_this_agent() -> None:
    """Nhịp của máy A không được đỡ cho agent sống trên máy B — kể cả cùng một workspace."""
    async with _client() as c:
        first, workspace, workplace = await _machine_with_one_cli(
            c, "beat-elsewhere@example.com"
        )
        person = (
            await c.post(
                "/auth/login",
                json={"email": "beat-elsewhere@example.com", "password": "password1234"},
            )
        ).json()["tokens"]["access_token"]
        agent = await _an_agent(c, person, workspace, workplace)

        started = await c.post(
            "/daemon/link/start",
            json={"platform": "linux", "daemon_version": "0.1.0", "hostname": "other"},
        )
        code = started.json()["code"]
        await c.post(
            f"/v1/machines/link/{code}/approve",
            json={"workspace_id": workspace},
            headers=_auth(person),
        )
        second = (await c.post("/daemon/link/poll", json={"code": code})).json()["token"]

        await _stop_beating(workspace, silent_for=timedelta(minutes=5))
        # Chỉ máy thứ hai sống lại. Máy giữ chỗ làm của agent vẫn im.
        await _beat(c, second)

        assert await _alive(agent["id"]) is False
        assert first  # cái máy giữ agent, cố tình không cho thở


# ── 6. một chỗ làm, nhiều agent ───────────────────────────────────────────────


async def test_every_agent_on_a_silent_machine_falls_together() -> None:
    """FR-006a nói "mọi agent trên máy đó", không phải agent nào tình cờ bị hỏi tới."""
    async with _client() as c:
        machine, workspace, workplace = await _machine_with_one_cli(
            c, "beat-all@example.com"
        )
        person = (
            await c.post(
                "/auth/login",
                json={"email": "beat-all@example.com", "password": "password1234"},
            )
        ).json()["tokens"]["access_token"]
        made = []
        for name in ("Marin", "Colette", "Aurel"):
            answered = await c.post(
                f"/v1/workspaces/{workspace}/mariuses",
                json={"name": name, "workplace_id": workplace},
                headers=_auth(person),
            )
            assert answered.status_code == 201, answered.text
            made.append(answered.json()["id"])
        await _beat(c, machine)
        assert [await _alive(one) for one in made] == [True, True, True]

        await _stop_beating(workspace, silent_for=timedelta(minutes=5))

        assert [await _alive(one) for one in made] == [False, False, False]

        listed = (
            await c.get(f"/v1/workspaces/{workspace}/mariuses", headers=_auth(person))
        ).json()
        assert {one["offline_reason"] for one in listed} == {"machine_unreachable"}


# ── 7. chỗ làm chưa từng được khai ────────────────────────────────────────────


async def test_a_machine_that_never_beat_is_not_treated_as_fresh() -> None:
    """Chưa từng có nhịp nào không phải là "vừa mới có nhịp"."""
    async with _client() as c:
        _, workspace, workplace = await _machine_with_one_cli(
            c, "beat-never@example.com"
        )
        person = (
            await c.post(
                "/auth/login",
                json={"email": "beat-never@example.com", "password": "password1234"},
            )
        ).json()["tokens"]["access_token"]
        agent = await _an_agent(c, person, workspace, workplace)

        async with get_sessionmaker()() as session:
            await session.execute(
                update(MachineModel)
                .where(MachineModel.workspace_id == UUID(workspace))
                .values(last_heartbeat_at=None)
            )
            await session.commit()
            rows = (
                await session.execute(
                    select(MachineModel.last_heartbeat_at).where(
                        MachineModel.workspace_id == UUID(workspace)
                    )
                )
            ).scalars().all()
        assert rows == [None]

        assert await _alive(agent["id"]) is False
