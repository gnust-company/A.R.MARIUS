"""Chữ ký chỉ có giá trị cho bản đang được rà soát (spec 001 FR-033, FR-040).

Một chữ ký được đặt xuống cho **một bản thành phẩm cụ thể**. Đầu việc quay về *đang làm*
nghĩa là bản đó sắp bị sửa. Nếu chữ ký cũ còn sống sang lần nộp sau, thì bản đã sửa được
đóng lại bằng cái gật cho bản trước nó — đúng cái *xong giả* mà cơ chế hai chữ ký sinh ra
để chặn.

Nên luật ở đây chỉ có một câu: **đầu việc rời *chờ rà soát* mà không sang *xong* hoặc
*đã huỷ* thì trạng thái đã-ký được đặt lại về chưa ai ký.**

Đặt lại **không** đụng tới nội dung rà soát. Ai đã duyệt, ai đã trả về, lý do gì, lúc nào
— tất cả nằm nguyên trong sổ và trong nhật ký đầu việc. Thứ được đặt lại chỉ là câu trả
lời cho "bản *hiện tại* đã ai ký chưa".

Đường trả về (từ chối kèm lý do) đã có bài kiểm riêng ở `test_approval_rejection.py`. Ở
đây soi những đường **còn lại** — chính là những đường trước nay không ai viết ra là phải
làm gì, nên chúng lọt lưới.
"""

from __future__ import annotations

from tests.support.approvals import task_awaiting_acceptance
from tests.support.planning import client, operating_project


async def _leader_signs(c, p, task_id: str) -> None:
    r = await c.post(
        f"/agent/tasks/{task_id}/approval",
        headers=p.leader_headers,
        json={"approve": True},
    )
    assert r.status_code == 200, r.text


async def _patron_signs(c, p, task_id: str) -> None:
    r = await c.post(
        f"/v1/tasks/{task_id}/approval", headers=p.headers, json={"approve": True}
    )
    assert r.status_code == 200, r.text


async def _move(c, p, task_id: str, status: str, reason: str | None = None) -> None:
    body: dict = {"status": status}
    if reason is not None:
        body["reason"] = reason
    r = await c.post(f"/v1/tasks/{task_id}/status", headers=p.headers, json=body)
    assert r.status_code == 200, r.text


async def _status(c, p, task_id: str) -> str:
    r = await c.get(f"/v1/tasks/{task_id}", headers=p.headers)
    assert r.status_code == 200, r.text
    return r.json()["status"]


# ── đường ra khỏi *chờ rà soát* không phải là trả về ──────────────────────────────

