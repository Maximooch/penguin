import os
import json
from pathlib import Path
import argparse


def detect_workspace_source(config_data: dict) -> str:
    """Best-effort detection of where the workspace path came from."""
    if os.getenv("PENGUIN_WORKSPACE"):
        return "env"
    try:
        if config_data.get("workspace", {}).get("path"):
            return "config"
    except Exception:
        pass
    return "default"


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the active Penguin workspace path")
    parser.add_argument("--json", action="store_true", help="Output as JSON with basic metadata")
    args = parser.parse_args()

    # Import inside main to avoid unnecessary imports when used as a module
    from penguin.config import WORKSPACE_PATH, load_config

    workspace_path = Path(WORKSPACE_PATH)
    config_data = load_config()
    source = detect_workspace_source(config_data)

    if args.json:
        print(
            json.dumps(
                {
                    "workspace": str(workspace_path),
                    "exists": workspace_path.exists(),
                    "source": source,
                }
            )
        )
    else:
        print(str(workspace_path))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


