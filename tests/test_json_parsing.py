"""Tests for LLM JSON response parsing."""

from chunks2skus.utils.llm_client import (
    extract_field_value,
    extract_json_blocks,
    parse_json_response,
)


class TestParseJsonResponse:
    """Test parse_json_response handles various LLM output formats."""

    def test_clean_json(self):
        result = parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = parse_json_response(text)
        assert result == {"key": "value"}

    def test_bare_code_block(self):
        text = '```\n{"key": "value"}\n```'
        result = parse_json_response(text)
        assert result == {"key": "value"}

    def test_empty_string(self):
        assert parse_json_response("") is None

    def test_none_input(self):
        assert parse_json_response(None) is None

    def test_invalid_json(self):
        assert parse_json_response("not json at all") is None

    def test_nested_json(self):
        text = '{"facts": [{"name": "test", "content": "value"}]}'
        result = parse_json_response(text)
        assert result is not None
        assert len(result["facts"]) == 1

    def test_whitespace_around(self):
        result = parse_json_response('  \n  {"key": "value"}  \n  ')
        assert result == {"key": "value"}

    def test_json_with_newlines(self):
        text = '{\n  "key": "value",\n  "list": [1, 2, 3]\n}'
        result = parse_json_response(text)
        assert result["list"] == [1, 2, 3]


class TestExtractJsonBlocks:
    """Test extraction of multiple JSON blocks from mixed text."""

    def test_single_block(self):
        text = 'Some text {"key": "value"} more text'
        blocks = extract_json_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["key"] == "value"

    def test_multiple_blocks(self):
        text = '{"a": 1} some text {"b": 2}'
        blocks = extract_json_blocks(text)
        assert len(blocks) == 2

    def test_nested_braces(self):
        text = '{"outer": {"inner": "value"}}'
        blocks = extract_json_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["outer"]["inner"] == "value"

    def test_no_json(self):
        blocks = extract_json_blocks("no json here")
        assert blocks == []


class TestExtractFieldValue:
    """Test regex-based field extraction from malformed JSON."""

    def test_double_quoted(self):
        text = '{"name": "test-value", "other": 1}'
        assert extract_field_value(text, "name") == "test-value"

    def test_not_found(self):
        assert extract_field_value('{"key": "value"}', "missing") is None
