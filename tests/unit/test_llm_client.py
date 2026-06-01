import pytest
from llm.client import MockLLMClient, create_client


def test_mock_client_returns_fixed_response():
    client = MockLLMClient(response='{"mappings": [], "unmappable": []}')
    result = client.complete("some prompt")
    assert result == '{"mappings": [], "unmappable": []}'


def test_mock_client_records_calls():
    client = MockLLMClient(response="ok")
    client.complete("prompt one")
    client.complete("prompt two")
    assert client.call_count == 2
    assert client.last_prompt == "prompt two"


def test_create_client_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        create_client("unknown/model-id")


def test_create_client_rejects_missing_model_id():
    with pytest.raises(ValueError, match="Invalid model spec"):
        create_client("claude")


def test_create_client_accepts_valid_spec_format():
    # Should not raise — provider is recognised even if SDK not configured
    client = create_client("claude/claude-opus-4-6")
    assert hasattr(client, "complete")


def test_create_client_accepts_vertex_spec():
    client = create_client("vertex/gemini-2.0-flash")
    assert hasattr(client, "complete")


def test_create_client_vertex_rejects_missing_model_id():
    with pytest.raises(ValueError, match="Invalid model spec"):
        create_client("vertex")
