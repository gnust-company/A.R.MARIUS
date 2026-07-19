"""Turn backend HTTP errors into clean, actionable MCP tool errors.

The backend maps its domain errors to a stable set of status codes
(``backend/armarius/presentation/errors.py``):

- 401 → auth (missing/invalid token)
- 404 → LookupError                       → resource not found
- 409 → transition / artifact / invite    → a workshop rule blocked it
- 400 → EnrollmentError / ValueError      → bad code or bad argument
- 422 → request-body validation           → malformed payload

Every JSON error body is ``{"detail": "..."}``. We surface that detail plus a short,
model-facing hint so a weak model knows what to do next.
"""

from __future__ import annotations

import httpx


class ArmariusApiError(RuntimeError):
    """A non-2xx response from the Armarius backend, rendered for an agent."""

    def __init__(self, status_code: int, detail: str, hint: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        self.hint = hint
        message = f"HTTP {status_code}: {detail}"
        if hint:
            message = f"{message} — {hint}"
        super().__init__(message)


_HINTS = {
    401: (
        "your token is missing or invalid — re-save it from your setup prompt (STEP 1), "
        "or ask your patron to re-send the invite"
    ),
    404: "the resource was not found — check the task_id / marius_id",
    409: (
        "a workshop rule blocked this — e.g. review/done needs a published artifact, or "
        "a dependency is not met"
    ),
    422: "the payload was rejected — check the argument shapes",
}


def _extract_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except (ValueError, TypeError):
        return response.text.strip() or response.reason_phrase or "request failed"
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str) and detail:
            return detail
        if detail is not None:
            return str(detail)
    return str(body)


def raise_for_status(response: httpx.Response) -> None:
    """Raise ``ArmariusApiError`` for any non-2xx response; no-op otherwise."""
    if response.is_success:
        return
    detail = _extract_detail(response)
    hint = _HINTS.get(response.status_code, "")
    raise ArmariusApiError(response.status_code, detail, hint)
