import pytest

from core.memory.json_response import parse_json_response


def test_parse_json_response_accepts_complete_markdown_json_block():
    assert parse_json_response('```json\n{"memories": []}\n```') == {
        "memories": []
    }


def test_parse_json_response_rejects_unclosed_markdown_block():
    with pytest.raises(ValueError, match="not closed"):
        parse_json_response('```json\n{"memories": []}')


def test_parse_json_response_rejects_explanation_around_json():
    with pytest.raises(ValueError):
        parse_json_response('结果如下：\n{"memories": []}')
