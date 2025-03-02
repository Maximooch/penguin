import subprocess
import tempfile
from pathlib import Path


def lint_python(target: str, is_file: bool) -> dict:
    try:
        print(f"Target: {target}")  # Debug print
        if is_file:
            file_path = Path(target).resolve()
        else:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as temp_file:
                temp_file.write(target)
                file_path = Path(temp_file.name).resolve()

        print(f"File path: {file_path}")  # Debug print

        if not file_path.exists():
            return {"error": f"File not found: {file_path}"}

        results = []

        # Run Flake8
        flake8_result = subprocess.run(
            ["flake8", str(file_path)], capture_output=True, text=True
        )
        if flake8_result.stdout:
            results.append(("Flake8 (Style)", flake8_result.stdout))

        # Run Pylint
        pylint_result = subprocess.run(
            ["pylint", str(file_path)], capture_output=True, text=True
        )
        if pylint_result.stdout:
            results.append(("Pylint (Code Quality)", pylint_result.stdout))

        # Run mypy
        mypy_result = subprocess.run(
            ["mypy", str(file_path), "--strict"], capture_output=True, text=True
        )
        if mypy_result.stdout:
            results.append(("mypy (Type Checking)", mypy_result.stdout))

        # Run Bandit
        bandit_result = subprocess.run(
            ["bandit", "-r", str(file_path)], capture_output=True, text=True
        )
        if bandit_result.stdout:
            results.append(("Bandit (Security)", bandit_result.stdout))

        if not is_file:
            file_path.unlink()

        if not results:
            return {"result": "No linting errors found."}
        else:
            formatted_output = []
            for tool, output in results:
                formatted_output.append(f"\n--- {tool} ---\n{output}")
            return {"result": "Linting results:\n" + "\n".join(formatted_output)}

    except Exception as e:
        return {"error": f"Error during linting: {str(e)}"}
