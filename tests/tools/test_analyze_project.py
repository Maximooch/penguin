import subprocess

from penguin.tools.core import support


def test_analyze_project_uses_gitignore_with_walk_fallback_and_file_limit(
    tmp_path, monkeypatch
):
    (tmp_path / "app.py").write_text("def run():\n    return True\n")
    dependency_dir = tmp_path / ".venv"
    dependency_dir.mkdir()
    (dependency_dir / "dependency.py").write_text("def ignored():\n    return True\n")

    result = support.analyze_project_structure(tmp_path)

    assert "Files analyzed: 1" in result
    assert "dependency.py" not in result

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".venv/\ngenerated/\n")
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    (generated_dir / "generated.py").write_text("def generated():\n    return True\n")

    result = support.analyze_project_structure(tmp_path)

    assert "Files analyzed: 1" in result
    assert "generated.py" not in result

    result = support.analyze_project_structure(tmp_path, respect_gitignore=False)

    assert "Files analyzed: 2" in result

    monkeypatch.setattr(support, "_ANALYZE_PROJECT_MAX_FILES", 1)

    result = support.analyze_project_structure(tmp_path, respect_gitignore=False)

    assert (
        result
        == "Error: Project analysis exceeds 1 Python files; narrow the directory."
    )
