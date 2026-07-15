"""Shared fixtures for the armarius-mcp test suite."""

from __future__ import annotations

from typing import Any

import pytest

from armarius_mcp.client import ArmariusClient
from armarius_mcp.config import Config
from armarius_mcp.state import ServerState

BASE_URL = "http://api.test"


class FakeClient:
    """Records calls and returns canned results — stands in for ArmariusClient in tools tests."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self.calls: list[tuple[str, tuple, dict]] = []
        self.result: Any = {"ok": True}

    def set_token(self, token: str) -> None:
        self.token = token

    def _record(self, _call: str, /, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((_call, args, kwargs))
        return self.result

    async def whoami(self) -> Any:
        return self._record("whoami")

    async def get_task(self, task_id: str) -> Any:
        return self._record("get_task", task_id)

    async def claim_task(self, task_id: str) -> Any:
        return self._record("claim_task", task_id)

    async def post_comment(self, task_id: str, body: str) -> Any:
        return self._record("post_comment", task_id, body)

    async def update_status(self, task_id: str, status: str, reason: str | None = None) -> Any:
        return self._record("update_status", task_id, status, reason)

    async def set_next_action(self, task_id: str, next_action: str | None) -> Any:
        return self._record("set_next_action", task_id, next_action)

    async def publish_artifact(self, task_id: str, **kwargs: Any) -> Any:
        return self._record("publish_artifact", task_id, **kwargs)

    def last(self) -> tuple[str, tuple, dict]:
        return self.calls[-1]


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient(token="arm_existing")


@pytest.fixture
def state(fake_client: FakeClient, tmp_path) -> ServerState:
    cred = tmp_path / "acme_marin.json"
    cfg = Config(
        base_url=BASE_URL,
        token="arm_existing",
        credential_path=str(cred),
        agent_name="Marin",
        agent_role="Backend",
        workspace="Acme",
        project="Web",
    )
    return ServerState(cfg, fake_client)  # type: ignore[arg-type]


@pytest.fixture
def real_client() -> ArmariusClient:
    return ArmariusClient(BASE_URL, "arm_test_token")
