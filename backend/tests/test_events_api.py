"""Hybrid SSE — TopicEventBus semantics + the two stream endpoints (API_CONTRACT §2, §8).

Verifies SSE framing (`event:`/`data:`/`id:`) and `Last-Event-ID` resume on both the
always-on workspace control-plane stream and the per-task trace stream.
"""

from __future__ import annotations

import asyncio
import json

from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.events.topic_bus import TopicEventBus
from armarius.main import app


# ── TopicEventBus unit ────────────────────────────────────────────────────────
async def test_topic_bus_seq_increments_and_resumes_after_id() -> None:
    bus = TopicEventBus()
    s1 = await bus.publish("t", "a", {"x": 1})
    s2 = await bus.publish("t", "b", {"x": 2})
    assert s2 == s1 + 1

    gen = bus.subscribe("t", after_seq=s1)
    first = await asyncio.wait_for(gen.__anext__(), timeout=1)
    assert first.seq == s2 and first.type == "b" and first.data == {"x": 2}
    await gen.aclose()


async def test_topic_bus_fans_out_live_to_every_subscriber() -> None:
    bus = TopicEventBus()
    gen_a, gen_b = bus.subscribe("room"), bus.subscribe("room")
    ta = asyncio.create_task(gen_a.__anext__())
    tb = asyncio.create_task(gen_b.__anext__())
    await asyncio.sleep(0.05)  # let both generators attach their live queues

    await bus.publish("room", "ping", {"n": 1})
    ea = await asyncio.wait_for(ta, timeout=1)
    eb = await asyncio.wait_for(tb, timeout=1)
    assert ea.type == eb.type == "ping" and ea.seq == eb.seq
    await gen_a.aclose()
    await gen_b.aclose()


async def test_topic_bus_is_topic_scoped() -> None:
    bus = TopicEventBus()
    await bus.publish("ws:1", "a", {})
    gen = bus.subscribe("ws:2")  # different topic — must not see ws:1's backlog
    try:
        await asyncio.wait_for(gen.__anext__(), timeout=0.2)
        raise AssertionError("ws:2 should have no events")
    except TimeoutError:
        pass
    finally:
        await gen.aclose()


async def test_topic_bus_evicts_idle_topics_over_cap() -> None:
    # A cap keeps memory bounded: transient per-task topics must not leak buffers forever.
    bus = TopicEventBus(max_topics=2)
    await bus.publish("task:a", "x", {})
    await bus.publish("task:b", "x", {})
    await bus.publish("task:c", "x", {})  # 3rd topic → evict the LRU idle one (task:a)
    assert bus.backlog("task:a") == []  # dropped
    assert [e.type for e in bus.backlog("task:c")] == ["x"]  # kept


async def test_topic_bus_never_evicts_a_live_topic() -> None:
    # A topic with an attached subscriber keeps its replay buffer even under pressure.
    bus = TopicEventBus(max_topics=2)
    queue, _unregister = bus.register("task:live")
    await bus.publish("task:live", "x", {})
    await bus.publish("task:idle", "x", {})
    await bus.publish("task:new", "x", {})  # over cap → must evict idle, never the live one
    assert [e.type for e in bus.backlog("task:live")] == ["x"]
    assert bus.backlog("task:idle") == []


# ── HTTP SSE endpoints ────────────────────────────────────────────────────────
async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[str, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    token = r.json()["tokens"]["access_token"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    return token, ws.json()[0]["id"]


def _parse_events(text: str) -> list[dict]:
    """Parse an SSE body into a list of {id,event,data} frames (blank line = boundary)."""
    events: list[dict] = []
    cur: dict = {}
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line == "":
            if "event" in cur:
                events.append(cur)
            cur = {}
            continue
        for key in ("id", "event", "data"):
            if line.startswith(f"{key}:"):
                cur[key] = line[len(key) + 1 :].strip()
    if "event" in cur:
        events.append(cur)
    return events


async def _invite(c: AsyncClient, ws_id: str, h: dict, name: str) -> str:
    r = await c.post(
        f"/v1/workspaces/{ws_id}/mariuses",
        headers=h,
        json={"name": name, "role": "r", "adapter_type": "echo", "adapter_config": {}},
    )
    return r.json()["id"]


async def test_workspace_stream_frames_a_control_event() -> None:
    # `?live=0` is the finite catch-up response: replay the backlog and close.
    async with await _client() as c:
        token, ws_id = await _register(c, "sse1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        mid = await _invite(c, ws_id, h, "One")  # publishes marius.status_changed

        resp = await c.get(f"/v1/workspaces/{ws_id}/events?live=0", headers=h)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_events(resp.text)
    assert len(events) == 1
    ev = events[0]
    assert ev["event"] == "marius.status_changed"
    assert int(ev["id"]) > 0
    assert json.loads(ev["data"]) == {"marius_id": mid, "status": "invited"}


async def test_workspace_stream_resumes_from_last_event_id() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "sse2@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        await _invite(c, ws_id, h, "One")

        r1 = await c.get(f"/v1/workspaces/{ws_id}/events?live=0", headers=h)
        first_id = _parse_events(r1.text)[0]["id"]

        mid2 = await _invite(c, ws_id, h, "Two")  # a later event the client missed

        resume_h = {**h, "Last-Event-ID": first_id}
        r2 = await c.get(f"/v1/workspaces/{ws_id}/events?live=0", headers=resume_h)
    resumed = _parse_events(r2.text)
    # Resume skips everything ≤ first_id and delivers only the missed second event.
    assert len(resumed) == 1
    assert int(resumed[0]["id"]) > int(first_id)
    assert json.loads(resumed[0]["data"])["marius_id"] == mid2


async def test_workspace_stream_cross_workspace_is_404() -> None:
    async with await _client() as c:
        _, ws_a = await _register(c, "ownerA@armarius.dev")
        token_b, _ = await _register(c, "ownerB@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        r = await c.get(f"/v1/workspaces/{ws_a}/events?live=0", headers=hb)
    assert r.status_code == 404, r.text


async def test_per_task_stream_frames_and_resumes() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "sse3@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        proj = await c.post(
            f"/v1/workspaces/{ws_id}/projects",
            headers=h,
            json={
                "name": "Apollo",
                "leader": {"marius_id": None},
                "roles": [{"title": "Backend", "seats": 1}],
            },
        )
        pid = proj.json()["id"]
        task = await c.post(
            f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Implement /login"}
        )
        task_id = task.json()["id"]

        # The wake engine tees run events here in Sprint 5; publish directly for now.
        bus = app.state.container.control_bus
        s1 = await bus.publish(f"task:{task_id}", "run.delta", {"text": "hello"})
        await bus.publish(f"task:{task_id}", "run.delta", {"text": "world"})

        r1 = await c.get(f"/v1/tasks/{task_id}/stream?live=0", headers=h)
        assert r1.status_code == 200
        events = _parse_events(r1.text)
        assert [e["event"] for e in events] == ["run.delta", "run.delta"]
        assert json.loads(events[0]["data"]) == {"text": "hello"}

        resume_h = {**h, "Last-Event-ID": str(s1)}
        r2 = await c.get(f"/v1/tasks/{task_id}/stream?live=0", headers=resume_h)
    resumed = _parse_events(r2.text)
    assert len(resumed) == 1
    assert json.loads(resumed[0]["data"]) == {"text": "world"}
