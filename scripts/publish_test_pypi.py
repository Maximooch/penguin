#!/usr/bin/env python3
"""
Script to publish Penguin AI to Test PyPI

This script automates the process of:
1. Cleaning previous builds
2. Running basic tests
3. Building the package
4. Uploading to Test PyPI
5. Testing the installation

Usage:
    python scripts/publish_test_pypi.py [--skip-tests] [--skip-upload] [--skip-install-test]
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def run_command(cmd, check=True, capture_output=False):
    """Run a command and handle errors"""
    print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    try:
        if capture_output:
            result = subprocess.run(cmd, shell=isinstance(cmd, str), check=check, 
                                  capture_output=True, text=True)
            return result.stdout.strip()
        else:
            subprocess.run(cmd, shell=isinstance(cmd, str), check=check)
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}")
        if capture_output and e.stdout:
            print(f"STDOUT: {e.stdout}")
        if capture_output and e.stderr:
            print(f"STDERR: {e.stderr}")
        sys.exit(1)


def clean_build_artifacts():
    """Clean previous build artifacts"""
    print("🧹 Cleaning build artifacts...")
    
    artifacts = [
        "build",
        "dist", 
        "*.egg-info",
        "penguin.egg-info",
        "penguin_ai.egg-info"
    ]
    
    for pattern in artifacts:
        if "*" in pattern:
            # Use shell expansion for glob patterns
            run_command(f"rm -rf {pattern}", check=False)
        else:
            path = Path(pattern)
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                print(f"  Removed: {path}")


def check_dependencies():
    """Check that required tools are installed"""
    print("🔍 Checking dependencies...")
    
    required_tools = ["build", "twine"]
    missing_tools = []
    
    for tool in required_tools:
        try:
            run_command(f"python -m {tool} --help", capture_output=True)
            print(f"  ✅ {tool} is available")
        except:
            missing_tools.append(tool)
            print(f"  ❌ {tool} is missing")
    
    if missing_tools:
        print(f"\n❌ Missing required tools: {', '.join(missing_tools)}")
        print("Install them with:")
        print(f"  pip install {' '.join(missing_tools)}")
        sys.exit(1)


def run_basic_tests():
    """Run basic import and syntax tests"""
    print("🧪 Running basic tests...")
    
    # Test basic import
    try:
        run_command([sys.executable, "-c", "import penguin; print('✅ Basic import successful')"])
    except:
        print("❌ Basic import failed")
        sys.exit(1)
    
    # Test entry points exist
    try:
        run_command([sys.executable, "-c", 
                    "from penguin.chat.cli import app; from penguin.api.server import main; print('✅ Entry points accessible')"])
    except:
        print("❌ Entry points test failed")
        sys.exit(1)


def build_package():
    """Build the package"""
    print("📦 Building package...")
    
    # Build wheel and source distribution
    run_command([sys.executable, "-m", "build"])
    
    # Check that files were created
    dist_dir = Path("dist")
    if not dist_dir.exists():
        print("❌ dist/ directory not created")
        sys.exit(1)
    
    wheel_files = list(dist_dir.glob("*.whl"))
    tar_files = list(dist_dir.glob("*.tar.gz"))
    
    if not wheel_files:
        print("❌ No wheel file created")
        sys.exit(1)
    
    if not tar_files:
        print("❌ No source distribution created")
        sys.exit(1)
    
    print(f"✅ Built: {wheel_files[0].name}")
    print(f"✅ Built: {tar_files[0].name}")
    
    return wheel_files[0], tar_files[0]


def check_package_contents(wheel_file):
    """Check package contents"""
    print("🔍 Checking package contents...")
    
    # Check wheel contents
    result = run_command(["python", "-m", "zipfile", "-l", str(wheel_file)], capture_output=True)
    
    required_files = [
        "penguin/__init__.py",
        "penguin/core.py", 
        "penguin/config.yml",
        "penguin/chat/cli.py",
        "penguin/api/server.py"
    ]
    
    missing_files = []
    for required_file in required_files:
        if required_file not in result:
            missing_files.append(required_file)
    
    if missing_files:
        print(f"❌ Missing required files in package: {missing_files}")
        sys.exit(1)
    
    print("✅ Package contents look good")


def upload_to_test_pypi():
    """Upload to Test PyPI"""
    print("🚀 Uploading to Test PyPI...")
    
    # Check for API token
    if not os.getenv("TWINE_PASSWORD") and not os.path.exists(Path.home() / ".pypirc"):
        print("❌ No Test PyPI credentials found")
        print("Set TWINE_PASSWORD environment variable or configure ~/.pypirc")
        print("Get a token from: https://test.pypi.org/manage/account/token/")
        sys.exit(1)
    
    # Upload to Test PyPI
    cmd = [
        sys.executable, "-m", "twine", "upload",
        "--repository", "testpypi",
        "dist/*"
    ]
    
    if os.getenv("TWINE_PASSWORD"):
        cmd.extend(["--username", "__token__"])
    
    run_command(cmd)
    print("✅ Upload successful!")


def test_installation():
    """Test installation from Test PyPI"""
    print("🧪 Testing installation from Test PyPI...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        venv_path = Path(temp_dir) / "test_venv"
        
        # Create virtual environment
        print("  Creating test virtual environment...")
        venv.create(venv_path, with_pip=True)
        
        # Get python executable in venv
        if sys.platform == "win32":
            python_exe = venv_path / "Scripts" / "python.exe"
            pip_exe = venv_path / "Scripts" / "pip.exe"
        else:
            python_exe = venv_path / "bin" / "python"
            pip_exe = venv_path / "bin" / "pip"
        
        # Install from Test PyPI
        print("  Installing from Test PyPI...")
        run_command([
            str(pip_exe), "install", 
            "--index-url", "https://test.pypi.org/simple/",
            "--extra-index-url", "https://pypi.org/simple/",
            "penguin-ai"
        ])
        
        # Test basic import
        print("  Testing basic import...")
        run_command([str(python_exe), "-c", "import penguin; print('Import successful')"])
        
        # Test CLI entry point
        print("  Testing CLI entry point...")
        run_command([str(python_exe), "-c", "from penguin.chat.cli import app; print('CLI entry point works')"])
        
        print("✅ Installation test successful!")


def main():
    parser = argparse.ArgumentParser(description="Publish Penguin AI to Test PyPI")
    parser.add_argument("--skip-tests", action="store_true", help="Skip running tests")
    parser.add_argument("--skip-upload", action="store_true", help="Skip uploading to Test PyPI")
    parser.add_argument("--skip-install-test", action="store_true", help="Skip testing installation")
    
    args = parser.parse_args()
    
    print("🐧 Penguin AI - Test PyPI Publication Script")
    print("=" * 50)
    
    # Change to project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    os.chdir(project_root)
    
    try:
        # Step 1: Clean build artifacts
        clean_build_artifacts()
        
        # Step 2: Check dependencies
        check_dependencies()
        
        # Step 3: Run basic tests
        if not args.skip_tests:
            run_basic_tests()
        else:
            print("⏭️  Skipping tests")
        
        # Step 4: Build package
        wheel_file, tar_file = build_package()
        
        # Step 5: Check package contents
        check_package_contents(wheel_file)
        
        # Step 6: Upload to Test PyPI
        if not args.skip_upload:
            upload_to_test_pypi()
        else:
            print("⏭️  Skipping upload")
        
        # Step 7: Test installation
        if not args.skip_install_test and not args.skip_upload:
            test_installation()
        else:
            print("⏭️  Skipping installation test")
        
        print("\n🎉 Publication process completed successfully!")
        print("\nNext steps:")
        print("1. Visit https://test.pypi.org/project/penguin-ai/ to see your package")
        print("2. Test installation: pip install -i https://test.pypi.org/simple/ penguin-ai")
        print("3. When ready, publish to real PyPI with: twine upload dist/*")
        
    except KeyboardInterrupt:
        print("\n❌ Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 