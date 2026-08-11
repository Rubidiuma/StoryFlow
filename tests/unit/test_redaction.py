"""T18 unit coverage for the log-redaction filter."""

from __future__ import annotations

import logging

import pytest

from storyflow.security.redaction import RedactionFilter, redact


@pytest.mark.parametrize(
    "text, should_be_redacted",
    [
        ("sk-abcdefghijklmnopqrstuvwxyz", True),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig", True),
        ("api_key=my-super-secret-key-123", True),
        ("Cookie: session_id=abc123; other=val", True),
        ("Hello, world!", False),
        ("status: ok", False),
        ("error code: 404", False),
    ],
)
def test_redact_masks_sensitive_patterns(text: str, should_be_redacted: bool) -> None:
    """Patterns that look like credentials must be masked; benign text must survive."""
    result = redact(text)
    if should_be_redacted:
        assert "[REDACTED]" in result
        assert text != result
    else:
        assert result == text


def test_redact_leaves_error_codes_visible() -> None:
    """Error codes like 'invalid_choice_state' must not be treated as secrets."""
    text = "detail: invalid_choice_state retryable: False"
    assert redact(text) == text


def test_logging_filter_redacts_message() -> None:
    """RedactionFilter must rewrite log record messages before emission."""
    record = logging.LogRecord(
        name="storyflow", level=logging.ERROR,
        pathname="", lineno=0,
        msg="LLM error: api_key=top-secret-key provider=claude",
        args=(), exc_info=None,
    )
    filt = RedactionFilter()
    result = filt.filter(record)
    assert result is True  # filter must pass the record through
    assert "top-secret-key" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_exception_string_without_credentials_is_unchanged() -> None:
    """redact() on a plain exception message must not alter it."""
    text = "ValueError: scenes_since_last_choice must not be negative"
    assert redact(text) == text
