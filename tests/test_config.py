from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chloride.config import Config, Tier, load_config, parse_limit


def test_parse_limit_accepts_supported_units():
    assert parse_limit("6/m") == (6, 60)
    assert parse_limit("10 per 30s") == (10, 30)


@pytest.mark.parametrize("value", ["0/m", "-1/m", "1/0s", "invalid"])
def test_parse_limit_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        parse_limit(value)


def test_config_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Config(AI_MODEL_NAME="test:model", misspelled_setting=True)


def test_tier_lists_are_not_shared():
    first = Tier()
    second = Tier()
    first.allowed_tools.append("read_memory")
    assert second.allowed_tools == []


def test_load_config_restricts_extra_context_to_workspace(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "AI_MODEL_NAME": "test:model",
        "AI_EXTRA_CONTEXT_PATH": "../outside.md",
    }))

    with pytest.raises(ValueError, match="inside the workspace"):
        load_config(config_path)


def test_load_config_accepts_existing_workspace_context(tmp_path: Path):
    (tmp_path / "context.md.j2").write_text("hello")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "AI_MODEL_NAME": "test:model",
        "AI_EXTRA_CONTEXT_PATH": "context.md.j2",
    }))

    assert load_config(config_path).AI_MODEL_NAME == "test:model"
