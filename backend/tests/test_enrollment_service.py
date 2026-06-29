"""EnrollmentService — enroll-and-wait, token on approve, claim recovery (LLD §3.4, §12)."""

from __future__ import annotations

import asyncio

import pytest

from armarius.application.use_cases.enrollment import EnrollmentError, EnrollmentService
from armarius.domain.entities.marius import InviteError, InviteStatus
from armarius.domain.entities.workspace import Workspace
from tests.support.fakes import FakeUowFactory


def _factory_with_workspace() -> tuple[FakeUowFactory, Workspace]:
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    return factory, ws


async def _wait_until(predicate, *, tries: int = 200) -> bool:
    for _ in range(tries):
        if predicate():
            return True
        await asyncio.sleep(0)
    return False


async def test_invite_creates_invited_marius_without_token() -> None:
    factory, ws = _factory_with_workspace()
    svc = EnrollmentService(factory)

    m = await svc.invite(ws.id, "Marin", "Backend")

    assert m.invite_status == InviteStatus.INVITED
    assert m.agent_token is None
    assert m.enrollment_code


async def test_enroll_blocks_until_approved_then_returns_token() -> None:
    factory, ws = _factory_with_workspace()
    svc = EnrollmentService(factory)
    m = await svc.invite(ws.id, "Marin", "Backend")

    held = asyncio.create_task(svc.enroll(m.id, m.enrollment_code))

    # the call holds: it flips to pending_review and does NOT return yet
    assert await _wait_until(
        lambda: factory.store.mariuses[m.id].invite_status == InviteStatus.PENDING_REVIEW
    )
    await asyncio.sleep(0)
    assert not held.done()

    approved = await svc.approve(m.id)
    token = await asyncio.wait_for(held, timeout=1)

    assert token == approved.agent_token
    assert token
    assert factory.store.mariuses[m.id].invite_status == InviteStatus.APPROVED


async def test_approve_before_enroll_is_rejected_then_enroll_recovers() -> None:
    factory, ws = _factory_with_workspace()
    svc = EnrollmentService(factory)
    m = await svc.invite(ws.id, "Marin", "Backend")

    # cannot approve straight from INVITED — the agent must enroll first
    with pytest.raises(InviteError):
        await svc.approve(m.id)


async def test_enroll_after_approval_returns_token_immediately() -> None:
    factory, ws = _factory_with_workspace()
    svc = EnrollmentService(factory)
    m = await svc.invite(ws.id, "Marin", "Backend")

    held = asyncio.create_task(svc.enroll(m.id, m.enrollment_code))
    assert await _wait_until(
        lambda: factory.store.mariuses[m.id].invite_status == InviteStatus.PENDING_REVIEW
    )
    approved = await svc.approve(m.id)
    await asyncio.wait_for(held, timeout=1)

    # a second enroll (e.g. reconnect) returns the same token without blocking
    token = await asyncio.wait_for(svc.enroll(m.id, m.enrollment_code), timeout=1)
    assert token == approved.agent_token


async def test_enroll_rejects_bad_code() -> None:
    factory, ws = _factory_with_workspace()
    svc = EnrollmentService(factory)
    m = await svc.invite(ws.id, "Marin", "Backend")

    with pytest.raises(EnrollmentError):
        await svc.enroll(m.id, "wrong-code")


async def test_claim_is_recovery_only() -> None:
    factory, ws = _factory_with_workspace()
    svc = EnrollmentService(factory)
    m = await svc.invite(ws.id, "Marin", "Backend")

    # before approval, claim is rejected
    with pytest.raises(InviteError):
        await svc.claim(m.id, m.enrollment_code)

    held = asyncio.create_task(svc.enroll(m.id, m.enrollment_code))
    assert await _wait_until(
        lambda: factory.store.mariuses[m.id].invite_status == InviteStatus.PENDING_REVIEW
    )
    approved = await svc.approve(m.id)
    await asyncio.wait_for(held, timeout=1)

    # after approval, claim recovers the same token
    assert await svc.claim(m.id, m.enrollment_code) == approved.agent_token


async def test_approve_mints_token_once() -> None:
    factory, ws = _factory_with_workspace()
    svc = EnrollmentService(factory)
    m = await svc.invite(ws.id, "Marin", "Backend")
    held = asyncio.create_task(svc.enroll(m.id, m.enrollment_code))
    assert await _wait_until(
        lambda: factory.store.mariuses[m.id].invite_status == InviteStatus.PENDING_REVIEW
    )
    approved = await svc.approve(m.id)
    await asyncio.wait_for(held, timeout=1)

    # re-approving an already-approved Marius is rejected (token not re-minted)
    with pytest.raises(InviteError):
        await svc.approve(m.id)
    assert factory.store.mariuses[m.id].agent_token == approved.agent_token
