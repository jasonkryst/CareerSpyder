import pytest
from pydantic import BaseModel, Field, ValidationError

from app.web.validation import fmt_validation_error


class _Simple(BaseModel):
    board_token: str = Field(min_length=1)


class _Multi(BaseModel):
    name: str = Field(min_length=1)
    board_token: str = Field(min_length=1)


def _err(model, **kwargs) -> ValidationError:
    with pytest.raises(ValidationError) as exc_info:
        model(**kwargs)
    return exc_info.value


def test_fmt_single_field_error_contains_field_name_and_message():
    err = _err(_Simple, board_token="")
    result = fmt_validation_error(err)
    assert "board_token" in result
    assert "1 character" in result


def test_fmt_single_field_error_has_no_pydantic_url():
    err = _err(_Simple, board_token="")
    result = fmt_validation_error(err)
    assert "pydantic.dev" not in result
    assert "type=" not in result


def test_fmt_multiple_field_errors_joined_by_semicolon():
    err = _err(_Multi, name="", board_token="")
    result = fmt_validation_error(err)
    assert ";" in result
    assert "name" in result
    assert "board_token" in result


def test_fmt_validation_error_no_pydantic_internal_noise():
    err = _err(_Simple, board_token="")
    result = fmt_validation_error(err)
    assert "string_too_short" not in result
    assert "For further information" not in result