async def test_pulling_a_task_back_by_hand_clears_the_leader_signature() -> None:
    """Kéo tay về *đang làm* — không qua cửa từ chối — cũng phải đặt lại chữ ký.

    Đây là lỗ hổng mà cách tính cũ để lọt: nó suy ra "đang ở lần rà soát nào" bằng cách
    đếm số lần **bị từ chối**, nên một đường ra không sinh dòng từ chối nào thì với nó
    không có gì thay đổi cả — chữ ký cũ vẫn được coi là của bản mới.
    """
    async with client() as c:
        p = await operating_project(c, "reset-a@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _leader_signs(c, p, task_id)

        # Không ai từ chối. Chỉ là việc chưa ổn nên kéo về làm tiếp.
        await _move(c, p, task_id, "in_progress", reason="Còn thiếu phần đối chiếu.")
        await _move(c, p, task_id, "in_review")

        # Người chủ gật cho bản mới. Chữ ký của Trưởng dự án là cho bản **cũ**.
        await _patron_signs(c, p, task_id)

        assert await _status(c, p, task_id) == "in_review", (
            "bản đã sửa lại không được đóng bằng chữ ký cho bản trước nó"
        )


async def test_blocking_a_task_under_review_clears_the_leader_signature() -> None:
    """Đường thứ hai ra khỏi *chờ rà soát*: bị chặn.

    Việc nằm chờ gỡ chặn rồi mới làm tiếp thì bản nộp lại cũng là bản khác.
    """
    async with client() as c:
        p = await operating_project(c, "reset-b@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _leader_signs(c, p, task_id)

        await _move(c, p, task_id, "blocked", reason="Chờ khoá sổ kế toán.")
        await _move(c, p, task_id, "in_progress")
        await _move(c, p, task_id, "in_review")
        await _patron_signs(c, p, task_id)

        assert await _status(c, p, task_id) == "in_review", (
            "đi qua *bị chặn* rồi quay lại vẫn phải xin chữ ký mới"
        )


async def test_reopening_a_closed_task_clears_both_signatures() -> None:
    """Mở lại việc đã đóng thì hai chữ ký cũ hết hiệu lực.

    Nếu chúng còn sống, mở lại rồi nộp thẳng sang *chờ rà soát* là đóng được ngay mà
    không ai nhìn lại lần nữa — mở lại hoá ra thành một đường vòng để né rà soát.
    """
    async with client() as c:
        p = await operating_project(c, "reset-c@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _leader_signs(c, p, task_id)
        await _patron_signs(c, p, task_id)
        assert await _status(c, p, task_id) == "done"

        r = await c.post(
            f"/v1/tasks/{task_id}/reopen",
            headers=p.headers,
            json={"reason": "Số liệu quý sau lệch, phải soát lại."},
        )
        assert r.status_code == 200, r.text

        await _move(c, p, task_id, "in_review")
        await _patron_signs(c, p, task_id)

        assert await _status(c, p, task_id) == "in_review", (
            "việc mở lại phải đi qua rà soát lại từ đầu"
        )


# ── đặt lại không được làm mất ngữ cảnh ──────────────────────────────────────────

async def test_the_reset_keeps_every_word_of_the_earlier_review() -> None:
    """Đây là điều kiện để việc đặt lại là an toàn.

    Trạng thái đã-ký được đặt lại, nhưng **nội dung** rà soát thì không: lý do, ai nói,
    lúc nào vẫn đọc lại được. Nếu đặt lại mà mất mấy thứ đó thì thợ mất luôn thứ cần để
    sửa, và không ai truy được vì sao bản trước bị trả.
    """
    async with client() as c:
        p = await operating_project(c, "reset-d@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _leader_signs(c, p, task_id)
        r = await c.post(
            f"/v1/tasks/{task_id}/approval",
            headers=p.headers,
            json={"approve": False, "reason": "Thiếu đối chiếu sổ cái quý hai."},
        )
        assert r.status_code == 200, r.text
        await _move(c, p, task_id, "in_review")

        entries = (await c.get(f"/v1/tasks/{task_id}/log", headers=p.headers)).json()

    blob = " ".join(str(e.get("reason") or "") for e in entries)
    assert "sổ cái quý hai" in blob, entries
    assert [e for e in entries if e["kind"] == "approval_signed"], entries


# ── và con đường bình thường vẫn phải đóng được ──────────────────────────────────

async def test_the_ordinary_path_still_closes_on_two_signatures() -> None:
    """Đối chứng. Một luật đặt lại quá tay sẽ khiến không đầu việc nào đóng được nữa."""
    async with client() as c:
        p = await operating_project(c, "reset-e@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _leader_signs(c, p, task_id)
        await _patron_signs(c, p, task_id)

        assert await _status(c, p, task_id) == "done"


async def test_a_signature_survives_the_wait_for_the_other_one() -> None:
    """Đối chứng thứ hai, hẹp hơn: chữ ký chỉ hết hiệu lực khi đầu việc **rời** rà soát.

    Trong lúc đầu việc vẫn nằm ở *chờ rà soát* đợi người thứ hai, chữ ký người thứ nhất
    phải còn nguyên — nếu không thì hai người sẽ không bao giờ ký kịp cùng một bản.
    """
    async with client() as c:
        p = await operating_project(c, "reset-f@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _leader_signs(c, p, task_id)

        assert await _status(c, p, task_id) == "in_review"
        await _patron_signs(c, p, task_id)

        assert await _status(c, p, task_id) == "done"
