"""Đưa một dự án qua trọn vòng thiết lập → lập kế hoạch → vận hành, qua HTTP thật.

Câu chuyện 2 soi cổng chặn của **đầu việc**, nhưng đầu việc thật chỉ tồn tại sau khi
người chủ duyệt kế hoạch (FR-003) và "trong khuôn" chỉ có nghĩa khi đã có hạng mục được
duyệt (FR-027). Mỗi bài kiểm mà phải diễn lại toàn bộ vở đó thì hoá ra kiểm cổng kế hoạch
một trăm lần và kiểm thứ đang xét đúng một lần.

Khác với `support/projects.py` — chỗ đó ép thẳng giai đoạn ở tầng lưu trữ cho các bài kiểm
không dính gì tới kế hoạch. Ở đây ta đi đúng đường thật, vì bài kiểm cần **hạng mục kế
hoạch có thật** để trỏ vào.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from httpx import ASGITransport, AsyncClient

from tests.support.agents import invite_and_online


@dataclass
class OperatingProject:
    """Một dự án đang *vận hành* với kế hoạch đã duyệt."""

    headers: dict
    workspace_id: str
    project_id: str
    leader_token: str
    leader_id: str
    worker_id: str
    worker_token: str = ""
    plan_items: list[dict] = field(default_factory=list)

    @property
    def leader_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.leader_token}"}

    @property
    def worker_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.worker_token}"}

    def item_id(self, index: int = 0) -> str:
        return self.plan_items[index]["id"]


def client() -> AsyncClient:
    from armarius.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def register(c: AsyncClient, email: str) -> tuple[dict, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    ws = await c.get("/v1/workspaces", headers=h)
    return h, ws.json()[0]["id"]


DEFAULT_ITEMS: list[dict] = [
    {"title": "Cổng đăng nhập", "description": "Đăng nhập bằng tài khoản sẵn có", "order": 1},
    {"title": "Bảng điều khiển", "description": "Trang chính sau khi đăng nhập", "order": 2},
]


async def operating_project(
    c: AsyncClient,
    email: str,
    *,
    name: str = "Apollo",
    items: list[dict] | None = None,
) -> OperatingProject:
    """Dựng dự án, mời đủ người, Trưởng dự án trình bối cảnh và kế hoạch, người chủ duyệt."""
    h, ws_id = await register(c, email)
    created = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={
            "name": name,
            "description": "ship it",
            "objective": "Ra mắt nền tảng",
            "leader": {"description": "Điều phối dự án.", "marius_id": None},
            "roles": [{"title": "Backend", "seats": 1, "description": "Lo phần máy chủ."}],
        },
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]

    leader_id, leader_token = await invite_and_online(c, ws_id, h, name="Leader")
    worker_id, worker_token = await invite_and_online(c, ws_id, h, name="Dev")
    for marius_id, role_key in ((leader_id, "leader"), (worker_id, "backend")):
        g = await c.post(
            f"/v1/projects/{pid}/grant",
            headers=h,
            json={"role_key": role_key, "marius_id": marius_id},
        )
        assert g.status_code == 201, g.text

    ah = {"Authorization": f"Bearer {leader_token}"}
    ctx = await c.post(
        f"/agent/projects/{pid}/context",
        headers=ah,
        json={
            "objective": "Ra mắt nền tảng trong quý này",
            "background": "Đội cũ để lại một bản dựng dở.",
            "constraints": "Không đổi cơ sở dữ liệu.",
            "scope": "Chỉ phần máy chủ.",
            "principles": "Đặc tả đi trước.",
        },
    )
    assert ctx.status_code == 200, ctx.text
    approved_ctx = await c.post(
        f"/v1/projects/{pid}/context/approve", headers=h, json={"approve": True}
    )
    assert approved_ctx.status_code == 200, approved_ctx.text

    plan = await c.post(
        f"/agent/projects/{pid}/plan",
        headers=ah,
        json={
            "summary": "Hai hạng mục, hai tuần.",
            "risks": "Phụ thuộc bên thứ ba.",
            "items": items if items is not None else DEFAULT_ITEMS,
        },
    )
    assert plan.status_code == 200, plan.text
    decided = await c.post(
        f"/v1/projects/{pid}/plan/decision", headers=h, json={"decision": "duyet"}
    )
    assert decided.status_code == 200, decided.text

    detail = await c.get(f"/v1/projects/{pid}", headers=h)
    assert detail.json()["status"] == "operating", detail.text

    return OperatingProject(
        headers=h,
        workspace_id=ws_id,
        project_id=pid,
        leader_token=leader_token,
        leader_id=leader_id,
        worker_id=worker_id,
        worker_token=worker_token,
        plan_items=decided.json()["items"],
    )
