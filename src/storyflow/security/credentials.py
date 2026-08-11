from __future__ import annotations

"""Credential provider with source priority: secret file > env var."""

from os import getenv
from pathlib import Path
from typing import Any


class CredentialSource:
    FILE = "file"
    ENV = "env"
    NONE = "none"


class CredentialProvider:
    """Read the LLM API key from the highest-priority available source."""

    def __init__(self, *, secret_file: Path | None = None) -> None:
        self._secret_file = secret_file

    def get_llm_key(self) -> str | None:
        if self._secret_file is not None and self._secret_file.exists():
            text = self._secret_file.read_text(encoding="utf-8").strip()
            if text:
                return text
        return getenv("STORYFLOW_LLM_KEY") or None

    def status(self) -> dict[str, Any]:
        """Return configured/source info without revealing the key value."""
        key = self.get_llm_key()
        if key is None:
            return {"configured": False, "source": CredentialSource.NONE}
        if self._secret_file is not None and self._secret_file.exists():
            return {"configured": True, "source": CredentialSource.FILE}
        return {"configured": True, "source": CredentialSource.ENV}
