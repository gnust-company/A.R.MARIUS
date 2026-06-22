"""Adapter registry — resolves a MariusAdapter by its `type` (§5)."""

from __future__ import annotations

from armarius.application.ports.adapter import AdapterRegistry, MariusAdapter


class InMemoryAdapterRegistry(AdapterRegistry):
    def __init__(self) -> None:
        self._adapters: dict[str, MariusAdapter] = {}

    def register(self, adapter: MariusAdapter) -> None:
        self._adapters[adapter.type] = adapter

    def get(self, adapter_type: str) -> MariusAdapter:
        try:
            return self._adapters[adapter_type]
        except KeyError as exc:
            raise LookupError(f"no adapter registered for type '{adapter_type}'") from exc

    def types(self) -> list[str]:
        return sorted(self._adapters)
