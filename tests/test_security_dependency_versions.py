"""Keep reviewed Python security floors in the committed dependency graph."""

from pathlib import Path

import pytest
import tomllib
from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
SECURITY_FLOORS = {
    "filelock": "4.2.1",
    "litellm": "1.100.4",
    "oauthlib": "4.0.1",
    "opentelemetry-api": "1.45.2",
    "pyasn1": "0.6.5",
    "setuptools": "84.1.0",
    "tornado": "6.6",
}


@pytest.mark.parametrize("package,minimum", SECURITY_FLOORS.items())
def test_locked_security_floor(package: str, minimum: str) -> None:
    """Check every resolution, including platform-specific duplicate entries."""
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    versions = [p["version"] for p in lock["package"] if p["name"] == package]
    assert versions, f"Missing reviewed dependency: {package}"
    assert all(Version(version) >= Version(minimum) for version in versions)


@pytest.mark.parametrize("package", ["litellm", "setuptools"])
def test_direct_dependencies_reject_vulnerable_releases(package: str) -> None:
    """Published metadata must retain the floor even without the source lock."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    entries = config["build-system"]["requires"] + [
        entry
        for group in config["project"]["optional-dependencies"].values()
        for entry in group
    ]
    requirements = [Requirement(entry) for entry in entries]
    matching = [entry for entry in requirements if entry.name == package]
    assert matching
    for entry in matching:
        assert any(
            spec.operator in {">=", "=="}
            and Version(spec.version) >= Version(SECURITY_FLOORS[package])
            for spec in entry.specifier
        ), str(entry)
