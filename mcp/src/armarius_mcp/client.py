"""Async HTTP client over the Armarius `/agent/*` API.

One method per endpoint (``backend/armarius/presentation/api/agent.py``). The bearer
token is injected here; every non-2xx becomes an ``ArmariusApiError`` via
``raise_for_status``. Nothing above this layer touches httpx.

Under operator-invite (issue #63) the agent receives its token in the setup prompt
Armarius pushes via its gateway, then calls ``GET /agent/me`` — so there is no
``enroll``/``claim`` bootstrap anymore (issue #64). The token is resolved from the
credential file / env at startup (see ``config.py``).
"""

from __future__ import annotations

from typing import Any

import httpx

from armarius_mcp.http_error import ArmariusApiError, raise_for_status


class NotEnrolledError(RuntimeError):
    """A token-required call was made before the token was resolved."""

    def __init__(self) -> None:
        super().__init__(
            "No agent token found. Your token is delivered in the setup prompt Armarius "
            "pushes to your gateway — save it to your credential file (or set "
            "ARMARIUS_AGENT_TOKEN) and restart. Then call `whoami` to confirm you are online."
        )


class ArmariusClient:
    """Thin async wrapper over `/agent/*`. Holds the token; injects it per call."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        request_timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._request_timeout = request_timeout
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            transport=transport,
            timeout=request_timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ArmariusClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # -- token -----------------------------------------------------------------
    @property
    def token(self) -> str | None:
        return self._token

    def set_token(self, token: str) -> None:
        self._token = token

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            raise NotEnrolledError()
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        auth: bool = True,
        timeout: float | None = None,  # noqa: ASYNC109 — httpx's own per-request timeout
    ) -> Any:
        headers = self._auth_headers() if auth else {}
        try:
            resp = await self._client.request(
                method,
                path,
                json=json,
                headers=headers,
                timeout=timeout if timeout is not None else self._request_timeout,
            )
        except httpx.TimeoutException as exc:
            raise ArmariusApiError(
                0, f"request timed out: {exc}", "the call took too long"
            ) from exc
        except httpx.HTTPError as exc:
            raise ArmariusApiError(
                0, f"could not reach the backend: {exc}", f"is the API up at {self._base_url}?"
            ) from exc
        raise_for_status(resp)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # -- token-authenticated ---------------------------------------------------
    async def whoami(self) -> Any:
        return await self._request("GET", "/agent/me")

    async def get_task(self, task_id: str) -> Any:
        return await self._request("GET", f"/agent/tasks/{task_id}")

    async def claim_task(self, task_id: str) -> Any:
        return await self._request("POST", f"/agent/tasks/{task_id}/claim", json={})

    async def post_comment(self, task_id: str, body: str) -> Any:
        return await self._request(
            "POST", f"/agent/tasks/{task_id}/comment", json={"body": body}
        )

    async def update_status(self, task_id: str, status: str, reason: str | None = None) -> Any:
        payload: dict[str, Any] = {"status": status}
        if reason is not None:
            payload["reason"] = reason
        return await self._request("POST", f"/agent/tasks/{task_id}/status", json=payload)

    async def set_next_action(self, task_id: str, next_action: str | None) -> Any:
        return await self._request(
            "POST", f"/agent/tasks/{task_id}/next-action", json={"next_action": next_action}
        )

    async def publish_artifact(
        self,
        task_id: str,
        *,
        name: str,
        kind: str = "file",
        content: str | None = None,
        content_b64: str | None = None,
        content_sha256: str | None = None,
        uri: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"name": name, "kind": kind}
        if content is not None:
            payload["content"] = content
        if content_b64 is not None:
            payload["content_b64"] = content_b64
        if content_sha256 is not None:
            payload["content_sha256"] = content_sha256
        if uri is not None:
            payload["uri"] = uri
        return await self._request("POST", f"/agent/tasks/{task_id}/artifact", json=payload)
