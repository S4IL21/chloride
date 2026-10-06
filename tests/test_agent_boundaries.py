import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from chloride import agent as agent_module


def test_dm_memory_is_namespaced_by_user():
    ctx = SimpleNamespace(deps=SimpleNamespace(
        guild_id=None,
        author_id=42,
        message=None,
    ))

    assert agent_module._memory_namespace(ctx) == "dm-42"


def test_local_analysis_rejects_files_outside_allowed_roots(tmp_path: Path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    monkeypatch.setattr(agent_module, "ANALYSIS_SOURCES", (allowed.resolve(),))

    with pytest.raises(ValueError, match="inside"):
        agent_module._safe_analysis_path(str(outside))


def test_local_analysis_accepts_bounded_file_in_allowed_root(tmp_path: Path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "document.txt"
    source.write_text("safe")
    monkeypatch.setattr(agent_module, "ANALYSIS_SOURCES", (allowed.resolve(),))

    assert agent_module._safe_analysis_path(str(source)) == source.resolve()


def test_remote_analysis_rejects_loopback_url():
    with pytest.raises(ValueError, match="Private, local"):
        asyncio.run(agent_module._validate_public_url("http://127.0.0.1/private"))
