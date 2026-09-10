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

#: Kỹ năng có sẵn của mọi workspace — tờ hướng dẫn agent nói lại với Armarius.
BUILTIN = "armarius-http"


def chosen(packet: dict) -> list[str]:
    """Những kỹ năng **người chủ chọn**, theo thứ tự đi xuống.

    Kỹ năng có sẵn đi cùng mọi gói việc dù không ai chọn (2026-09-06), nên gạt nó ra là cách
    duy nhất để các bài dưới đây còn hỏi đúng câu chúng sinh ra để hỏi. Chính luật mới thì có
    bài riêng của nó.
    """
    return [s["name"] for s in packet["skills"] if s["name"] != BUILTIN]


# ── whole, and in the packet ──────────────────────────────────────────────────


async def test_the_packet_carries_the_skill_whole() -> None:
    """Mọi tệp của kỹ năng đi cùng gói việc, không phải một danh sách để đi lấy sau."""
    async with _client() as c:
        box = await link_machine(c, "skills-whole@armarius.dev")
        skill = await _skill(c, box, name="Cookbook", files=COOKBOOK)
        agent = await _agent(c, box, name="Marin", skill_ids=[skill["id"]])

        packet = await _claim_for(c, box, agent)

        assert chosen(packet) == [skill["slug"]]
        mine = next(s for s in packet["skills"] if s["name"] == skill["slug"])
        assert mine["files"] == COOKBOOK


async def test_an_agent_nobody_chose_a_skill_for_still_gets_the_sheet_it_needs() -> None:
    """Không chọn gì thì vẫn nhận tờ hướng dẫn giao thức — nó không phải một lựa chọn.

    Bài này thay một bài cũ khẳng định *không chọn gì thì nhận về rỗng*, và câu ấy đã sai từ
    lúc nó được viết chứ không phải sai từ hôm nay: chính thông điệp đi cùng gói việc này bảo
    agent *use your Armarius tools*, còn bộ công cụ ấy do daemon bơm vào mỗi lượt chạy. Một
    agent không có tờ hướng dẫn là một agent được đưa lệnh gọi tên những thứ không ai giải
    thích — và tới 2026-09-06 thì việc nó có đọc được hay không phụ thuộc vào việc có ai bấm
    đúng một cái chip trên giao diện.
    """
    async with _client() as c:
        box = await link_machine(c, "skills-none@armarius.dev")
        agent = await _agent(c, box, name="Marin", skill_ids=[])

        packet = await _claim_for(c, box, agent)

        assert [s["name"] for s in packet["skills"]] == [BUILTIN]
        assert chosen(packet) == []
        # Và nó tới **nguyên vẹn**, không phải một cái tên rỗng ruột.
        sheet = packet["skills"][0]["files"]
        assert "SKILL.md" in sheet
        assert "armarius help" in sheet["SKILL.md"]


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

        assert chosen(packet) == [mine["slug"]]


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

        assert chosen(packet) == [first["slug"], second["slug"]]


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

        assert chosen(packet) == [good["slug"]]


# ── và thôi đi theo, khi người chủ bỏ nó ra ───────────────────────────────────


async def test_a_skill_taken_off_an_agent_stops_riding_its_work() -> None:
    """Bỏ một kỹ năng khỏi agent thì gói việc **lượt sau** ngừng chở nó (T170, FR-007m).

    Nửa *trao* đã có năm bài ở trên. Nửa *thôi trao* mới có từ 2026-09-08, và cho tới bài này
    thứ duy nhất đo được nó là danh sách máy chủ trả về — mà danh sách trả về không phải thứ
    chạy trên máy người dùng. Gói việc mới là. Một kỹ năng đã bỏ mà vẫn được ghi xuống thư mục
    làm việc ở lượt kế tiếp thì agent vẫn đọc nó, và người chủ không có cách nào biết.

    Không có cửa riêng cho từng kỹ năng: bỏ là **gửi lại cả danh sách ngắn hơn**, vì cả danh
    sách mới nói được *đúng những cái này, không cái nào khác*.
    """
    async with _client() as c:
        box = await link_machine(c, "skills-removed@armarius.dev")
        cookbook = await _skill(c, box, name="Cookbook", files=COOKBOOK)
        pantry = await _skill(
            c, box, name="Pantry", files={"SKILL.md": "---\nname: pantry\n---\n\n# Pantry\n"}
        )
        agent = await _agent(
            c, box, name="Marin", skill_ids=[cookbook["id"], pantry["id"]]
        )

        # Trước khi bỏ: cả hai đi cùng gói việc.
        before = await _claim_for(c, box, agent)
        assert sorted(chosen(before)) == sorted([cookbook["slug"], pantry["slug"]]), before

        # Trả lượt ấy lại trước khi xin lượt sau. Máy này nhận một việc một lúc, nên một lượt
        # bị bỏ lửng ở trạng thái *đang cầm* làm mọi lần xin sau trả về rỗng — và một gói việc
        # rỗng thì bài kiểm nào cũng "đạt", vì kỹ năng đã bỏ đúng là không có trong đó.
        done = await c.post(
            f"/daemon/runs/{before['run_id']}/finish",
            json={"status": "completed"},
            headers=auth(box.token),
        )
        assert done.status_code == 200, done.text

        taken_off = await c.patch(
            f"/v1/workspaces/{box.workspace_id}/mariuses/{agent['id']}",
            json={"skill_ids": [cookbook["id"]]},
            headers=box.headers,
        )
        assert taken_off.status_code == 200, taken_off.text

        # Sau khi bỏ: lượt kế tiếp chỉ chở cái còn lại — và chở nó **nguyên vẹn**, nên đây không
        # phải một gói việc rỗng đọc nhầm thành đúng.
        after = await _claim_for(c, box, agent)
        assert chosen(after) == [cookbook["slug"]], after
        assert pantry["slug"] not in [s["name"] for s in after["skills"]], after
        kept = next(s for s in after["skills"] if s["name"] == cookbook["slug"])
        assert kept["files"] == COOKBOOK
