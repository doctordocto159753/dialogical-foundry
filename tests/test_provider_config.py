import httpx
import pytest

from engine.provider import DEFAULT_LLM_TIMEOUT_SECONDS, _client_options


def test_model_clients_default_to_thirty_minute_response_timeout(monkeypatch):
    monkeypatch.delenv("FOUNDRY_LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    options = _client_options("OPENAI_BASE_URL")

    assert "base_url" not in options
    assert isinstance(options["timeout"], httpx.Timeout)
    assert options["timeout"].connect == 30.0
    assert options["timeout"].read == DEFAULT_LLM_TIMEOUT_SECONDS
    assert options["timeout"].write == DEFAULT_LLM_TIMEOUT_SECONDS
    assert options["timeout"].pool == DEFAULT_LLM_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    ("env_name", "url"),
    [
        ("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1"),
        ("ANTHROPIC_BASE_URL", "https://anthropic-gateway.example.com"),
    ],
)
def test_model_client_options_use_environment_timeout_and_base_url(
    monkeypatch, env_name, url
):
    monkeypatch.setenv("FOUNDRY_LLM_TIMEOUT_SECONDS", "42")
    monkeypatch.setenv(env_name, f"  {url}  ")

    options = _client_options(env_name)

    assert options["base_url"] == url
    assert options["timeout"].connect == 30.0
    assert options["timeout"].read == 42.0


@pytest.mark.parametrize("value", ["0", "-1", "nan", "not-a-number"])
def test_model_timeout_rejects_invalid_environment_values(monkeypatch, value):
    monkeypatch.setenv("FOUNDRY_LLM_TIMEOUT_SECONDS", value)

    with pytest.raises(RuntimeError, match="must be a positive number"):
        _client_options("OPENAI_BASE_URL")
