"""Đưa một đầu việc tới sát cửa *xong* — tức đang *chờ rà soát* và đã có thành phẩm.

Câu chuyện 3 soi khâu **ký**, nên mọi bài kiểm của nó đều bắt đầu từ cùng một chỗ: việc đã
làm xong, thành phẩm đã nộp, chỉ còn chờ chữ ký. Diễn lại quãng đường đó trong từng bài
kiểm là kiểm vòng đời đầu việc mười lần và kiểm cái đang xét đúng một lần.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.support.planning import OperatingProject


async def task_awaiting_acceptance(
    c: AsyncClient,
    p: OperatingProject,
    *,
    title: str = "Kết xuất báo cáo tháng",
    plan_item_index: int = 0,
    criteria: list[str] | None = None,
) -> str:
    """Tạo đầu việc trong khuôn kế hoạch, giao cho thợ, làm tới nơi, nộp thành phẩm và
    đẩy sang *chờ rà soát*. Trả về mã đầu việc.

    `criteria` đặt bộ tiêu chí công nhận ngay sau khi tạo — phải là ở đó, vì máy chủ khoá
    bộ tiêu chí lại từ lúc thợ bắt tay (FR-019). Bỏ trống thì đầu việc đi tới cửa *xong*
    mà không có thước nào, đúng như phần lớn bài kiểm cũ vẫn làm.
    """
    created = await c.post(
        f"/agent/projects/{p.project_id}/tasks",
        headers=p.leader_headers,
        json={
            "title": title,
            "description": "Gom số liệu tháng rồi kết xuất ra tệp bảng tính.",
            "assignee_marius_id": p.worker_id,
            "plan_item_id": p.item_id(plan_item_index),
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    if criteria:
        written = await c.put(
            f"/v1/tasks/{task_id}/criteria",
            headers=p.headers,
            json={"items": [{"text": text} for text in criteria]},
        )
        assert written.status_code == 200, written.text

    moved = await c.post(
        f"/v1/tasks/{task_id}/status", headers=p.headers, json={"status": "in_progress"}
    )
    assert moved.status_code == 200, moved.text

    published = await c.post(
        f"/v1/tasks/{task_id}/artifacts",
        headers=p.headers,
        json={"name": "bao-cao.csv", "kind": "file", "content": "thang,doanh-thu\n7,100"},
    )
    assert published.status_code == 201, published.text

    review = await c.post(
        f"/v1/tasks/{task_id}/status", headers=p.headers, json={"status": "in_review"}
    )
    assert review.status_code == 200, review.text
    return str(task_id)
