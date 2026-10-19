import pytest

from core.model import ModelResponseError, parse_json_response


def test_parse_json_response_accepts_complete_markdown_json_block():
    assert parse_json_response('```json\n{"memories": []}\n```') == {
        "memories": []
    }


def test_parse_json_response_rejects_unclosed_markdown_block():
    with pytest.raises(ModelResponseError, match="not closed"):
        parse_json_response('```json\n{"memories": []}')


def test_parse_json_response_rejects_explanation_around_json():
    with pytest.raises(ModelResponseError):
        parse_json_response('结果如下：\n{"memories": []}')

@pytest.mark.parametrize(("text", "expected"), [
    (' {"memories": []} ', {"memories": []}),
    ('```\n[]\n```', []),
    ('```JSON\nnull\n```', None),
])
def test_parse_json_response_accepts_supported_formats(text, expected):
    assert parse_json_response(text) == expected


@pytest.mark.parametrize("text", [
    "", "not-json", '{"a":1} trailing',
    '```python\n{}\n```', '```json\n{}\n```\nexplanation',
])
def test_parse_json_response_rejects_invalid_formats(text):
    with pytest.raises(ModelResponseError):
        parse_json_response(text)
