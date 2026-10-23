"""Keep reviewed security exceptions from becoming permanent package freezes."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import tomllib


def test_security_cooldown_exceptions_expire():
    config = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    )["tool"]["uv"]
    assert config["exclude-newer"] == "7 days"
    now = datetime.now(timezone.utc)
    for package, cutoff in config.get("exclude-newer-package", {}).items():
        expiry = datetime.fromisoformat(cutoff) + timedelta(days=7)
        assert now < expiry, (
            f"Remove the expired {package} cutoff from pyproject.toml and run uv lock; "
            "the reviewed release now satisfies the global seven-day cooldown."
        )
