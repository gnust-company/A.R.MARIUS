"""Chấm điểm một tiêu chí công nhận (T178, FR-019, Câu chuyện 3 kịch bản 1).

Thực thể tiêu chí có sẵn hàm chấm, trường kết quả *chưa chấm / đạt / không đạt* và chỗ trỏ
sang thành phẩm làm bằng chứng — nhưng quét cả máy chủ thì **không một lời gọi nào**. Hệ
quả: bộ tiêu chí đặt ra trước khi thợ bắt tay rồi nằm im tới hết đời đầu việc, và Trưởng dự
án ký tán thành mà không đi qua nó lấy một dòng. Kịch bản 1 viết thẳng *"khi Trưởng dự án
chấm đạt hết tiêu chí"*; bước ấy không tồn tại.

Bài kiểm ở đây canh cả ba nửa của việc dựng lại bước đó: chấm được, chấm rồi mới ký được,
và số `đạt/tổng` trên bảng tự đổi ngay khi có người chấm.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from tests.support.approvals import task_awaiting_acceptance
from tests.support.planning import OperatingProject, client, operating_project

CRITERIA = ["Tệp kết xuất mở được", "Số liệu khớp sổ cái"]


async def _criteria(c: AsyncClient, p: OperatingProject, task_id: str) -> list[dict]:
    r = await c.get(f"/v1/tasks/{task_id}/criteria", headers=p.headers)
    assert r.status_code == 200, r.text
    return list(r.json())


async def _artifact_id(c: AsyncClient, p: OperatingProject, task_id: str) -> str:
    r = await c.get(f"/v1/tasks/{task_id}/artifacts", headers=p.headers)
    assert r.status_code == 200, r.text
    return str(r.json()[0]["id"])


async def _rate(
    c: AsyncClient,
    p: OperatingProject,
    task_id: str,
    criterion_id: str,
    *,
    result: str = "passed",
    evidence: str | None = None,
    headers: dict | None = None,
):
    body: dict = {"result": result}
    if evidence is not None:
        body["evidence_artifact_id"] = evidence
    return await c.post(
        f"/agent/tasks/{task_id}/criteria/{criterion_id}",
        headers=headers if headers is not None else p.leader_headers,
        json=body,
    )


async def _pass_them_all(c: AsyncClient, p: OperatingProject, task_id: str) -> None:
    evidence = await _artifact_id(c, p, task_id)
    for item in await _criteria(c, p, task_id):
        r = await _rate(c, p, task_id, item["id"], evidence=evidence)
        assert r.status_code == 200, r.text


def _frames(body: str) -> list[tuple[str, dict]]:
    """Đọc một lượt gửi bù của dòng sự kiện thành các cặp (loại tin, dữ liệu).

    Chuẩn hoá ký tự xuống dòng trước: máy chủ viết `\\r\\n`, nên cắt thẳng theo `\\n\\n`
    không tìm thấy dấu ngăn nào và gộp cả dòng tin thành một khung.
    """
    out: list[tuple[str, dict]] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        kind, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                kind = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = json.loads(line.removeprefix("data:").strip())
        if kind is not None:
            out.append((kind, data or {}))
    return out


# ── chấm được ─────────────────────────────────────────────────────────────────────


async def test_the_leader_scores_a_criterion_and_the_board_number_moves() -> None:
    """Chấm một trong hai tiêu chí → thẻ trên bảng đọc ra 1/2, và kênh dự án có lên tiếng."""
    async with client() as c:
        p = await operating_project(c, "rate-a@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p, criteria=CRITERIA)
        evidence = await _artifact_id(c, p, task_id)
        items = await _criteria(c, p, task_id)

        scored = await _rate(c, p, task_id, items[0]["id"], evidence=evidence)
        assert scored.status_code == 200, scored.text
        assert scored.json()["result"] == "passed"
        assert scored.json()["evidence_artifact_id"] == evidence

        counts = await c.get(
            f"/v1/projects/{p.project_id}/task-counts", headers=p.headers
        )
        row = next(r for r in counts.json() if r["task_id"] == task_id)
        assert (row["criteria_passed"], row["criteria_total"]) == (1, 2)

        stream = await c.get(
            f"/v1/projects/{p.project_id}/events?live=0", headers=p.headers
        )
    kinds = [kind for kind, _ in _frames(stream.text)]
    assert "task.checklist_changed" in kinds, kinds


async def test_a_criterion_can_be_marked_failed_and_then_passed_again() -> None:
    """Vòng rà soát có thể chạy hai lượt; chấm không phải là một chiều."""
    async with client() as c:
        p = await operating_project(c, "rate-b@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p, criteria=CRITERIA[:1])
        evidence = await _artifact_id(c, p, task_id)
        item = (await _criteria(c, p, task_id))[0]

        failed = await _rate(c, p, task_id, item["id"], result="failed")
        assert failed.status_code == 200, failed.text
        assert failed.json()["result"] == "failed"

        passed = await _rate(c, p, task_id, item["id"], evidence=evidence)
    assert passed.status_code == 200, passed.text
    assert passed.json()["result"] == "passed"


# ── ba lời từ chối quanh lúc chấm ─────────────────────────────────────────────────


async def test_a_pass_over_http_must_cite_an_artifact() -> None:
    async with client() as c:
        p = await operating_project(c, "rate-c@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p, criteria=CRITERIA[:1])
        item = (await _criteria(c, p, task_id))[0]
        r = await _rate(c, p, task_id, item["id"])
    assert r.status_code == 409, r.text
    assert "bằng chứng" in r.json()["detail"]


async def test_the_evidence_must_belong_to_this_task() -> None:
    """Trỏ sang thành phẩm của đầu việc khác là một trích dẫn không lần ngược được."""
    async with client() as c:
        p = await operating_project(c, "rate-d@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p, criteria=CRITERIA[:1])
        other_id = await task_awaiting_acceptance(
            c, p, title="Việc khác", plan_item_index=1
        )
        stranger = await _artifact_id(c, p, other_id)
        item = (await _criteria(c, p, task_id))[0]
        r = await _rate(c, p, task_id, item["id"], evidence=stranger)
    assert r.status_code == 404, r.text


async def test_a_criterion_is_scored_while_the_task_is_in_review() -> None:
    """Chấm đạt trước khi có đầu ra để soi thì không nói gì về đầu ra ấy."""
    async with client() as c:
        p = await operating_project(c, "rate-e@armarius.dev")
        created = await c.post(
            f"/v1/projects/{p.project_id}/tasks",
            headers=p.headers,
            json={"title": "Chưa làm", "description": "Mô tả đàng hoàng."},
        )
        task_id = created.json()["id"]
        written = await c.put(
            f"/v1/tasks/{task_id}/criteria",
            headers=p.headers,
            json={"items": [{"text": CRITERIA[0]}]},
        )
        item = written.json()[0]
        r = await _rate(c, p, task_id, item["id"], evidence=str(task_id))
    assert r.status_code == 409, r.text
    assert "chờ rà soát" in r.json()["detail"]


async def test_only_the_leader_seat_scores() -> None:
    """Thợ tự chấm đạt việc mình làm là đi thẳng qua đúng cái cổng bộ tiêu chí dựng lên."""
    async with client() as c:
        p = await operating_project(c, "rate-f@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p, criteria=CRITERIA[:1])
        evidence = await _artifact_id(c, p, task_id)
        item = (await _criteria(c, p, task_id))[0]
        r = await _rate(
            c, p, task_id, item["id"], evidence=evidence, headers=p.worker_headers
        )
    assert r.status_code == 404, r.text


async def test_a_stranger_workspace_cannot_reach_the_criteria() -> None:
    """Hiến pháp I: thẻ của vùng khác đọc ra *không tìm thấy*, kể cả ở lối đọc."""
    async with client() as c:
        p = await operating_project(c, "rate-g@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p, criteria=CRITERIA[:1])
        stranger = await operating_project(c, "rate-h@armarius.dev", name="Khác")

        read = await c.get(
            f"/agent/tasks/{task_id}/criteria", headers=stranger.leader_headers
        )
        assert read.status_code == 404, read.text

        item = (await _criteria(c, p, task_id))[0]
        wrote = await _rate(
            c, p, task_id, item["id"], evidence=str(task_id),
            headers=stranger.leader_headers,
        )
    assert wrote.status_code == 404, wrote.text


# ── chấm rồi mới ký được ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("result", ["unrated", "failed"])
async def test_no_signature_until_every_criterion_is_passed(result: str) -> None:
    """Chưa chấm và chấm không đạt chặn chữ ký như nhau — từ phía đóng việc là một điều."""
    async with client() as c:
        p = await operating_project(c, f"sign-{result}@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p, criteria=CRITERIA)
        evidence = await _artifact_id(c, p, task_id)
        items = await _criteria(c, p, task_id)

        first = await _rate(c, p, task_id, items[0]["id"], evidence=evidence)
        assert first.status_code == 200, first.text
        if result == "failed":
            second = await _rate(c, p, task_id, items[1]["id"], result="failed")
            assert second.status_code == 200, second.text

        refused = await c.post(
            f"/agent/tasks/{task_id}/approval",
            headers=p.leader_headers,
            json={"approve": True},
        )
        assert refused.status_code == 409, refused.text
        assert CRITERIA[1] in refused.json()["detail"], refused.text

        # Không được ghi chữ ký nào — từ chối sớm chứ không phải ghi rồi rút.
        signed = await c.get(f"/v1/tasks/{task_id}/approvals", headers=p.headers)
        assert signed.json() == [], signed.text

        fixed = await _rate(c, p, task_id, items[1]["id"], evidence=evidence)
        assert fixed.status_code == 200, fixed.text
        accepted = await c.post(
            f"/agent/tasks/{task_id}/approval",
            headers=p.leader_headers,
            json={"approve": True},
        )
    assert accepted.status_code == 200, accepted.text


async def test_a_rejection_needs_no_scores() -> None:
    """Trả lại là nói *chưa đạt*; bắt chấm đủ trước khi được nói thế là bắt ngược."""
    async with client() as c:
        p = await operating_project(c, "sign-reject@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p, criteria=CRITERIA)
        sent_back = await c.post(
            f"/agent/tasks/{task_id}/approval",
            headers=p.leader_headers,
            json={"approve": False, "reason": "thiếu cột doanh thu"},
        )
    assert sent_back.status_code == 200, sent_back.text
    assert sent_back.json()["status"] == "in_progress", sent_back.text


async def test_the_patron_signature_is_refused_too_when_the_yardstick_is_not_met() -> None:
    """Nửa thứ hai của cổng, dựng lại bằng dữ liệu cũ.

    Qua lối đi thật thì không tới được đây: chữ ký Trưởng dự án đã đòi chấm đủ. Nhưng một
    đầu việc đã ký từ trước khi có luật này thì tới được — và nếu chỉ chặn ở lúc *đóng*,
    chữ ký người chủ vẫn ghi vào rồi bước chuyển sau đó mới vỡ, để lại một đầu việc mang
    đủ hai chữ ký mà nằm mãi ở *chờ rà soát*.
    """
    from armarius.domain.entities.checklist_item import AcceptanceResult
    from armarius.main import app

    async with client() as c:
        p = await operating_project(c, "sign-legacy@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p, criteria=CRITERIA[:1])
        await _pass_them_all(c, p, task_id)
        leader = await c.post(
            f"/agent/tasks/{task_id}/approval",
            headers=p.leader_headers,
            json={"approve": True},
        )
        assert leader.status_code == 200, leader.text

        # Gỡ điểm đã chấm ngay trong kho, đúng hình dạng một dòng dữ liệu cũ.
        from uuid import UUID

        async with app.state.container.uow_factory() as uow:
            item = (await uow.criteria.list_by_task(UUID(task_id)))[0]
            item.result = AcceptanceResult.UNRATED
            item.done = False
            await uow.criteria.update(item)
            await uow.commit()

        patron = await c.post(
            f"/v1/tasks/{task_id}/approval", headers=p.headers, json={"approve": True}
        )
        assert patron.status_code == 409, patron.text
        assert CRITERIA[0] in patron.json()["detail"], patron.text

        # Điều phân biệt hai cổng, và là lý do cổng này tồn tại: chữ ký người chủ **không
        # được ghi**. Chỉ chặn ở lúc đóng cũng trả về 409 với đúng câu chữ ấy — nhìn từ
        # ngoài giống hệt — nhưng lúc đó dòng chữ ký đã nằm trong sổ rồi.
        rows = await c.get(f"/v1/tasks/{task_id}/approvals", headers=p.headers)
        kinds = [a["signer_kind"] for a in rows.json()]
        assert kinds == ["leader"], kinds
        still = await c.get(f"/v1/tasks/{task_id}", headers=p.headers)
    assert still.json()["status"] == "in_review", still.text


async def test_a_task_with_no_criteria_still_closes() -> None:
    """Cố ý: bộ tiêu chí rỗng thì cổng này đi qua.

    Bắt buộc *phải có* tiêu chí là một cổng khác, đặt ở lúc giao việc chứ không phải lúc
    đóng — và dựng nó ở đây sẽ chặn mọi đầu việc có từ trước bộ tiêu chí. Ghi ra thành bài
    kiểm để lần sau ai đó đọc mã không tưởng là quên.
    """
    async with client() as c:
        p = await operating_project(c, "sign-empty@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        leader = await c.post(
            f"/agent/tasks/{task_id}/approval",
            headers=p.leader_headers,
            json={"approve": True},
        )
        assert leader.status_code == 200, leader.text
        done = await c.post(
            f"/v1/tasks/{task_id}/approval", headers=p.headers, json={"approve": True}
        )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done", done.text
