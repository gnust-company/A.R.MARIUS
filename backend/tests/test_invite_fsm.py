"""Marius invite FSM — operator-invite: invited → approved, token minted on activate (#63)."""

from __future__ import annotations

import pytest

from armarius.domain.entities.marius import InviteError, InviteStatus, Marius
from armarius.shared.clock import utcnow


def _invited() -> Marius:
    return Marius(invite_status=InviteStatus.INVITED)


def test_invited_has_no_token() -> None:
    m = _invited()
    assert m.agent_token is None
    assert m.invite_status == InviteStatus.INVITED


def test_activate_mints_token_and_flips_to_approved() -> None:
    m = _invited()
    now = utcnow()
    m.activate("secret-token", now)
    assert m.invite_status == InviteStatus.APPROVED
    assert m.agent_token == "secret-token"
    assert m.approved_at == now


def test_cannot_activate_twice() -> None:
    """Idempotent re-activation is an error — a second mint would replace a live token."""
    m = _invited()
    m.activate("secret-token", utcnow())
    with pytest.raises(InviteError):
        m.activate("another-token", utcnow())
    assert m.agent_token == "secret-token"  # unchanged


def test_cannot_activate_a_revoked_agent() -> None:
    m = _invited()
    m.revoke()
    with pytest.raises(InviteError):
        m.activate("secret-token", utcnow())


def test_activate_from_pending_review_for_legacy_rows() -> None:
    """PENDING_REVIEW only exists on legacy rows; activate still admits them (#63)."""
    m = Marius(invite_status=InviteStatus.PENDING_REVIEW)
    m.activate("secret-token", utcnow())
    assert m.invite_status == InviteStatus.APPROVED


def test_revoke_from_invited() -> None:
    m = _invited()
    m.revoke()
    assert m.invite_status == InviteStatus.REVOKED


def test_revoke_from_approved() -> None:
    """Widened revoke: an already-active agent can be revoked (#63)."""
    m = _invited()
    m.activate("secret-token", utcnow())
    m.revoke()
    assert m.invite_status == InviteStatus.REVOKED


def test_cannot_revoke_twice() -> None:
    m = _invited()
    m.revoke()
    with pytest.raises(InviteError):
        m.revoke()
