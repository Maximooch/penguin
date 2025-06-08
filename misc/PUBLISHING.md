# Publishing Penguin AI to PyPI

This document outlines the process for publishing Penguin AI to Test PyPI and PyPI.

## Prerequisites

### 1. Accounts and Tokens
- [ ] Create account on [Test PyPI](https://test.pypi.org/account/register/)
- [ ] Create account on [PyPI](https://pypi.org/account/register/)
- [ ] Generate API tokens:
  - Test PyPI: https://test.pypi.org/manage/account/token/
  - PyPI: https://pypi.org/manage/account/token/

### 2. Development Tools
```bash
pip install build twine pytest pytest-asyncio
```

### 3. Environment Setup
Set your Test PyPI token as an environment variable:
```bash
export TWINE_PASSWORD="your-test-pypi-token"
```

Or configure `~/.pypirc`:
```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = your-pypi-token

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = your-test-pypi-token
```

## Pre-Publication Checklist

### Code Quality
- [ ] All tests pass: `python -m pytest tests/`
- [ ] Code is properly formatted: `black penguin/`
- [ ] Imports are sorted: `isort penguin/`
- [ ] Linting passes: `ruff check penguin/`
- [ ] No sensitive data in code (API keys, passwords, etc.)

### Package Configuration
- [ ] Version number updated in `pyproject.toml`
- [ ] Dependencies are up to date and properly specified
- [ ] Entry points are correctly configured
- [ ] `README.md` is comprehensive and up to date
- [ ] `LICENSE` file is present and correct
- [ ] `MANIFEST.in` includes all necessary files

### Documentation
- [ ] README includes installation instructions
- [ ] Usage examples are current
- [ ] API documentation is complete
- [ ] Changelog is updated

### Testing
- [ ] Package builds successfully: `python -m build`
- [ ] Entry points work: `penguin --help` and `penguin-web --help`
- [ ] Basic import works: `python -c "import penguin"`
- [ ] Core functionality works in clean environment

## Publication Process

### Step 1: Test PyPI Publication

Use the automated script:
```bash
python scripts/publish_test_pypi.py
```

Or manually:
```bash
# Clean previous builds
rm -rf build/ dist/ *.egg-info/

# Build package
python -m build

# Check package
python -m twine check dist/*

# Upload to Test PyPI
python -m twine upload --repository testpypi dist/*
```

### Step 2: Test Installation from Test PyPI

```bash
# Create test environment
python -m venv test_env
source test_env/bin/activate  # On Windows: test_env\Scripts\activate

# Install from Test PyPI
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ penguin-ai

# Test basic functionality
penguin --help
python -c "import penguin; print('Success!')"

# Clean up
deactivate
rm -rf test_env
```

### Step 3: Production PyPI Publication

Only after thorough testing on Test PyPI:

```bash
# Upload to production PyPI
python -m twine upload dist/*
```

## Version Management

### Semantic Versioning
- `MAJOR.MINOR.PATCH` (e.g., `1.2.3`)
- **MAJOR**: Breaking changes
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, backward compatible

### Pre-release Versions
- Alpha: `1.0.0a1`, `1.0.0a2`
- Beta: `1.0.0b1`, `1.0.0b2`
- Release Candidate: `1.0.0rc1`, `1.0.0rc2`

### Development Versions
- `1.0.0.dev1`, `1.0.0.dev2`

## Troubleshooting

### Common Issues

#### Build Failures
```bash
# Check for syntax errors
python -m py_compile penguin/**/*.py

# Check dependencies
pip check

# Verbose build
python -m build --verbose
```

#### Upload Failures
```bash
# Check package metadata
python -m twine check dist/*

# Test upload (dry run)
python -m twine upload --repository testpypi dist/* --verbose
```

#### Import Errors After Installation
- Check that all dependencies are properly specified
- Verify entry points are correct
- Test in clean virtual environment

### Package Size Issues
If package is too large:
- Review `MANIFEST.in` to exclude unnecessary files
- Check for accidentally included data files
- Consider splitting into multiple packages

## Automation

### GitHub Actions (Future)
Consider setting up automated publishing with GitHub Actions:
- Trigger on version tags
- Run tests before publishing
- Publish to Test PyPI on pre-release tags
- Publish to PyPI on release tags

### Pre-commit Hooks
```bash
pip install pre-commit
pre-commit install
```

## Security Considerations

- Never commit API tokens to version control
- Use environment variables or secure credential storage
- Regularly rotate API tokens
- Review dependencies for security vulnerabilities
- Use `pip-audit` to check for known vulnerabilities

## Post-Publication

### Verification
- [ ] Package appears on PyPI/Test PyPI
- [ ] Installation works: `pip install penguin-ai`
- [ ] Entry points work correctly
- [ ] Documentation links are functional

### Monitoring
- Monitor download statistics
- Watch for user issues and bug reports
- Keep dependencies updated
- Plan regular maintenance releases

## Resources

- [Python Packaging User Guide](https://packaging.python.org/)
- [PyPI Help](https://pypi.org/help/)
- [Test PyPI](https://test.pypi.org/)
- [Twine Documentation](https://twine.readthedocs.io/)
- [setuptools Documentation](https://setuptools.pypa.io/) 