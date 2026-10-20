"""Skill dựng sẵn không hiện ở đâu cả (spec 003 FR-123, SC-108).

Người chủ chốt 2026-10-12: skill để agent làm việc được với hệ thống là thứ hệ thống **tự gắn**,
không phải thứ để người dùng xem hay chọn, nên ẩn hết — kể cả thư viện skill. Agent vẫn nhận nó
ở mọi lượt chạy, theo đường riêng (`builtins_for`); bài ấy ở `test_claim_carries_skills.py`.

Lọc ở **cửa**, không ở màn hình: màn nào mới mà quên lọc thì lộ lại, còn cửa thì mọi màn đi qua.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from armarius.infrastructure.database.engine import get_sessionmaker, init_db
from armarius.infrastructure.database.models import MariusModel
from armarius.main import app
from tests.support.machines import LinkedMachine, link_machine


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _builtin_ids(workspace_id: str) -> set[str]:
    found = await app.state.container.skills.builtins_for(UUID(workspace_id))
    assert found, "không gian làm việc nào cũng được gieo skill dựng sẵn — phép thử hỏng"
    return {str(one.id) for one in found}


async def _a_skill_of_their_own(c: AsyncClient, m: LinkedMachine) -> str:
    made = await c.post(
        f"/v1/workspaces/{m.workspace_id}/skills/manual",
        headers=m.headers,
        json={"name": "Viết báo cáo", "description": "Cách viết một báo cáo ngắn."},
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


async def test_the_skill_library_lists_only_what_people_added() -> None:
    async with _client() as c:
        m = await link_machine(c, "library-hides-builtins@armarius.dev")
        own = await _a_skill_of_their_own(c, m)

        listed = await c.get(f"/v1/workspaces/{m.workspace_id}/skills", headers=m.headers)
        assert listed.status_code == 200, listed.text
        ids = {s["id"] for s in listed.json()}
        assert ids == {own}, listed.json()
        assert not ids & await _builtin_ids(m.workspace_id)


async def test_a_built_in_reads_as_missing_however_it_is_asked_for() -> None:
    async with _client() as c:
        m = await link_machine(c, "builtin-is-missing@armarius.dev")
        builtin = next(iter(await _builtin_ids(m.workspace_id)))
        at = f"/v1/workspaces/{m.workspace_id}/skills/{builtin}"

        for asked in (
            await c.get(at, headers=m.headers),
            await c.put(at, headers=m.headers, json={"files": {"SKILL.md": "x"}}),
            await c.delete(at, headers=m.headers),
        ):
            assert asked.status_code == 404, asked.text
            assert asked.json()["code"] == "skill_not_found"

        # Không bị xoá, không bị sửa: nó vẫn đi tới mọi lượt chạy.
        assert builtin in await _builtin_ids(m.workspace_id)


async def test_an_agent_made_with_a_built_in_keeps_only_the_skills_a_person_chose() -> None:
    """Client cũ còn gửi id dựng sẵn thì không sai gì — chỉ thừa — nên bỏ đi chứ không từ chối."""
    async with _client() as c:
        m = await link_machine(c, "create-drops-builtin@armarius.dev")
        own = await _a_skill_of_their_own(c, m)
        builtin = next(iter(await _builtin_ids(m.workspace_id)))

        created = await c.post(
            f"/v1/workspaces/{m.workspace_id}/mariuses",
            headers=m.headers,
            json={
                "name": "Cassia",
                "workplace_id": m.workplace_id,
                "skill_ids": [builtin, own],
                "skills": ["Talking to Armarius", "Viết báo cáo"],
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["skill_ids"] == [own]
        assert created.json()["skills"] == ["Viết báo cáo"]


async def test_editing_an_agent_cannot_put_a_built_in_back_on_its_list() -> None:
    async with _client() as c:
        m = await link_machine(c, "update-drops-builtin@armarius.dev")
        own = await _a_skill_of_their_own(c, m)
        builtin = next(iter(await _builtin_ids(m.workspace_id)))
        created = await c.post(
            f"/v1/workspaces/{m.workspace_id}/mariuses",
            headers=m.headers,
            json={"name": "Decima", "workplace_id": m.workplace_id},
        )
        agent = created.json()["id"]

        edited = await c.patch(
            f"/v1/workspaces/{m.workspace_id}/mariuses/{agent}",
            headers=m.headers,
            json={"skill_ids": [own, builtin]},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["skill_ids"] == [own]


async def test_installing_skills_leaves_built_ins_out_including_one_already_on_the_list() -> None:
    """Một agent cũ có id dựng sẵn trên danh sách (người từng bấm chọn chip trước 2026-09-06):
    lần cài kế tiếp dọn nó đi, chứ không chép nó sang danh sách mới."""
    async with _client() as c:
        m = await link_machine(c, "install-drops-builtin@armarius.dev")
        own = await _a_skill_of_their_own(c, m)
        builtin = next(iter(await _builtin_ids(m.workspace_id)))
        created = await c.post(
            f"/v1/workspaces/{m.workspace_id}/mariuses",
            headers=m.headers,
            json={"name": "Nona", "workplace_id": m.workplace_id},
        )
        agent = created.json()["id"]
        async with get_sessionmaker()() as session:
            await session.execute(
                update(MariusModel)
                .where(MariusModel.id == UUID(agent))
                .values(skill_ids=[builtin], skills=["Talking to Armarius"])
            )
            await session.commit()

        installed = await c.post(
            f"/v1/workspaces/{m.workspace_id}/mariuses/{agent}/install-skills",
            headers=m.headers,
            json={"skill_ids": [own, builtin]},
        )
        assert installed.status_code == 200, installed.text
        assert installed.json()["skill_ids"] == [own]

        directory = await c.get(f"/v1/workspaces/{m.workspace_id}/mariuses", headers=m.headers)
        shown = next(a for a in directory.json() if a["id"] == agent)
        assert shown["skill_ids"] == [own]
        assert shown["skills"] == ["Viết báo cáo"]


async def test_a_skill_of_their_own_named_like_a_built_in_keeps_its_name() -> None:
    """Bắt ở review #289: lọc tên bằng cách so chuỗi thì skill riêng trùng tên skill dựng sẵn
    giữ được id mà mất tên — hai danh sách không còn nói cùng một điều. Tên phải được dựng lại
    từ những id còn giữ, như `_forget_everywhere` vẫn làm."""
    async with _client() as c:
        m = await link_machine(c, "same-name-as-builtin@armarius.dev")
        builtin = next(iter(await _builtin_ids(m.workspace_id)))
        same = await c.post(
            f"/v1/workspaces/{m.workspace_id}/skills/manual",
            headers=m.headers,
            json={"name": "Talking to Armarius", "description": "của riêng người chủ"},
        )
        assert same.status_code == 201, same.text
        own = same.json()["id"]

        created = await c.post(
            f"/v1/workspaces/{m.workspace_id}/mariuses",
            headers=m.headers,
            json={
                "name": "Aurel",
                "workplace_id": m.workplace_id,
                "skill_ids": [builtin, own],
                "skills": ["Talking to Armarius", "Talking to Armarius"],
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["skill_ids"] == [own]
        assert created.json()["skills"] == ["Talking to Armarius"]

        # Không có id dựng sẵn nào để bỏ thì không gì bị đụng tới, kể cả cái tên trùng ấy.
        untouched = await c.post(
            f"/v1/workspaces/{m.workspace_id}/mariuses",
            headers=m.headers,
            json={
                "name": "Tullia",
                "workplace_id": m.workplace_id,
                "skill_ids": [own],
                "skills": ["Talking to Armarius"],
            },
        )
        assert untouched.status_code == 201, untouched.text
        assert untouched.json()["skill_ids"] == [own]
        assert untouched.json()["skills"] == ["Talking to Armarius"]
