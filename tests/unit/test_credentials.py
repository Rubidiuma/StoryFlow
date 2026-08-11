"""T18 unit coverage for the credential provider source priority."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from storyflow.security.credentials import CredentialProvider, CredentialSource


def test_env_var_is_lowest_priority_source(tmp_path: Path) -> None:
    """ENV source is used only when keyring and secret file are both absent."""
    with patch.dict(os.environ, {"STORYFLOW_LLM_KEY": "env-key-xyz"}):
        provider = CredentialProvider(secret_file=None)
        key = provider.get_llm_key()
    assert key == "env-key-xyz"


def test_secret_file_takes_priority_over_env(tmp_path: Path) -> None:
    """A valid secret file supersedes the environment variable."""
    secret = tmp_path / "key.txt"
    secret.write_text("file-key-abc\n")
    with patch.dict(os.environ, {"STORYFLOW_LLM_KEY": "env-key-xyz"}):
        provider = CredentialProvider(secret_file=secret)
        key = provider.get_llm_key()
    assert key == "file-key-abc"


def test_status_never_reveals_plaintext_key(tmp_path: Path) -> None:
    """status() must not contain the actual credential value."""
    secret = tmp_path / "key.txt"
    secret.write_text("super-secret-token\n")
    provider = CredentialProvider(secret_file=secret)

    result = provider.status()

    assert "super-secret-token" not in str(result)
    assert result["configured"] is True


def test_status_reports_unconfigured_when_no_key_available() -> None:
    """Status is unconfigured when neither env var nor secret file is set."""
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("STORYFLOW_LLM_KEY", None)
        provider = CredentialProvider(secret_file=None)
        result = provider.status()
    assert result["configured"] is False


def test_missing_secret_file_falls_back_to_env(tmp_path: Path) -> None:
    """A nonexistent secret file path gracefully falls back to env var."""
    missing = tmp_path / "nonexistent.txt"
    with patch.dict(os.environ, {"STORYFLOW_LLM_KEY": "fallback-key"}):
        provider = CredentialProvider(secret_file=missing)
        key = provider.get_llm_key()
    assert key == "fallback-key"
