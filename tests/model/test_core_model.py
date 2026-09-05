import pytest

from core.model import ModelMessage, ModelRequest, ModelRequestError


@pytest.mark.parametrize(
    ("role", "content"),
    [
        ("", "hello"),
        ("   ", "hello"),
        ("user", ""),
        ("user", "\t"),
    ],
)
def test_model_message_rejects_empty_fields(role: str, content: str) -> None:
    with pytest.raises(ModelRequestError):
        ModelMessage(role=role, content=content)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"messages": ()},
        {"messages": (ModelMessage("user", "hello"),), "temperature": -0.1},
        {
            "messages": (ModelMessage("user", "hello"),),
            "max_output_tokens": 0,
        },
    ],
)
def test_model_request_rejects_invalid_values(kwargs: object) -> None:
    with pytest.raises(ModelRequestError):
        ModelRequest(**kwargs)  # type: ignore[arg-type]


def test_model_request_accepts_custom_role_and_unbounded_temperature() -> None:
    request = ModelRequest(
        messages=(ModelMessage("custom-role", "hello"),),
        temperature=3.5,
        max_output_tokens=1,
    )

    assert request.temperature == 3.5
