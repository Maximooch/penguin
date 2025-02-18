import sys
import traceback
from setuptools import find_packages, setup

def get_packages():
    """Get package list with debug information."""
    try:
        packages = find_packages()
        print(f"Found packages: {packages}")
        return packages
    except Exception as e:
        print(f"Error finding packages: {e}")
        print(f"Traceback:\n{traceback.format_exc()}")
        return []

try:
    print(f"Python version: {sys.version}")
    print(f"Current path: {sys.path}")
    
    setup(
        name="penguin",
        version="0.1.0",
        packages=get_packages(),
        package_dir={"": "."},  # Add explicit package directory
        include_package_data=True,  # Include non-Python files
        install_requires=[
            # Web Framework
            "fastapi>=0.68.0",
            "uvicorn>=0.15.0",
            "websockets>=10.0",
            "jinja2>=3.0.0",
            # Core Dependencies
            "tenacity>=8.0.1",
            "pydantic>=1.8.2",
            "python-dotenv>=0.19.0",
            # LLM and API
            "litellm>=1.0.0",
            "anthropic>=0.3.0",
            "openai>=0.27.0",
            # Memory and Search
            "chromadb>=0.3.0",
            "ollama>=0.1.0",
            # Utils
            "rich>=10.0.0",
            "typer>=0.4.0",
            "requests>=2.26.0",
            # Development
            "pytest>=6.0.0",
            "black>=21.0.0",
            "isort>=5.0.0",
            "ruff>=0.1.0",  # Added Ruff
            "plotext",
            "matplotlib",
            "networkx",
            "IPython",
            "ipykernel",
            "ipywidgets",
        ],
        python_requires=">=3.8",
        entry_points={
            "console_scripts": [
                "penguin=penguin.chat.cli:app",
                "penguin-web=penguin.api.server:main",
            ],
        },
    )
except Exception as e:
    print(f"Setup failed: {e}")
    print(f"Traceback:\n{traceback.format_exc()}")
    raise
