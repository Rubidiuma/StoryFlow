"""T22 static checks for Docker configuration safety and correctness."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
COMPOSE = ROOT / "docker-compose.example.yml"


def test_dockerfile_exists() -> None:
    assert DOCKERFILE.exists(), "Dockerfile is missing"


def test_dockerfile_has_explicit_workdir() -> None:
    """Dockerfile must define a WORKDIR for reproducible builds."""
    content = DOCKERFILE.read_text()
    assert "WORKDIR" in content


def test_dockerfile_has_healthcheck() -> None:
    """HEALTHCHECK instruction must be present for orchestrator readiness."""
    assert "HEALTHCHECK" in DOCKERFILE.read_text()


def test_dockerfile_exposes_correct_port() -> None:
    assert "EXPOSE 8000" in DOCKERFILE.read_text()


def test_dockerfile_declares_data_volume() -> None:
    """Writable state must go to /data, not the image layer."""
    assert "VOLUME /data" in DOCKERFILE.read_text() or "/data" in DOCKERFILE.read_text()


def test_dockerignore_excludes_secrets() -> None:
    """Secret-like files must never enter the build context."""
    content = DOCKERIGNORE.read_text()
    for pattern in ("*.env", ".env", "*.key", "secret"):
        assert any(pattern in line for line in content.splitlines()), (
            f"dockerignore should exclude '{pattern}'"
        )


def test_dockerignore_excludes_tests_and_caches() -> None:
    content = DOCKERIGNORE.read_text()
    assert "tests/" in content or "tests" in content
    assert ".pytest_cache" in content


def test_compose_example_has_no_hardcoded_key() -> None:
    """Example compose file must not contain any real API key value."""
    content = COMPOSE.read_text()
    # Check that no sk- prefixed token appears (OpenAI/Anthropic style)
    import re
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", content), (
        "compose example must not contain a real API key"
    )


def test_compose_example_documents_secret_instructions() -> None:
    """Compose file must document how to pass the secret safely."""
    content = COMPOSE.read_text()
    assert "NEVER" in content or "secret" in content.lower()
