"""Exercise .cmd wrappers using a harmless local Python script, never the APIs."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name,command", [("scan", "scan_channels"), ("process", "process_jobs")])
def test_windows_wrapper_is_local_and_preserves_exit_status(name, command, tmp_path):
    source = ROOT / "scripts" / f"{name}.cmd"
    text = source.read_text(encoding="utf-8")
    assert 'cd /d "%~dp0.."' in text
    assert r".venv\Scripts\python.exe" in text
    assert "exit /b %errorlevel%" in text
    assert command in text
    assert "schtasks" not in text.lower()
    assert "start " not in text.lower()
    assert "%*" in text
    if os.name != "nt":
        pytest.skip("Execution requires Windows cmd.exe")
    root = tmp_path / "project with spaces"
    (root / "scripts").mkdir(parents=True)
    python_dir = root / ".venv" / "Scripts"
    python_dir.mkdir(parents=True)
    shutil.copy2(source, root / "scripts" / source.name)
    shutil.copy2(sys.executable, python_dir / "python.exe")
    shutil.copy2(Path(sys.prefix) / "pyvenv.cfg", root / ".venv" / "pyvenv.cfg")
    (root / "manage.py").write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path('arguments.json').write_text(json.dumps(sys.argv[1:]))\n"
        "print('harmless-wrapper-probe')\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(root / "scripts" / source.name), "--limit", "3"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 7, result.stderr
    args = json.loads((root / "arguments.json").read_text())
    assert args[0] == command
    assert args[-2:] == ["--limit", "3"]
    # Even the process wrapper stays preview-first: live is an explicit opt-in.
    assert "--publish" not in args
    assert "harmless-wrapper-probe" in (root / ".runtime" / f"{name}.log").read_text()
