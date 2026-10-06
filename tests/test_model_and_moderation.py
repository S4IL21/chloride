import pytest

from chloride.config import Config
from chloride.model import build_model
from chloride.moderation import timeout


def test_standard_model_does_not_require_inline_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    config = Config(AI_MODEL_NAME="google-gla:gemini-flash-latest")

    assert build_model(config) == "google-gla:gemini-flash-latest"
    assert "GOOGLE_API_KEY" not in __import__('os').environ


@pytest.mark.parametrize("seconds", [0, -1])
def test_timeout_requires_positive_duration(seconds):
    with pytest.raises(ValueError, match="positive"):
        timeout(None, 123, seconds)
