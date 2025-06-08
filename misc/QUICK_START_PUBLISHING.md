# Quick Start: Publishing Penguin AI to Test PyPI

This is a streamlined guide to get Penguin AI published to Test PyPI quickly.

## Prerequisites (5 minutes)

1. **Create Test PyPI account**: https://test.pypi.org/account/register/
2. **Get API token**: https://test.pypi.org/manage/account/token/
3. **Install tools**:
   ```bash
   pip install build twine
   ```

## Set Up Credentials (2 minutes)

**Option A: Environment Variable**
```bash
export TWINE_PASSWORD="your-test-pypi-token-here"
```

**Option B: Config File**
Create `~/.pypirc`:
```ini
[distutils]
index-servers = testpypi

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = your-test-pypi-token-here
```

## Publish to Test PyPI (3 minutes)

### Automated Way (Recommended)
```bash
python scripts/publish_test_pypi.py
```

### Manual Way
```bash
# Clean and build
rm -rf build/ dist/ *.egg-info/
python -m build

# Check package
python -m twine check dist/*

# Upload to Test PyPI
python -m twine upload --repository testpypi dist/*
```

## Test Installation (2 minutes)

```bash
# Create test environment
python -m venv test_env
source test_env/bin/activate  # Windows: test_env\Scripts\activate

# Install from Test PyPI
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ penguin-ai

# Test it works
penguin --help
python -c "import penguin; print('Success!')"

# Clean up
deactivate
rm -rf test_env
```

## What's Included in the Package

✅ **Core Components**:
- `penguin.core.PenguinCore` - Main AI assistant
- `penguin.chat.cli` - Command-line interface
- `penguin.api.server` - Web server
- `penguin.config.yml` - Default configuration

✅ **Entry Points**:
- `penguin` - CLI command
- `penguin-web` - Web server command

✅ **Dependencies**: All required packages automatically installed

## Next Steps

1. **View on Test PyPI**: https://test.pypi.org/project/penguin-ai/
2. **Share with testers**: They can install with the command above
3. **Gather feedback**: Test in different environments
4. **Publish to PyPI**: When ready, use `twine upload dist/*` (without `--repository testpypi`)

## Troubleshooting

**Build fails?**
```bash
python test_package.py  # Run our test suite
```

**Upload fails?**
- Check your token is correct
- Ensure you're using `__token__` as username
- Try `--verbose` flag for more details

**Installation fails?**
- Make sure to use both index URLs as shown above
- Some dependencies might not be on Test PyPI

## Version Updates

To publish a new version:
1. Update version in `pyproject.toml`
2. Clean and rebuild: `rm -rf dist/ && python -m build`
3. Upload: `python -m twine upload --repository testpypi dist/*`

---

**Total time: ~12 minutes** ⏱️

For detailed information, see [PUBLISHING.md](PUBLISHING.md). 