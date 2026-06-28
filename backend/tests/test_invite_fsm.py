"""Marius invite FSM — enroll-and-wait, token minted on approve (LLD §3.4, §12)."""

from __future__ import annotations

import pytest

from armarius.domain.entities.marius import InviteError, InviteStatus, Marius
from armarius.shared.clock import utcnow


def _invited() -> Marius:
    return Marius(invite_status=InviteStatus.INVITED, enrollment_code="code-123")


def test_invite_has_no_token() -> None:
    m = _invited()
    assert m.agent_token is None
    assert m.invite_status == InviteStatus.INVITED


def test_enroll_moves_to_pending_review() -> None:
    m = _invited()
    m.begin_enroll()
    assert m.invite_status == InviteStatus.PENDING_REVIEW
    assert m.agent_token is None  # still no token before approval


def test_enroll_is_idempotent() -> None:
    m = _invited()
    m.begin_enroll()
    m.begin_enroll()  # re-enroll while pending is allowed
    assert m.invite_status == InviteStatus.PENDING_REVIEW


def test_approve_mints_token_once() -> None:
    m = _invited()
    m.begin_enroll()
    now = utcnow()
    m.approve("secret-token", now)
    assert m.invite_status == InviteStatus.APPROVED
    assert m.agent_token == "secret-token"
    assert m.approved_at == now


def test_cannot_approve_before_enroll() -> None:
    m = _invited()
    with pytest.raises(InviteError):
        m.approve("secret-token", utcnow())


def test_cannot_approve_twice() -> None:
    m = _invited()
    m.begin_enroll()
    m.approve("secret-token", utcnow())
    with pytest.raises(InviteError):
        m.approve("another-token", utcnow())


def test_revoke_before_approval() -> None:
    m = _invited()
    m.begin_enroll()
    m.revoke()
    assert m.invite_status == InviteStatus.REVOKED


def test_cannot_revoke_after_approval() -> None:
    m = _invited()
    m.begin_enroll()
    m.approve("secret-token", utcnow())
    with pytest.raises(InviteError):
        m.revoke()


def test_claim_returns_token_after_approval() -> None:
    m = _invited()
    m.begin_enroll()
    m.approve("secret-token", utcnow())
    assert m.token_for_claim() == "secret-token"


def test_claim_rejected_before_approval() -> None:
    m = _invited()
    m.begin_enroll()
    with pytest.raises(InviteError):
        m.token_for_claim()
