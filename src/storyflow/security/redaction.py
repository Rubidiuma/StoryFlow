from __future__ import annotations

"""Log-level redaction of credentials and secrets."""

import logging
import re

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9\-_]{16,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-_\.]{16,}"),
    re.compile(r"(api_key=)[^\s&\"']+"),
    re.compile(r"(Cookie:[^\n]*session_id=)[^\s;\"']+"),
]

_REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Replace credential-like patterns in text with [REDACTED]."""
    result = text
    for pattern in _PATTERNS:
        result = pattern.sub(
            lambda m: (
                m.group(0)[:m.start(1) - m.start(0)] + _REDACTED
                if m.lastindex and m.lastindex >= 1
                else _REDACTED
            ),
            result,
        )
    return result


class RedactionFilter(logging.Filter):
    """Logging filter that scrubs secrets from log record messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            try:
                record.args = tuple(redact(str(a)) for a in record.args)  # type: ignore[assignment]
            except TypeError:
                pass
        return True
