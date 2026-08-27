"""Xoá một kỹ năng là xoá cả những chỗ còn gọi tên nó (T125, FR-011c).

Trước đợt này, xoá một kỹ năng chỉ xoá cái hàng. Cái ở lại là mối nối trên agent — một mã
trong danh sách, một cái tên nằm cạnh, một dòng trong sổ đã-cài — trỏ vào chỗ trống. Không
gì đổ vỡ, và đó đúng là lý do nó chất lên: chỗ nào dịch mã ra kỹ năng cũng lặng lẽ bỏ qua mã
không tìm thấy. Cái giá phải trả là hai danh sách thôi khớp nhau về số lượng, và cuốn sổ vẫn
khai một agent đã cài thứ không còn trong cửa hàng.

Hai đường xoá, một luật. Người chủ xoá kỹ năng mình tự làm là một; một mục gieo sẵn bị rút
khỏi danh sách rồi bị vòng gieo dọn đi là hai. Đường nào cũng phải để lại đúng một trạng
thái: **không còn chỗ nào nhắc tới nó nữa.**

Phần dữ liệu đã nằm sẵn trong cơ sở dữ liệu từ những đợt trước — `armarius-onboarder`, rồi
`armarius-mcp` — thuộc về bản di trú, và có bài kiểm riêng ở cuối tệp này chạy trên chuỗi di
trú thật.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from armarius.infrastructure.persistence.unit_of_work import make_uow
from armarius.main import app
from tests.support.agents import invite_agent

pytestmark = pytest.mark.anyio

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    ws = await c.get("/v1/workspaces", headers=h)
    return h, ws.json()[0]["id"]


async def _agent_row(marius_id: str):
    async with make_uow() as uow:
        return await uow.mariuses.get(uuid.UUID(marius_id))


# ── 1. the owner deletes a skill they made ────────────────────────────────────


async def test_deleting_a_skill_takes_it_off_every_agent_that_had_it() -> None:
    async with _client() as c:
        h, ws_id = await _register(c, "forget-agent@armarius.dev")
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        keeper_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")
        made = await c.post(
            f"/v1/workspaces/{ws_id}/skills/manual",
            headers=h,
            json={"name": "Bảng màu", "description": "owner's own"},
        )
        doomed_id = made.json()["id"]

        agent = await invite_agent(
            c, ws_id, h, name="Marin", skill_ids=[keeper_id, doomed_id]
        )
        await c.post(
            f"/v1/workspaces/{ws_id}/mariuses/{agent['id']}/install-skills",
            headers=h,
            json={"skill_ids": [doomed_id]},
        )
        before = await _agent_row(agent["id"])
        assert doomed_id in before.skill_ids

        gone = await c.delete(
            f"/v1/workspaces/{ws_id}/skills/{doomed_id}", headers=h
        )
        assert gone.status_code in (200, 204), gone.text

        after = await _agent_row(agent["id"])
    assert after.skill_ids == [keeper_id], after.skill_ids
    assert after.skills == ["Armarius HTTP API"], after.skills


# The two lists are one fact written twice, and they have to stay that way. A name left
# beside no id is a pill on the screen for a skill the agent is not linked to.
async def test_the_names_left_behind_are_exactly_the_ids_left_behind() -> None:
    async with _client() as c:
        h, ws_id = await _register(c, "forget-names@armarius.dev")
        made = await c.post(
            f"/v1/workspaces/{ws_id}/skills/manual",
            headers=h,
            json={"name": "Bảng màu", "description": "owner's own"},
        )
        doomed_id = made.json()["id"]
        agent = await invite_agent(c, ws_id, h, name="Marin", skill_ids=[doomed_id])

        await c.delete(f"/v1/workspaces/{ws_id}/skills/{doomed_id}", headers=h)

        after = await _agent_row(agent["id"])
    assert after.skill_ids == []
    assert after.skills == []


# A skill nobody was linked to is deleted without disturbing anybody who was linked to
# something else. The repair has to be about the skill that went, not about every link.
async def test_deleting_one_skill_does_not_disturb_another_agents_links() -> None:
    async with _client() as c:
        h, ws_id = await _register(c, "forget-others@armarius.dev")
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        keeper_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")
        made = await c.post(
            f"/v1/workspaces/{ws_id}/skills/manual",
            headers=h,
            json={"name": "Bảng màu", "description": "owner's own"},
        )
        doomed_id = made.json()["id"]
        untouched = await invite_agent(c, ws_id, h, name="Khác")
        # Through the linking route, so this agent has all three lists filled in — an
        # agent with empty lists would be undisturbed by anything and prove nothing.
        await c.post(
            f"/v1/workspaces/{ws_id}/mariuses/{untouched['id']}/install-skills",
            headers=h,
            json={"skill_ids": [keeper_id]},
        )

        await c.delete(f"/v1/workspaces/{ws_id}/skills/{doomed_id}", headers=h)

        after = await _agent_row(untouched["id"])
    assert after.skill_ids == [keeper_id]
    assert after.skills == ["Armarius HTTP API"]


# ── 2. a built-in that stops being shipped ────────────────────────────────────


# The other door into the same state. A de-listed built-in is deleted by the seeding pass,
# not by anybody asking for it, so the repair has to hang off the deletion rather than off
# the request that caused it.
async def test_a_builtin_that_stops_shipping_is_forgotten_the_same_way() -> None:
    from armarius.domain.entities.skill import Skill
    from armarius.shared.clock import utcnow

    async with _client() as c:
        h, ws_id = await _register(c, "forget-builtin@armarius.dev")
        async with make_uow() as uow:
            retired = Skill(
                workspace_id=uuid.UUID(ws_id),
                slug="armarius-onboarder",
                name="Armarius Onboarder",
                description="retired playbook",
                source="builtin",
                source_url="/static/skills/armarius-onboarder/SKILL.md",
                files={"SKILL.md": "old"},
                created_at=utcnow(),
            )
            await uow.skills.add(retired)
            await uow.commit()
        retired_id = str(retired.id)
        agent = await invite_agent(c, ws_id, h, name="Marin", skill_ids=[retired_id])

        # Reading the Shop is what triggers the seeding pass, and the prune inside it.
        await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)

        after = await _agent_row(agent["id"])
    assert after.skill_ids == [], after.skill_ids
    assert after.skills == [], after.skills


# ── 3. the generation already in the database ─────────────────────────────────

BEFORE = "e4c9f7b21a63"  # ngay trước bản dọn
# Và chính bản dọn. Ba bài dưới đây nâng cấp tới **đúng bản này**, không tới `head`: chúng hỏi
# một câu về một bản di trú cụ thể chạy trên dữ liệu thật, nên chạy hết cả chuỗi chỉ khiến
# chúng đỏ mỗi lần một bản di trú *sau* đó đụng vào cùng cái cột — như bản gỡ
# `mariuses.skill_installs` ở đợt daemon (T062), thứ chẳng liên quan gì tới điều đang hỏi.
CLEANUP = "a1b7d3f95c28"


def _alembic(db_file: Path, target: str) -> None:
    run = subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND_ROOT,
        env=os.environ | {"DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert run.returncode == 0, run.stderr or run.stdout


LIVE = uuid.uuid4()
DEAD = uuid.uuid4()
AGENT = uuid.uuid4()
ROLE = uuid.uuid4()
NEIGHBOUR_SKILL = uuid.uuid4()
NEIGHBOUR_AGENT = uuid.uuid4()


def _seed(db_file: Path) -> None:
    """Một workspace như đêm trước khi nâng cấp: một kỹ năng còn, một mã đã mồ côi."""
    engine = create_engine(f"sqlite:///{db_file}")
    workspace, user, project = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as cx:
            cx.execute(
                text(
                    "INSERT INTO users (id, email, username, full_name, "
                    "hashed_password, role, is_active, is_verified) "
                    "VALUES (:i, 'old@example.com', 'old', 'Old', 'x', 'patron', 1, 1)"
                ),
                {"i": str(user)},
            )
            cx.execute(
                text(
                    "INSERT INTO workspaces (id, name, slug, owner_user_id) "
                    "VALUES (:i, 'WS', 'ws', :u)"
                ),
                {"i": str(workspace), "u": str(user)},
            )
            cx.execute(
                text(
                    "INSERT INTO projects (id, workspace_id, name, slug, status, "
                    "next_task_seq) VALUES (:i, :w, 'P', 'p', 'operating', 1)"
                ),
                {"i": str(project), "w": str(workspace)},
            )
            cx.execute(
                text(
                    "INSERT INTO skills (id, workspace_id, slug, name, description, "
                    "source, source_url, files) VALUES "
                    "(:i, :w, 'armarius-http', 'Armarius HTTP API', '', 'builtin', '', '{}')"
                ),
                {"i": str(LIVE), "w": str(workspace)},
            )
            cx.execute(
                text(
                    "INSERT INTO mariuses (id, workspace_id, name, role, skills, "
                    "skill_ids, skill_installs, adapter_type, adapter_config, liveness) "
                    "VALUES (:i, :w, 'Marin', '', :names, :ids, :installs, 'echo', "
                    "'{}', 'offline')"
                ),
                {
                    "i": str(AGENT),
                    "w": str(workspace),
                    # Both lists carry the dead one, exactly as the old delete path left it.
                    "names": json.dumps(["Armarius HTTP API", "Armarius MCP"]),
                    "ids": json.dumps([str(LIVE), str(DEAD)]),
                    "installs": json.dumps(
                        {"armarius-http": "installed", "armarius-mcp": "installed"}
                    ),
                },
            )
            cx.execute(
                text(
                    "INSERT INTO roles (id, project_id, key, title, seats, is_leader, "
                    "description, skill_ids) VALUES "
                    "(:i, :p, 'backend', 'Backend', 1, 0, 'Lo máy chủ.', :ids)"
                ),
                {"i": str(ROLE), "p": str(project), "ids": json.dumps([str(DEAD)])},
            )
    finally:
        engine.dispose()


def _seed_neighbour(db_file: Path) -> None:
    """Một workspace thứ hai, có một kỹ năng **còn sống** trùng slug với cái đã chết ở kia.

    Slug chỉ duy nhất trong một workspace. Hai nơi cùng đặt tên "armarius-mcp" là hai kỹ
    năng khác nhau, và cái còn sống ở đây không được phép giữ cho cái đã chết ở bên kia
    khỏi bị dọn.
    """
    engine = create_engine(f"sqlite:///{db_file}")
    workspace, user = uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as cx:
            cx.execute(
                text(
                    "INSERT INTO users (id, email, username, full_name, "
                    "hashed_password, role, is_active, is_verified) "
                    "VALUES (:i, 'next@example.com', 'next', 'Next', 'x', "
                    "'patron', 1, 1)"
                ),
                {"i": str(user)},
            )
            cx.execute(
                text(
                    "INSERT INTO workspaces (id, name, slug, owner_user_id) "
                    "VALUES (:i, 'WS2', 'ws2', :u)"
                ),
                {"i": str(workspace), "u": str(user)},
            )
            cx.execute(
                text(
                    "INSERT INTO skills (id, workspace_id, slug, name, description, "
                    "source, source_url, files) VALUES "
                    "(:i, :w, 'armarius-mcp', 'Armarius MCP', '', 'manual', '', '{}')"
                ),
                {"i": str(NEIGHBOUR_SKILL), "w": str(workspace)},
            )
            cx.execute(
                text(
                    "INSERT INTO mariuses (id, workspace_id, name, role, skills, "
                    "skill_ids, skill_installs, adapter_type, adapter_config, liveness) "
                    "VALUES (:i, :w, 'Hàng xóm', '', :names, :ids, :installs, 'echo', "
                    "'{}', 'offline')"
                ),
                {
                    "i": str(NEIGHBOUR_AGENT),
                    "w": str(workspace),
                    "names": json.dumps(["Armarius MCP"]),
                    "ids": json.dumps([str(NEIGHBOUR_SKILL)]),
                    "installs": json.dumps({"armarius-mcp": "installed"}),
                },
            )
    finally:
        engine.dispose()


def _rows(db_file: Path):
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as cx:
            agent = cx.execute(
                text(
                    "SELECT skill_ids, skills, skill_installs FROM mariuses WHERE id = :i"
                ),
                {"i": str(AGENT)},
            ).one()
            role = cx.execute(
                text("SELECT skill_ids FROM roles WHERE id = :i"), {"i": str(ROLE)}
            ).one()
    finally:
        engine.dispose()
    return agent, role


def test_the_upgrade_clears_the_links_earlier_deletions_left_behind(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "forget-skills.db"
    _alembic(db_file, BEFORE)
    _seed(db_file)

    _alembic(db_file, CLEANUP)

    agent, role = _rows(db_file)
    assert json.loads(agent[0]) == [str(LIVE)], "mã kỹ năng đã chết còn nằm trên agent"
    assert json.loads(agent[1]) == ["Armarius HTTP API"], (
        "tên còn lại phải đúng bằng mã còn lại, không phải một danh sách lọc riêng"
    )
    assert json.loads(agent[2]) == {"armarius-http": "installed"}, (
        "sổ đã-cài vẫn khai một kỹ năng không còn trong cửa hàng"
    )
    assert json.loads(role[0]) == [], "mã kỹ năng đã chết còn nằm trên một vai"


def test_the_upgrade_leaves_a_workspace_that_was_already_clean_alone(
    tmp_path: Path,
) -> None:
    """Bản di trú chỉ được đụng vào thứ đã hỏng.

    Một bản dọn chạy trên dữ liệu lành mà vẫn ghi lại là một bản dọn không ai kiểm được: nó
    ghi đè bằng chính thứ nó đọc, và cái sai duy nhất nó có thể gây ra sẽ nằm im ở đó.
    """
    db_file = tmp_path / "already-clean.db"
    _alembic(db_file, BEFORE)
    _seed(db_file)
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as cx:
            cx.execute(
                text("UPDATE mariuses SET skill_ids = :ids, skills = :names, "
                     "skill_installs = :installs WHERE id = :i"),
                {
                    "ids": json.dumps([str(LIVE)]),
                    "names": json.dumps(["Armarius HTTP API"]),
                    "installs": json.dumps({"armarius-http": "installed"}),
                    "i": str(AGENT),
                },
            )
            cx.execute(
                text("UPDATE roles SET skill_ids = '[]' WHERE id = :i"),
                {"i": str(ROLE)},
            )
    finally:
        engine.dispose()

    _alembic(db_file, CLEANUP)

    agent, role = _rows(db_file)
    assert json.loads(agent[0]) == [str(LIVE)]
    assert json.loads(agent[1]) == ["Armarius HTTP API"]
    assert json.loads(agent[2]) == {"armarius-http": "installed"}
    assert json.loads(role[0]) == []


def test_a_live_slug_next_door_does_not_save_a_dead_one_here(tmp_path: Path) -> None:
    """Sổ đã-cài ghi bằng slug, mà slug chỉ duy nhất trong một workspace.

    Gộp slug của cả hệ thống thành một rổ rồi lấy đó mà lọc là đọc nhầm phạm vi: một kỹ
    năng còn sống ở workspace bên cạnh sẽ giữ nguyên cái mục mồ côi ở đây — đúng thứ bản
    di trú này sinh ra để dọn. Nên phải soi từng workspace, và soi bằng workspace của
    chính agent đó.
    """
    db_file = tmp_path / "same-slug-two-workspaces.db"
    _alembic(db_file, BEFORE)
    _seed(db_file)
    _seed_neighbour(db_file)

    _alembic(db_file, CLEANUP)

    agent, _ = _rows(db_file)
    assert json.loads(agent[2]) == {"armarius-http": "installed"}, (
        "mục mồ côi vẫn còn — một slug trùng tên ở workspace khác đã che nó lại"
    )

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as cx:
            neighbour = cx.execute(
                text(
                    "SELECT skill_ids, skills, skill_installs FROM mariuses "
                    "WHERE id = :i"
                ),
                {"i": str(NEIGHBOUR_AGENT)},
            ).one()
    finally:
        engine.dispose()
    assert json.loads(neighbour[0]) == [str(NEIGHBOUR_SKILL)]
    assert json.loads(neighbour[1]) == ["Armarius MCP"]
    assert json.loads(neighbour[2]) == {"armarius-mcp": "installed"}, (
        "kỹ năng còn sống của workspace bên cạnh bị dọn nhầm"
    )
