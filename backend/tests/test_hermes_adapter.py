from __future__ import annotations

from uuid import uuid4

from armarius.application.ports.adapter import ExecContext
from armarius.infrastructure.adapters.hermes_gateway import HermesGatewayAdapter


def test_dispatch_named_event() -> None:
    etype, payload = HermesGatewayAdapter._dispatch(
        "tool.started", ['{"tool_name": "read_file"}']
    )
    assert etype == "tool.started"
    assert payload["tool_name"] == "read_file"


def test_dispatch_falls_back_to_type_field() -> None:
    etype, payload = HermesGatewayAdapter._dispatch(None, ['{"type": "run.completed"}'])
    assert etype == "run.completed"


def test_dispatch_reads_gateway_payload_event_field() -> None:
    # Hermes/openclaw send the discriminator in `payload["event"]` (no SSE `event:` field,
    # no `type` key). This is the regression for the wire-format mismatch that made every run
    # read as FAILED "stream ended before run.completed" — the gateway HAD sent run.completed.
    etype, _payload = HermesGatewayAdapter._dispatch(
        None, ['{"event": "run.completed", "run_id": "run_x", "usage": {"total_tokens": 10}}']
    )
    assert etype == "run.completed"


def test_dispatch_normalizes_message_delta_to_assistant_delta() -> None:
    # The gateway streams text as `message.delta` with the chunk in `delta`; wake/leader-chat
    # consumers + the durable-event filter key on `assistant.delta` + `payload["text"]`.
    etype, payload = HermesGatewayAdapter._dispatch(
        None, ['{"event": "message.delta", "delta": "Ch"}']
    )
    assert etype == "assistant.delta"
    assert payload["text"] == "Ch"


def test_dispatch_sse_event_field_still_wins_over_payload_event() -> None:
    etype, _payload = HermesGatewayAdapter._dispatch(
        "tool.started", ['{"event": "message.delta"}']
    )
    assert etype == "tool.started"


def test_dispatch_non_json_becomes_text() -> None:
    etype, payload = HermesGatewayAdapter._dispatch("assistant.delta", ["hello world"])
    assert etype == "assistant.delta"
    assert payload["text"] == "hello world"


def test_session_derivation_is_deterministic_and_durable() -> None:
    adapter = HermesGatewayAdapter()
    marius_id, task_id = uuid4(), uuid4()
    ctx = ExecContext(prompt="x", adapter_config={}, marius_id=marius_id, task_id=task_id)
    session_id, session_key = adapter._session(ctx)
    assert session_id == f"armarius:task:{task_id}"
    assert session_key == f"armarius:agent:{marius_id}:task:{task_id}"
    # existing handle wins (resume)
    ctx2 = ExecContext(
        prompt="x",
        adapter_config={},
        session_params={"session_id": "keep", "session_key": "scope"},
        marius_id=marius_id,
        task_id=task_id,
    )
    assert adapter._session(ctx2) == ("keep", "scope")
