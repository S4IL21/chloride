from pathlib import Path

import pytest
import typer

from chloride.main import create, create_dockerfiles


def test_create_populates_empty_workspace(tmp_path: Path):
    workspace = tmp_path / "bot"
    workspace.mkdir()

    create(workspace)

    assert (workspace / "config.yaml").is_file()
    assert (workspace / "config.md.j2").is_file()
    assert (workspace / "Dockerfile").is_file()
    assert (workspace / "docker-compose.yml").is_file()
    assert "config.yaml" in (workspace / ".gitignore").read_text()
    assert (workspace / ".dockerignore").read_text() == "*\n"


def test_create_refuses_nonempty_workspace(tmp_path: Path):
    (tmp_path / "existing.txt").write_text("keep me")

    with pytest.raises(typer.Exit):
        create(tmp_path)

    assert (tmp_path / "existing.txt").read_text() == "keep me"


def test_create_docker_requires_force_to_replace(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("AI_MODEL_NAME: test:model\n")
    (tmp_path / "Dockerfile").write_text("original")

    with pytest.raises(typer.Exit):
        create_dockerfiles(tmp_path, force=False)

    assert (tmp_path / "Dockerfile").read_text() == "original"

    create_dockerfiles(tmp_path, force=True)
    assert "python:3.13-slim" in (tmp_path / "Dockerfile").read_text()
