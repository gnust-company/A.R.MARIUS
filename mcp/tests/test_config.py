"""Config bootstrap precedence + credential round-trip."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from armarius_mcp import config as config_mod
from armarius_mcp.config import resolve_config
from armarius_mcp.credentials import (
    CREDENTIAL_KEYS,
    Credentials,
    credential_path,
    discover,
    load,
    save,
    slugify,
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Clear all ARMARIUS_* env and point the credentials dir at a temp dir."""
    for key in list(__import__("os").environ):
        if key.startswith("ARMARIUS_"):
            monkeypatch.delenv(key, raising=False)
    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    monkeypatch.setattr(config_mod, "DEFAULT_BASE_URL", "http://localhost:8080")
    monkeypatch.setattr("armarius_mcp.credentials.CREDENTIALS_DIR", cred_dir)
    return cred_dir


def _write_cred(cred_dir, name="acme_marin.json", **over):
    data = {
        "agent_name": "Marin",
        "agent_role": "Backend",
        "agent_token": "arm_from_file",
        "workspace": "Acme",
        "project": "Web",
        "api_base_url": "http://file.host:8080",
    }
    data.update(over)
    p = cred_dir / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_slugify_matches_onboarding_rule():
    assert slugify("Acme Web Platform") == "acme-web-platform"
    assert slugify("  ") == "workspace"  # fallback
    assert slugify("A.R.MARIUS") == "a-r-marius"


def test_credential_path_shape():
    p = credential_path("Acme Web", "Marin")
    assert p.name == "acme-web_marin.json"


def test_credential_round_trip_has_six_keys(tmp_path):
    creds = Credentials(
        agent_name="Marin",
        agent_role="Backend",
        agent_token="arm_x",
        workspace="Acme",
        project="Web",
        api_base_url="http://h:8080",
    )
    path = tmp_path / "out.json"
    save(creds, path)
    on_disk = json.loads(path.read_text())
    assert list(on_disk.keys()) == list(CREDENTIAL_KEYS)
    assert load(path) == creds


def test_save_is_mode_0600(tmp_path):
    p = save(Credentials(agent_token="t"), tmp_path / "c.json")
    assert (p.stat().st_mode & 0o777) == 0o600


def test_token_env_beats_credential_file(monkeypatch, _isolate_env):
    _write_cred(_isolate_env)
    monkeypatch.setenv("ARMARIUS_AGENT_TOKEN", "arm_from_env")
    cfg = resolve_config(probe=False)
    assert cfg.token == "arm_from_env"


def test_token_falls_back_to_credential_file(_isolate_env):
    _write_cred(_isolate_env)
    cfg = resolve_config(probe=False)
    assert cfg.token == "arm_from_file"
    assert cfg.base_url == "http://file.host:8080"
    assert cfg.agent_name == "Marin" and cfg.workspace == "Acme"


def test_base_url_env_beats_file(monkeypatch, _isolate_env):
    _write_cred(_isolate_env)
    monkeypatch.setenv("ARMARIUS_PUBLIC_BASE_URL", "http://env.host:9000")
    cfg = resolve_config(probe=False)
    assert cfg.base_url == "http://env.host:9000"


def test_no_credentials_leaves_token_none(_isolate_env):
    cfg = resolve_config(probe=False)
    assert cfg.token is None
    assert cfg.has_token is False
    assert cfg.base_url == "http://localhost:8080"


def test_two_credential_files_are_ambiguous_no_token(_isolate_env):
    _write_cred(_isolate_env, name="acme_marin.json")
    _write_cred(_isolate_env, name="beta_marin.json")
    # discover() refuses to guess (multi-workspace, deferred to #15).
    assert discover(None) is None
    cfg = resolve_config(probe=False)
    assert cfg.token is None


def test_explicit_credential_file_wins_over_glob(monkeypatch, _isolate_env):
    _write_cred(_isolate_env, name="acme_marin.json", agent_token="arm_a")
    beta = _write_cred(_isolate_env, name="beta_marin.json", agent_token="arm_b")
    monkeypatch.setenv("ARMARIUS_CREDENTIAL_FILE", str(beta))
    cfg = resolve_config(probe=False)
    assert cfg.token == "arm_b"


def test_explicit_credential_file_expands_home_var(monkeypatch, tmp_path, _isolate_env):
    """A ``$HOME/...`` value (what the #114 MCP config now shows) must resolve.

    MCP hosts write the env value verbatim — no shell expansion — so the server itself
    has to expand ``$HOME``. Point HOME at a temp dir, drop a file under it, then pass the
    path with a literal ``$HOME`` prefix.
    """
    home = tmp_path / "home"
    (home / ".armarius" / "tokens").mkdir(parents=True)
    cred = home / ".armarius" / "tokens" / "acme_marin.json"
    _write_cred(cred.parent, name="acme_marin.json", agent_token="arm_home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(
        "ARMARIUS_CREDENTIAL_FILE", "$HOME/.armarius/tokens/acme_marin.json"
    )
    cfg = resolve_config(probe=False)
    assert cfg.token == "arm_home"


def test_explicit_credential_file_still_expands_tilde(monkeypatch, tmp_path, _isolate_env):
    """The older ``~/...`` form keeps working alongside ``$HOME`` (no regression)."""
    home = tmp_path / "home"
    (home / ".armarius" / "tokens").mkdir(parents=True)
    _write_cred(
        home / ".armarius" / "tokens", name="acme_marin.json", agent_token="arm_tilde"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(
        "ARMARIUS_CREDENTIAL_FILE", "~/.armarius/tokens/acme_marin.json"
    )
    cfg = resolve_config(probe=False)
    assert cfg.token == "arm_tilde"


@respx.mock
def test_base_url_probes_meta_when_unset(_isolate_env):
    # No env, no file → probe /v1/meta at the default and use its public_base_url.
    respx.get("http://localhost:8080/v1/meta").mock(
        return_value=httpx.Response(200, json={"public_base_url": "http://discovered:8080"})
    )
    cfg = resolve_config(probe=True)
    assert cfg.base_url == "http://discovered:8080"


@respx.mock
def test_base_url_probe_failure_falls_back_to_default(_isolate_env):
    respx.get("http://localhost:8080/v1/meta").mock(side_effect=httpx.ConnectError("down"))
    cfg = resolve_config(probe=True)
    assert cfg.base_url == "http://localhost:8080"
