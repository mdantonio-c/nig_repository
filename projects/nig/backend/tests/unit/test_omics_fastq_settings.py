"""Strict runtime FASTQ limit configuration, without broker or remote I/O."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from nig.scripts.init_omics_pipeline import DispatcherSettings
from nig.services.omics import settings


def test_missing_limit_uses_safe_default(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings.Env, "get", lambda key, default: default)
    assert settings.max_fastq_bytes_from_env() == 15_000_000_000
    assert DispatcherSettings.from_env().max_fastq_bytes == 15_000_000_000


@pytest.mark.parametrize("raw", ["1", "15000000000", "60000000000"])
def test_positive_environment_override(monkeypatch: Any, raw: str) -> None:
    monkeypatch.setattr(
        settings.Env, "get",
        lambda key, default: raw if key == "OMICS_MAX_FASTQ_BYTES" else default,
    )
    assert settings.max_fastq_bytes_from_env() == int(raw)
    assert DispatcherSettings.from_env().max_fastq_bytes == int(raw)


@pytest.mark.parametrize("raw", ["", "0", "-1", "invalid", "1.5", "15GB", "false"])
def test_invalid_environment_limit_is_not_silently_disabled(
    monkeypatch: Any, raw: str
) -> None:
    monkeypatch.setattr(
        settings.Env, "get",
        lambda key, default: raw if key == "OMICS_MAX_FASTQ_BYTES" else default,
    )
    with pytest.raises(ValueError, match="OMICS_MAX_FASTQ_BYTES"):
        settings.max_fastq_bytes_from_env()
    with pytest.raises(ValueError, match="OMICS_MAX_FASTQ_BYTES"):
        DispatcherSettings.from_env()


def test_configuration_forwards_limit_to_backend_and_worker() -> None:
    project = Path(__file__).resolve().parents[3]
    if not (project / "project_configuration.yaml").is_file() or not (
        project / "confs" / "commons.yml"
    ).is_file():
        pytest.skip("Static check requires the project configuration source tree")
    configuration = yaml.safe_load((project / "project_configuration.yaml").read_text())
    compose = yaml.safe_load((project / "confs" / "commons.yml").read_text())
    assert configuration["variables"]["env"]["OMICS_MAX_FASTQ_BYTES"] == 15_000_000_000
    for service in ("backend", "celery"):
        assert compose["services"][service]["environment"]["OMICS_MAX_FASTQ_BYTES"] == (
            "${OMICS_MAX_FASTQ_BYTES}"
        )