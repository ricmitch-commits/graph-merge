from pathlib import Path
import pytest
from llm.client import MockLLMClient
from pipeline.mapper import _parse_mapping_response

RESPONSES = Path(__file__).parent.parent / "fixtures" / "responses"


def test_valid_json_parsed_into_mapping_result():
    raw = (RESPONSES / "mapping_valid.json").read_text()
    client = MockLLMClient(response=raw)
    result = _parse_mapping_response(raw, client)
    assert len(result.mappings) == 1
    assert result.mappings[0].confidence == "high"
    assert result.mappings[0].destination_node.symbol == "ValidateToken"
    assert len(result.unmappable) == 1


def test_invalid_json_triggers_retry():
    bad_json = "not json"
    valid_json = (RESPONSES / "mapping_valid.json").read_text()
    client = MockLLMClient(response=valid_json)
    result = _parse_mapping_response(bad_json, client)
    assert client.call_count == 1   # one retry call was made
    assert len(result.mappings) == 1


def test_invalid_json_twice_raises_value_error():
    client = MockLLMClient(response="still not json")
    with pytest.raises(ValueError, match="unparseable after retry"):
        _parse_mapping_response("not json", client)


def test_unmappable_source_change_has_no_type_required():
    raw = (RESPONSES / "mapping_valid.json").read_text()
    client = MockLLMClient(response=raw)
    result = _parse_mapping_response(raw, client)
    # unmappable entries have no "type" field — SourceChange.type defaults to ""
    assert result.unmappable[0].source_change.type == ""
