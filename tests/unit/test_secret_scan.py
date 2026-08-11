"""T23 unit coverage for the secret scan script."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.secret_scan import scan_directory


def test_real_api_key_pattern_is_detected(tmp_path: Path) -> None:
    """A file containing an Anthropic-style key must be flagged."""
    (tmp_path / "config.py").write_text('LLM_KEY = "sk-ant-abcdefghijklmnopqrstuvwxyz1234"\n')
    findings = scan_directory(tmp_path)
    assert findings, "Should detect the sk- key"
    assert any("config.py" in str(f[0]) for f in findings)


def test_test_fixture_placeholder_is_not_flagged(tmp_path: Path) -> None:
    """Whitelisted test-fixture values must not produce false positives."""
    (tmp_path / "test_creds.py").write_text(
        'key = "sk-abcdefghijklmnopqrstuvwxyz"\n'
        'env_key = "env-key-xyz"\n'
        'file_key = "file-key-abc"\n'
    )
    findings = scan_directory(tmp_path)
    assert not findings, f"Should not flag test fixtures, got: {findings}"


def test_clean_source_file_passes(tmp_path: Path) -> None:
    """Normal Python source with no credentials must return empty findings."""
    (tmp_path / "models.py").write_text(
        "from dataclasses import dataclass\n\n@dataclass\nclass Story:\n    title: str\n"
    )
    findings = scan_directory(tmp_path)
    assert not findings


def test_bearer_token_in_source_is_detected(tmp_path: Path) -> None:
    """A hardcoded Bearer token in source code must be flagged."""
    (tmp_path / "client.py").write_text(
        'headers = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.realtoken12345678"}\n'
    )
    findings = scan_directory(tmp_path)
    assert findings


def test_pyc_files_are_skipped(tmp_path: Path) -> None:
    """Binary .pyc files should be silently skipped."""
    pyc = tmp_path / "compiled.pyc"
    pyc.write_bytes(b"sk-faketoken\x00\x01")
    findings = scan_directory(tmp_path)
    assert not findings
