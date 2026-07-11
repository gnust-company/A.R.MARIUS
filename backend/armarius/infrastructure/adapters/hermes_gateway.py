"""Hermes Gateway adapter — Armarius' reference runtime bridge (§5.3).

Maps one bounded wake to Hermes' HTTP+SSE gateway:
    POST /v1/runs                  -> 202 {run_id}
    GET  /v1/runs/{run_id}/events  -> SSE stream (teed to ctx.on_event)
    POST /v1/runs/{run_id}/stop    -> on timeout

Session continuity (durable):
    body.session_id        = "armarius:task:{task_id}"            (state.db transcript)
    X-Hermes-Session-Key   = "armarius:agent:{marius}:task:{task}" (Honcho memory scope)
We never call /new for a task session, so re-using session_id == resume.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from armarius.application.ports.adapter import (
    AdapterCapabilities,
    Diagnostics,
    ExecContext,
    ExecResult,
    MariusAdapter,
)
from armarius.domain.entities.run import RunStatus
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_BASE_URL = "http://localhost:8642"
_TERMINAL_EVENTS = {"run.completed", "run.failed"}


class HermesGatewayAdapter(MariusAdapter):
    type = "hermes_gateway"
    capabilities = AdapterCapabilities(resumable=True, streaming=True, transport="http")

    def _conn(self, config: dict) -> tuple[str, dict[str, str]]:
        base_url = str(config.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
        headers = {"Content-Type": "application/json"}
        api_key = config.get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return base_url, headers

    def _session(self, ctx: ExecContext) -> tuple[str, str]:
        params = ctx.session_params or {}
        session_id = params.get("session_id") or f"armarius:task:{ctx.task_id}"
        session_key = (
            params.get("session_key")
            or f"armarius:agent:{ctx.marius_id}:task:{ctx.task_id}"
        )
        return session_id, session_key

    async def _start_run(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        headers: dict[str, str],
        session_id: str,
        session_key: str,
        prompt: str,
        session_params: dict,
    ) -> tuple[str | None, ExecResult | None]:
        """POST /v1/runs. Returns ``(run_id, None)`` once the gateway accepts the work,
        or ``(None, <failed ExecResult>)`` if the connect/status/body says otherwise."""
        try:
            resp = await client.post(
                f"{base_url}/v1/runs",
                headers={**headers, "X-Hermes-Session-Key": session_key},
                json={"input": prompt, "session_id": session_id},
            )
        except httpx.HTTPError as exc:
            return None, ExecResult(
                status=RunStatus.FAILED,
                session_params=session_params,
                error=f"connect failed: {exc}",
            )
        if resp.status_code >= 400:
            return None, ExecResult(
                status=RunStatus.FAILED,
                session_params=session_params,
                error=f"POST /v1/runs -> {resp.status_code}: {resp.text[:300]}",
            )
        run_id = (resp.json() or {}).get("run_id")
        if not run_id:
            return None, ExecResult(
                status=RunStatus.FAILED,
                session_params=session_params,
                error="gateway did not return a run_id",
            )
        return run_id, None

    async def dispatch(self, ctx: ExecContext) -> ExecResult:
        """Hand the prompt to the gateway and return as soon as the run is accepted.

        Unlike ``execute``, this does NOT stream the run to completion — a setup push
        just needs the gateway to accept the work (202 + run_id). The agent then runs on
        its own and reports liveness back via ``/agent/me``; blocking here would stall
        the invite for the whole agent turn and falsely fail a slow-but-fine run (#63).
        """
        base_url, headers = self._conn(ctx.adapter_config)
        session_id, session_key = self._session(ctx)
        session_params = {"session_id": session_id, "session_key": session_key}
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None)) as client:
            run_id, failure = await self._start_run(
                client, base_url, headers, session_id, session_key, ctx.prompt, session_params
            )
        if failure is not None:
            return failure
        return ExecResult(
            status=RunStatus.RUNNING,
            session_params=session_params,
            session_display_id=session_id,
            external_run_id=run_id,
        )

    async def execute(self, ctx: ExecContext) -> ExecResult:
        base_url, headers = self._conn(ctx.adapter_config)
        session_id, session_key = self._session(ctx)
        session_params = {"session_id": session_id, "session_key": session_key}

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None)) as client:
            run_id, failure = await self._start_run(
                client, base_url, headers, session_id, session_key, ctx.prompt, session_params
            )
            if failure is not None:
                return failure
            assert run_id is not None  # _start_run returns exactly one of (run_id, failure)

            usage: dict[str, Any] = {}
            terminal = False
            try:
                async with asyncio.timeout(ctx.timeout_seconds):
                    async for event_type, payload in self._stream_events(
                        client, base_url, headers, run_id
                    ):
                        if ctx.on_event is not None:
                            await ctx.on_event(event_type, payload)
                        if event_type == "run.completed":
                            usage = payload.get("usage", {}) or usage
                            terminal = True
                        elif event_type == "run.failed":
                            terminal = True
                            return ExecResult(
                                status=RunStatus.FAILED,
                                session_params=session_params,
                                external_run_id=run_id,
                                usage=usage,
                                error=str(payload.get("error", "run failed")),
                            )
            except TimeoutError:
                await self._stop(client, base_url, headers, run_id)
                return ExecResult(
                    status=RunStatus.TIMED_OUT,
                    session_params=session_params,
                    external_run_id=run_id,
                    usage=usage,
                    error="run exceeded Armarius watchdog timeout",
                )
            except httpx.HTTPError as exc:
                return ExecResult(
                    status=RunStatus.FAILED,
                    session_params=session_params,
                    external_run_id=run_id,
                    usage=usage,
                    error=f"event stream error: {exc}",
                )

        status = RunStatus.COMPLETED if terminal else RunStatus.FAILED
        return ExecResult(
            status=status,
            session_params=session_params,
            session_display_id=session_id,
            external_run_id=run_id,
            usage=usage,
            error=None if terminal else "stream ended before run.completed",
        )

    async def _stream_events(
        self, client: httpx.AsyncClient, base_url: str, headers: dict[str, str], run_id: str
    ):
        """Yield (event_type, payload) tuples parsed from the Hermes SSE stream."""
        url = f"{base_url}/v1/runs/{run_id}/events"
        async with client.stream("GET", url, headers=headers) as stream:
            if stream.status_code >= 400:
                body = (await stream.aread()).decode("utf-8", "replace")
                raise httpx.HTTPStatusError(
                    f"events {stream.status_code}: {body[:200]}",
                    request=stream.request,
                    response=stream,
                )
            event_name: str | None = None
            data_lines: list[str] = []
            async for line in stream.aiter_lines():
                if line == "":  # blank line dispatches the buffered event
                    if data_lines:
                        yield self._dispatch(event_name, data_lines)
                        if event_name in _TERMINAL_EVENTS:
                            return
                    event_name, data_lines = None, []
                    continue
                if line.startswith(":"):  # SSE comment / heartbeat
                    continue
                if line.startswith("event:"):
                    event_name = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:"):].lstrip())

    @staticmethod
    def _dispatch(event_name: str | None, data_lines: list[str]) -> tuple[str, dict]:
        raw = "\n".join(data_lines)
        payload: dict = {}
        try:
            parsed = json.loads(raw)
            payload = parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            payload = {"text": raw}
        event_type = event_name or str(payload.get("type") or "message")
        return event_type, payload

    async def _stop(
        self, client: httpx.AsyncClient, base_url: str, headers: dict[str, str], run_id: str
    ) -> None:
        try:
            await client.post(f"{base_url}/v1/runs/{run_id}/stop", headers=headers)
        except httpx.HTTPError:
            logger.warning("failed to stop hermes run %s", run_id)

    async def test_environment(self, config: dict) -> Diagnostics:
        base_url, headers = self._conn(config)
        async with httpx.AsyncClient(timeout=10.0) as client:
            for path in ("/v1/capabilities", "/healthz", "/health"):
                try:
                    resp = await client.get(f"{base_url}{path}", headers=headers)
                except httpx.HTTPError as exc:
                    return Diagnostics(ok=False, detail=f"{base_url} unreachable: {exc}")
                if resp.status_code < 400:
                    info = {}
                    try:
                        info = resp.json()
                    except (json.JSONDecodeError, ValueError):
                        info = {"raw": resp.text[:200]}
                    return Diagnostics(ok=True, detail=f"reachable via {path}", info=info)
            return Diagnostics(ok=False, detail=f"{base_url}: no probe endpoint responded")
