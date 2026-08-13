"""Every workspace-scoped route, enumerated from the service's own interface document
(T174, FR-081, Hiến pháp I).

``test_patron_ws_guard`` and ``test_agent_ws_guard`` assert the same rule on a list of
routes typed out by hand. That is how seven routes stayed open: the hand-written list
named four of them, the other thirteen were never looked at, and nothing failed. T160
found the seven only by walking the live interface document instead of the list.

So this sweep takes its route list from ``app.openapi()`` — every path carrying a
``{workspace_id}`` segment, whatever module registered it — and calls each one with a
**stranger's token** against a **real row** belonging to someone else.

Two details decide whether this test means anything:

  * The ids are **real and seeded** — a stranger's request aimed at a random id 404s from
    "no such row" whether or not the ownership guard exists, which is a pass that proves
    nothing. Aiming at a row that genuinely exists leaves the guard as the only thing that
    can produce a 404.
  * A request body is synthesized from the route's own schema, because a 422 is decided
    before the endpoint runs — a route rejected for a malformed body never reaches the
    guard, and would sail through a sweep that merely asserted "not 200".

The answer must be 404 and never 403: *forbidden* confirms the row is there, and whether
it is there is the other tenant's fact to keep.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container
from tests.support.agents import GATEWAY_KEY, GATEWAY_URL

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")

# What the ownership guard says when it turns a caller away. The sweep matches on this text
# and not on the status code alone, because a 404 is not evidence the guard ran: the skill
# import route already 404s for a stranger simply because the URL it was handed does not
# resolve, and that is a route the sweep would otherwise have passed while it stood open.
_GUARD_SAYS = "workspace not found"

# Routes where the owner's own GET legitimately answers 404 because there is nothing to
# return yet — checked separately from the stranger sweep so an empty answer is never
# mistaken for a guard. A new route defaults to the strict rule; adding it here has to be
# a deliberate act with a reason next to it.
_OWNER_SEES_NOTHING_WHEN_EMPTY = {
    # No project-setup chat is open in a freshly registered workspace.
    "/v1/workspaces/{workspace_id}/onboarding/active",
}


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    container = build_container()
    container.registry.register(EchoAdapter(step_delay=0.0))
    app.state.container = container
    yield


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    ws = await c.get("/v1/workspaces", headers=h)
    assert ws.status_code == 200
    return h, ws.json()[0]["id"]


async def _seed(c: AsyncClient, h: dict, ws_id: str) -> dict[str, str]:
    """One real row of each kind a workspace route can name in its path."""
    marius = await c.post(
        f"/v1/workspaces/{ws_id}/mariuses",
        headers=h,
        json={
            "name": "Alpha",
            "skills": [],
            "skill_ids": [],
            "adapter_type": "echo",
            "gateway_url": GATEWAY_URL,
            "api_key": GATEWAY_KEY,
        },
    )
    assert marius.status_code == 201, marius.text
    skill = await c.post(
        f"/v1/workspaces/{ws_id}/skills/manual",
        headers=h,
        json={"name": "Private runbook", "description": "How this shop actually works"},
    )
    assert skill.status_code == 201, skill.text
    return {
        "workspace_id": ws_id,
        "marius_id": marius.json()["id"],
        "skill_id": skill.json()["id"],
    }


# ------------------------------------------------------------------ interface document
def _resolve(schema: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        node: Any = spec
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def _sample(schema: dict[str, Any], spec: dict[str, Any]) -> Any:
    """A minimally valid value for a schema node, so body validation cannot pre-empt the guard."""
    schema = _resolve(schema, spec)
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    for branching in ("anyOf", "oneOf"):
        if schema.get(branching):
            # Skip the null branch: an optional field still needs a usable value here.
            real = [b for b in schema[branching] if _resolve(b, spec).get("type") != "null"]
            return _sample((real or schema[branching])[0], spec)
    if schema.get("allOf"):
        merged: dict[str, Any] = {}
        for branch in schema["allOf"]:
            merged.update(_resolve(branch, spec))
        return _sample(merged, spec)

    kind = schema.get("type")
    if kind == "object" or "properties" in schema or "additionalProperties" in schema:
        props = schema.get("properties", {})
        body = {name: _sample(props.get(name, {}), spec) for name in schema.get("required", [])}
        extra = schema.get("additionalProperties")
        if not body and extra not in (None, False):
            return {"SKILL.md": "x" if extra is True else _sample(extra, spec)}
        return body
    if kind == "array":
        item = schema.get("items", {"type": "string"})
        return [_sample(item, spec) for _ in range(schema.get("minItems", 0))]
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return True
    if kind == "null":
        return None

    fmt = schema.get("format")
    if fmt == "uuid":
        return "00000000-0000-0000-0000-0000000000aa"
    if fmt in ("uri", "url"):
        return "https://example.invalid/skill/SKILL.md"
    if fmt == "email":
        return "someone@example.invalid"
    if fmt == "date-time":
        return "2026-01-01T00:00:00Z"
    return "x"


def _workspace_routes(spec: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path, item in spec["paths"].items():
        if "{workspace_id}" not in path:
            continue
        for method, operation in item.items():
            if method.lower() in _HTTP_METHODS:
                yield path, method.lower(), operation


def _detail(response: Any) -> str | None:
    """The error text, or None when the body is not an error at all — a leaked route answers
    with the rows themselves (often a bare list), which must not crash the sweep."""
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("detail") if isinstance(body, dict) else None


def _fill(path: str, seeds: dict[str, str]) -> str:
    url = path
    for name, value in seeds.items():
        url = url.replace("{" + name + "}", value)
    # ?live=0 turns the workspace event stream into a finite catch-up response; every other
    # route ignores it. Without it the sweep would hang on an always-open stream.
    return f"{url}?live=0"


async def _call(
    c: AsyncClient, method: str, url: str, headers: dict, operation: dict, spec: dict
) -> Any:
    schema = (
        operation.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    body = _sample(schema, spec) if schema is not None else None
    return await c.request(method.upper(), url, headers=headers, json=body)


# ------------------------------------------------------------------------------ sweep
async def test_no_workspace_route_answers_a_stranger():
    async with await _client() as c:
        ha, ws_a = await _register(c, "sweep-a@armarius.dev")
        seeds = await _seed(c, ha, ws_a)
        hb, _ = await _register(c, "sweep-b@armarius.dev")

        spec = app.openapi()
        routes = list(_workspace_routes(spec))
        assert len(routes) >= 20, (
            f"only {len(routes)} workspace-scoped routes found — the interface document "
            "looks truncated, and a sweep over a truncated list is the bug this test exists for"
        )

        # Every route is called before anything is asserted. Failing on the first one would
        # report a single open route per run, and T160 found seven — the list is the finding.
        open_routes: list[str] = []
        for path, method, operation in routes:
            url = _fill(path, seeds)
            assert "{" not in url, (
                f"{method.upper()} {path} names a path parameter this sweep has no real row "
                "for. Seed one in _seed(): pointing it at an unseeded id would let the route "
                "pass on a not-found that never reached the ownership guard."
            )
            r = await _call(c, method, url, hb, operation, spec)
            if r.status_code != 404 or _detail(r) != _GUARD_SAYS:
                open_routes.append(f"  {method.upper()} {path} → {r.status_code}: {r.text[:160]}")

        assert not open_routes, (
            f"{len(open_routes)} of {len(routes)} workspace routes did not turn a stranger "
            f"away with {_GUARD_SAYS!r}:\n" + "\n".join(open_routes)
        )


async def test_the_owner_still_reads_every_workspace_route():
    """The other half: a route that 404s for everyone would pass the sweep while being broken."""
    async with await _client() as c:
        ha, ws_a = await _register(c, "sweep-c@armarius.dev")
        seeds = await _seed(c, ha, ws_a)

        spec = app.openapi()
        for path, method, operation in _workspace_routes(spec):
            if method != "get":
                continue
            r = await _call(c, "get", _fill(path, seeds), ha, operation, spec)
            if path in _OWNER_SEES_NOTHING_WHEN_EMPTY:
                assert r.status_code == 404, f"GET {path} → {r.status_code}: {r.text[:200]}"
                continue
            assert r.status_code == 200, (
                f"GET {path} → {r.status_code} for its own owner: {r.text[:300]}"
            )


async def test_a_stranger_cannot_rewrite_another_workspaces_agent_or_skill():
    """The two writes T160 actually pulled off on the running service.

    A status code alone would not have caught them either way round, so this asserts the
    rows themselves: the agent keeps its name, the skill keeps its files and description.
    """
    async with await _client() as c:
        ha, ws_a = await _register(c, "sweep-d@armarius.dev")
        seeds = await _seed(c, ha, ws_a)
        hb, ws_b = await _register(c, "sweep-e@armarius.dev")

        rename = await c.patch(
            f"/v1/workspaces/{ws_a}/mariuses/{seeds['marius_id']}",
            headers=hb,
            json={"name": "Owned by B now"},
        )
        assert rename.status_code == 404, rename.text

        overwrite = await c.put(
            f"/v1/workspaces/{ws_a}/skills/{seeds['skill_id']}",
            headers=hb,
            json={"files": {"SKILL.md": "---\nname: B\n---\n\nMine now.\n"}},
        )
        assert overwrite.status_code == 404, overwrite.text

        # The workspace id in the path was ignored outright before the fix: B could read
        # A's skill through B's OWN workspace id, so the guard alone is not the whole story.
        through_own_ws = await c.get(
            f"/v1/workspaces/{ws_b}/skills/{seeds['skill_id']}", headers=hb
        )
        assert through_own_ws.status_code == 404, through_own_ws.text

        # Nothing moved, and the owner can still write both rows.
        agent = await c.get(f"/v1/workspaces/{ws_a}/mariuses", headers=ha)
        assert agent.status_code == 200
        assert [m["name"] for m in agent.json()] == ["Alpha"]

        skill = await c.get(f"/v1/workspaces/{ws_a}/skills/{seeds['skill_id']}", headers=ha)
        assert skill.status_code == 200
        assert skill.json()["description"] == "How this shop actually works"

        mine = await c.patch(
            f"/v1/workspaces/{ws_a}/mariuses/{seeds['marius_id']}",
            headers=ha,
            json={"name": "Alpha renamed"},
        )
        assert mine.status_code == 200, mine.text
        assert mine.json()["name"] == "Alpha renamed"
