"""Test GitHub App authentication in container.

Verifies that the GitHub App private key is properly mounted and auth works.
Requires GITHUB_APP_* env vars to be set.
"""

import os
import sys

import pytest

required_env = [
    "GITHUB_APP_ID",
    "GITHUB_APP_INSTALLATION_ID",
    "GITHUB_APP_PRIVATE_KEY_PATH",
]
missing = [e for e in required_env if not os.getenv(e)]
if missing:
    pytest.skip(
        f"Skipping GitHub App tests - missing env vars: {missing}",
        allow_module_level=True,
    )

github = pytest.importorskip("github", reason="PyGithub not installed")
Auth = github.Auth
Github = github.Github
GithubIntegration = github.GithubIntegration


def test_github_app_authentication():
    """Test that GitHub App credentials work."""
    app_id = os.getenv("GITHUB_APP_ID")
    installation_id = os.getenv("GITHUB_APP_INSTALLATION_ID")
    private_key_path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")

    print("\n=== Testing GitHub App Authentication ===")
    print(f"App ID: {app_id}")
    print(f"Installation ID: {installation_id}")
    print(f"Private key path: {private_key_path}")

    # Verify PEM file exists and is readable
    if not os.path.exists(private_key_path):
        raise FileNotFoundError(f"Private key not found at {private_key_path}")

    print("✓ Private key file exists")

    # Read the private key
    with open(private_key_path) as f:
        private_key = f.read()

    if not private_key.startswith("-----BEGIN"):
        raise ValueError("Private key doesn't look like a valid PEM file")

    print("✓ Private key file is valid PEM format")

    # Create App authentication
    try:
        auth = Auth.AppAuth(app_id, private_key)
        Github(auth=auth)
        print("✓ Created GitHub App auth")
    except Exception as e:
        raise RuntimeError(f"Failed to create App auth: {e}")

    # Get the installation (use GithubIntegration for newer PyGithub)
    try:
        integration = GithubIntegration(auth=auth)
        print("✓ GitHub integration created")

        # First, list all installations to verify the ID
        print(f"\nListing all installations for App ID {app_id}...")
        try:
            installations = integration.get_installations()
            install_list = list(installations)
            print(f"✓ Found {len(install_list)} installation(s)")
            for inst in install_list:
                print(f"  - Installation ID: {inst.id}, Account: {inst.account.login}")

            if not any(inst.id == int(installation_id) for inst in install_list):
                print(
                    "\n⚠️  WARNING: Installation ID "
                    f"{installation_id} not found in the list above"
                )
                print("   Make sure the App is installed and the ID is correct")
        except Exception as list_err:
            print(f"⚠️  Could not list installations: {list_err}")

        # Get installation auth directly
        print(f"\nAttempting to get installation token for ID {installation_id}...")
        installation_auth = auth.get_installation_auth(int(installation_id))
        github_with_token = Github(auth=installation_auth)
        print("✓ Installation access token obtained")

        # Try to access the target repo. Apps do not need user-info permission.
        repo_name = os.getenv("GITHUB_REPOSITORY", "Maximooch/penguin")
        repo = github_with_token.get_repo(repo_name)
        print(f"✓ Can access repo: {repo.full_name}")
        print(f"  Repo: {repo.description or 'No description'}")
        print(f"  Default branch: {repo.default_branch}")

        return True

    except Exception as e:
        raise RuntimeError(f"GitHub App auth failed: {e}")


if __name__ == "__main__":
    try:
        result = test_github_app_authentication()
        print("\n✅ GitHub App authentication test PASSED")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ GitHub App authentication test FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
