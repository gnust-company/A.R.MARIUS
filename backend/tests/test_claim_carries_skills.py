"""Kỹ năng đi xuống trong gói việc, và chỉ của đúng agent ấy (T058, FR-011b, FR-007b).

Đây là chỗ kế thừa nguyên flow Multica. Đường cũ — agent tự gọi về lấy kỹ năng rồi tự ghi —
bỏ vì ba lý do, và lý do nặng nhất không phải là tốn một lượt gọi: nó **không bảo đảm được
kỹ năng đã sẵn sàng trước khi agent đọc dòng đầu tiên**. Một agent bắt đầu đọc trong lúc kỹ
năng còn đang trên đường là một agent làm việc thiếu đúng thứ nó vừa được cấp.

Vì sao phải là *chỉ của agent ấy*: một chỗ làm phục vụ nhiều agent (FR-007a). Gom kỹ năng
theo chỗ làm là gom cả kỹ năng của agent bên cạnh — đúng thứ FR-007b cấm, và cấm ở tầng ghi
tệp thì đã muộn, vì tầng ấy chỉ thấy một danh sách và không còn biết nó của ai.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import LinkedMachine, auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _skill(
    c: AsyncClient, box: LinkedMachine, *, name: str, files: dict[str, str]
) -> dict:
    """One workspace skill with a file tree the patron wrote."""
    made = await c.post(
        f"/v1/workspaces/{box.workspace_id}/skills/manual",
        json={"name": name, "description": ""},
        headers=box.headers,
    )
    assert made.status_code == 201, made.text
    skill = made.json()
    saved = await c.put(
        f"/v1/workspaces/{box.workspace_id}/skills/{skill['id']}",
        json={"files": files},
        headers=box.headers,
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


async def _agent(
    c: AsyncClient, box: LinkedMachine, *, name: str, skill_ids: list[str]
) -> dict:
    return await invite_agent(
        c,
        box.workspace_id,
        box.headers,
        name=name,
        workplace_id=box.workplace_id,
        instructions="Do the job.",
        skill_ids=skill_ids,
    )


async def _claim_for(c: AsyncClient, box: LinkedMachine, agent: dict) -> dict:
    """Shelve one run for this agent and take it, returning the whole packet."""
    project_id = await a_project(box.workspace_id)
    task_id = await a_task(project_id, assigned_to=agent["id"])
    run_id = await shelve(marius_id=agent["id"], task_id=task_id)
    answered = await c.post(
        "/daemon/runs/claim",
        json={"workplace_ids": [box.workplace_id], "max": 1},
        headers=auth(box.token),
    )
    assert answered.status_code == 200, answered.text
    runs = answered.json()["runs"]
    assert [r["run_id"] for r in runs] == [str(run_id)], answered.text
    return runs[0]


COOKBOOK = {
    "SKILL.md": "---\nname: cookbook\ndescription: How we cook\n---\n\n# Cookbook\n",
    "ref/stock.md": "Simmer for six hours.\n",
}


# ── whole, and in the packet ──────────────────────────────────────────────────


async def test_the_packet_carries_the_skill_whole() -> None:
    """Mọi tệp của kỹ năng đi cùng gói việc, không phải một danh sách để đi lấy sau."""
    async with _client() as c:
        box = await link_machine(c, "skills-whole@armarius.dev")
        skill = await _skill(c, box, name="Cookbook", files=COOKBOOK)
        agent = await _agent(c, box, name="Marin", skill_ids=[skill["id"]])

        packet = await _claim_for(c, box, agent)

        assert [s["name"] for s in packet["skills"]] == [skill["slug"]]
        assert packet["skills"][0]["files"] == COOKBOOK


async def test_an_agent_with_no_skills_is_given_none() -> None:
    """Không có kỹ năng nào là một câu trả lời, không phải một lỗi."""
    async with _client() as c:
        box = await link_machine(c, "skills-none@armarius.dev")
        agent = await _agent(c, box, name="Marin", skill_ids=[])

        packet = await _claim_for(c, box, agent)

        assert packet["skills"] == []


async def test_one_agents_skills_never_ride_another_agents_work() -> None:
    """Hai agent chung một chỗ làm vẫn là hai bộ kỹ năng tách bạch (FR-007a, FR-007b)."""
    async with _client() as c:
        box = await link_machine(c, "skills-apart@armarius.dev")
        mine = await _skill(c, box, name="Cookbook", files=COOKBOOK)
        theirs = await _skill(
            c, box, name="Ledger", files={"SKILL.md": "---\nname: ledger\n---\n"}
        )
        marin = await _agent(c, box, name="Marin", skill_ids=[mine["id"]])
        await _agent(c, box, name="Otto", skill_ids=[theirs["id"]])

        packet = await _claim_for(c, box, marin)

        assert [s["name"] for s in packet["skills"]] == [mine["slug"]]


async def test_the_skills_arrive_in_the_order_they_were_granted() -> None:
    """Thứ tự người chủ cấp là thứ tự đi xuống — không xáo lại theo tên hay theo ngày."""
    async with _client() as c:
        box = await link_machine(c, "skills-order@armarius.dev")
        first = await _skill(c, box, name="Zephyr", files={"SKILL.md": "z\n"})
        second = await _skill(c, box, name="Anvil", files={"SKILL.md": "a\n"})
        agent = await _agent(
            c, box, name="Marin", skill_ids=[first["id"], second["id"]]
        )

        packet = await _claim_for(c, box, agent)

        assert [s["name"] for s in packet["skills"]] == [
            first["slug"],
            second["slug"],
        ]


# ── and nothing that could be written outside its own directory ───────────────


@pytest.mark.parametrize(
    "escape",
    ["../../../etc/evil", "/etc/evil", "ref/../../evil", "..", "ref\\..\\..\\evil"],
    ids=["climbs", "absolute", "climbs-mid-path", "bare-dots", "backslash"],
)
async def test_a_skill_that_could_write_outside_its_own_directory_is_refused(
    escape: str,
) -> None:
    """Đường dẫn thoát ra ngoài thư mục kỹ năng thì cả gói ấy bị từ chối.

    Từ chối cả kỹ năng chứ không phải bỏ riêng tệp hỏng: cây tệp của một kỹ năng do người
    gõ vào hoặc kéo về từ một kho ngoài, nên đây là dữ liệu từ bên ngoài. Bỏ lẻ một tệp thì
    agent đọc một SKILL.md mà những tệp nó nhắc tới đã lặng lẽ biến mất — tệ hơn là không
    có kỹ năng ấy.
    """
    async with _client() as c:
        box = await link_machine(c, f"skills-escape-{abs(hash(escape))}@armarius.dev")
        bad = await _skill(
            c, box, name="Cookbook", files={**COOKBOOK, escape: "whatever"}
        )
        good = await _skill(c, box, name="Ledger", files={"SKILL.md": "l\n"})
        agent = await _agent(c, box, name="Marin", skill_ids=[bad["id"], good["id"]])

        packet = await _claim_for(c, box, agent)

        assert [s["name"] for s in packet["skills"]] == [good["slug"]]
