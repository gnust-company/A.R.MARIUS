"""Seed parity (Sprint 6) — the demo scenario is owned by a loginable Patron.

The seeded "Acme Web Platform" workspace + its Mariuses must be owned by the demo user
so the owner-scoped ``/v1`` routes admit them, AND the demo user must be able to log in
with the configured password. Without this, a freshly-registered real user would never
see the showcase data (every workspace/marius was previously orphaned).
"""

from __future__ import annotations

from armarius.infrastructure.persistence.unit_of_work import make_uow
from armarius.main import app
from armarius.seed import maybe_seed
from armarius.shared.config import get_settings


async def test_seed_owns_workspace_mariuses_and_login_works() -> None:
    settings = get_settings()
    await maybe_seed(app.state.container)

    async with make_uow() as uow:
        user = await uow.users.get_by_email(settings.demo_email)
        assert user is not None, "demo Patron was not registered"

        acme = next(
            (w for w in await uow.workspaces.list() if w.slug == "acme-web-platform"),
            None,
        )
        assert acme is not None, "Acme workspace was not seeded"
        assert acme.owner_user_id == str(user.id), "workspace not owned by the demo user"

        mariuses = await uow.mariuses.list_by_workspace(acme.id)
        assert len(mariuses) == 4
        assert all(m.owner_user_id == str(user.id) for m in mariuses), (
            "not every seeded Marius is owned by the demo user"
        )

    # The demo Patron authenticates with the configured password → tokens are minted.
    _user, access, refresh = await app.state.container.auth.login(
        email=settings.demo_email, password=settings.demo_password
    )
    assert access and refresh


async def test_seed_is_idempotent() -> None:
    await maybe_seed(app.state.container)
    await maybe_seed(app.state.container)  # second run must not duplicate

    async with make_uow() as uow:
        acme = [
            w for w in await uow.workspaces.list() if w.slug == "acme-web-platform"
        ]
        assert len(acme) == 1, "seeding twice created duplicate workspaces"
