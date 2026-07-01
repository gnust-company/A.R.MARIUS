"""Demo seed — the "Settings Redesign" scenario from the design brief.

Runs once on an empty database so the dashboard has a coherent story to show:
a workspace, four Mariuses, and tasks spanning every lifecycle state, plus a
collaboration thread with @mentions and published artifacts. Uses the `echo`
adapter so "wake" works end-to-end without a real gateway.

Sprint 6 (integration): the scenario is **owned by a loginable demo Patron** (configured
via ``ARMARIUS_DEMO_EMAIL`` / ``ARMARIUS_DEMO_PASSWORD``). The Patron is registered (or
reused if present) and set as the ``owner_user_id`` on the workspace and every Marius, so
the golden-path UI journey — logged in as the demo user — can actually see and interact
with the seeded data (every ``/v1`` route is owner-scoped).
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from armarius.domain.entities.artifact import Artifact
from armarius.domain.entities.comment import AuthorKind, Comment
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.task import Task, TaskStatus
from armarius.domain.entities.workspace import Project, Workspace
from armarius.infrastructure.persistence.unit_of_work import make_uow
from armarius.presentation.container import Container
from armarius.shared.clock import utcnow
from armarius.shared.config import get_settings
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

ACME_SLUG = "acme-web-platform"


def _token() -> str:
    return f"arm_{secrets.token_urlsafe(24)}"


async def _demo_owner_id(container: Container) -> str:
    """Return the user id of the demo Patron, registering them if necessary."""
    settings = get_settings()
    async with make_uow() as uow:
        user = await uow.users.get_by_email(settings.demo_email)
    if user is not None:
        return str(user.id)
    # Register (hashes the password, creates the account). register() also provisions a
    # personal workspace — harmless alongside the seeded Acme workspace.
    user, _access, _refresh = await container.auth.register(
        email=settings.demo_email,
        full_name="Demo Patron",
        password=settings.demo_password,
    )
    return str(user.id)


async def maybe_seed(container: Container) -> None:
    settings = get_settings()
    async with make_uow() as uow:
        already = any(w.slug == ACME_SLUG for w in await uow.workspaces.list())
    if already:
        return  # idempotent — the showcase scenario is already present

    owner_id = await _demo_owner_id(container)

    async with make_uow() as uow:
        now = utcnow()
        ws = Workspace(
            name="Acme Web Platform",
            slug=ACME_SLUG,
            owner_user_id=owner_id,
            created_at=now,
        )
        await uow.workspaces.add(ws)

        project = Project(
            workspace_id=ws.id,
            name="Settings Redesign",
            slug="settings-redesign",
            description="Redesign the account settings experience, dark mode included.",
            created_at=now,
        )
        await uow.projects.add(project)

        def marius(name: str, role: str, skills: list[str], live: Liveness) -> Marius:
            return Marius(
                workspace_id=ws.id,
                name=name,
                role=role,
                skills=skills,
                adapter_type="echo",
                adapter_config={},
                owner_user_id=owner_id,
                agent_token=_token(),
                liveness=live,
                last_seen_at=now,
                created_at=now,
            )

        alice = marius("Alice", "Frontend", ["react", "css"], Liveness.WORKING)
        bob = marius("Bob", "Design", ["figma", "ux"], Liveness.IDLE)
        cleo = marius("Cleo", "Reviewer", ["security"], Liveness.ONLINE)
        dex = marius("Dex", "Backend", ["api", "db"], Liveness.OFFLINE)
        for m in (alice, bob, cleo, dex):
            await uow.mariuses.add(m)

        def task(
            title: str,
            status: TaskStatus,
            *,
            desc: str | None = None,
            assignee: Marius | None = None,
            reason: str | None = None,
            next_action: str | None = None,
        ) -> Task:
            return Task(
                project_id=project.id,
                title=title,
                description=desc,
                status=status,
                status_reason=reason,
                assigned_marius_id=assignee.id if assignee else None,
                next_action=next_action,
                in_progress_at=now if status == TaskStatus.IN_PROGRESS else None,
                completed_at=now if status == TaskStatus.DONE else None,
                created_at=now,
                updated_at=now,
            )

        t_ia = task(
            "Settings information architecture",
            TaskStatus.DONE,
            desc="Define the nav + section structure for the new settings area.",
            assignee=bob,
        )
        t_dark = task(
            "Add dark mode to Settings page",
            TaskStatus.IN_PROGRESS,
            desc="Introduce a dark theme for all settings panels, persisted per user.",
            assignee=alice,
            next_action="Wire ThemeProvider to the new tokens and persist the choice.",
        )
        t_audit = task(
            "Token audit",
            TaskStatus.IN_REVIEW,
            desc="Verify the color tokens meet WCAG AA contrast.",
            assignee=cleo,
        )
        t_persist = task(
            "Persist theme choice",
            TaskStatus.BLOCKED,
            desc="Save the selected theme to the account profile.",
            assignee=dex,
            reason="waiting on Dex for the /settings preferences API",
        )
        t_contrast = task(
            "Audit color contrast on charts",
            TaskStatus.TODO,
            desc="Charts use low-contrast greens in dark mode.",
            assignee=cleo,
        )
        t_spec = task(
            "Settings page redesign spec",
            TaskStatus.BACKLOG,
            desc="Write the redesign spec for the settings surface.",
        )
        for t in (t_ia, t_dark, t_audit, t_persist, t_contrast, t_spec):
            await uow.tasks.add(t)

        thread = [
            (alice, "Starting on dark mode. @Bob can you confirm the token palette for "
                    "dark surfaces?", [bob.id]),
            (bob, "@Alice use --surface-1..3 with the amber accent at 0.9 opacity. Spec "
                  "attached as an artifact.", [alice.id]),
            (alice, "Thanks — wiring the ThemeProvider now.", []),
        ]
        for i, (author, body, mentions) in enumerate(thread):
            await uow.comments.add(
                Comment(
                    task_id=t_dark.id,
                    author_kind=AuthorKind.AGENT,
                    author_marius_id=author.id,
                    body=body,
                    mentions=mentions,
                    created_at=now + timedelta(seconds=i),
                )
            )

        await uow.artifacts.add(
            Artifact(
                project_id=project.id,
                task_id=t_ia.id,
                marius_id=bob.id,
                name="settings-ia.md",
                kind="link",
                uri="store://settings-redesign/settings-ia.md",
                created_at=now,
            )
        )
        await uow.artifacts.add(
            Artifact(
                project_id=project.id,
                task_id=t_audit.id,
                marius_id=cleo.id,
                name="token-audit-report.md",
                kind="link",
                uri="store://settings-redesign/token-audit-report.md",
                created_at=now,
            )
        )

        await uow.commit()
        logger.info(
            "seeded demo workspace '%s' (%s) owned by %s — log in as %s",
            ws.name,
            ws.id,
            owner_id,
            settings.demo_email,
        )
