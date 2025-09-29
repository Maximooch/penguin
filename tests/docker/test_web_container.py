import os
import shutil
import subprocess
import time
import urllib.request

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover - optional dep in CI
    load_dotenv = None  # type: ignore


IMAGE = os.environ.get("PENGUIN_TEST_IMAGE", "penguin:web")
ENV_FILE = os.environ.get("PENGUIN_TEST_ENV_FILE", ".env")


def _curl_health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def test_web_container_health():
    # Ensure docker is available
    if shutil.which("docker") is None:
        raise RuntimeError("docker CLI not found in PATH")

    # Load .env if available (sets os.environ for this process)
    if load_dotenv is not None and os.path.isfile(ENV_FILE):
        load_dotenv(dotenv_path=ENV_FILE, override=False)

    # Prepare env flags to pass into container (allowlist of keys)
    pass_env_keys = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "PENGUIN_CORS_ORIGINS",
        "GITHUB_APP_ID",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_APP_PRIVATE_KEY_PATH",
        "GITHUB_REPOSITORY",
        "GITHUB_TOKEN",
        "PENGUIN_WORKSPACE",
    ]
    env_flags: list[str] = []
    for key in pass_env_keys:
        val = os.environ.get(key)
        if val:
            env_flags.extend(["-e", f"{key}={val}"])
    # Start container
    cmd = [
        "docker",
        "run",
        "-d",
        "-p",
        "28000:8000",
        *env_flags,
        IMAGE,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    cid = proc.stdout.strip()
    try:
        # Wait up to 30s for health
        for _ in range(30):
            if _curl_health(28000):
                break
            time.sleep(1)
        assert _curl_health(28000), "Web container did not become healthy"
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)


