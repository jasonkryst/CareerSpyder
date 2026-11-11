"""Guards for CI's Playwright install (#286).

CI used to run ``playwright install --with-deps chromium``, which runs apt on
every job, so an Ubuntu mirror outage failed every Playwright job before a
test ran. Both jobs now go through ``.github/actions/install-playwright``,
which only falls back to apt when Chromium can't launch. These tests keep
the workflows from regressing, and exercise ``install.sh`` against fake
``playwright``/``python`` executables (no network, no real browser).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION_DIR = ROOT / ".github" / "actions" / "install-playwright"
ACTION_REF = "./.github/actions/install-playwright"
SCRIPT = ACTION_DIR / "install.sh"

_WITH_DEPS = re.compile(r"playwright\s+install\b[^\n]*--with-deps")
_PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def with_deps_offenders(text: str) -> list[str]:
    """Lines that install Playwright with ``--with-deps`` (always runs apt)."""
    return [line.strip() for line in text.splitlines() if _WITH_DEPS.search(line)]


def _yaml_files() -> list[Path]:
    return sorted(
        [*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml"), *ACTION_DIR.glob("*.yml")]
    )


def _jobs(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]


def _runs_pytest(step: dict) -> bool:
    return bool(re.search(r"\bpytest\b", step.get("run", "")))


# --- the detector itself ----------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "      - run: playwright install --with-deps chromium",
        "run: playwright install chromium --with-deps",
        "python -m playwright install --with-deps",
    ],
)
def test_detector_flags_with_deps(line):
    assert with_deps_offenders(line) == [line.strip()]


@pytest.mark.parametrize(
    "line",
    [
        "playwright install chromium",
        "timeout 600 playwright install-deps chromium",
        "# we no longer use --with-deps here",
    ],
)
def test_detector_ignores_safe_lines(line):
    assert with_deps_offenders(line) == []


# --- the workflows ------------------------------------------------------------


def test_no_workflow_installs_playwright_with_deps():
    offenders = {
        str(p.relative_to(ROOT)): with_deps_offenders(p.read_text(encoding="utf-8"))
        for p in _yaml_files()
    }
    assert {k: v for k, v in offenders.items() if v} == {}


def test_every_pytest_job_installs_playwright_via_shared_action():
    checked = []
    for wf in WORKFLOWS.glob("*.yml"):
        for name, job in _jobs(wf).items():
            steps = job.get("steps", [])
            pytest_idx = [i for i, s in enumerate(steps) if _runs_pytest(s)]
            if not pytest_idx:
                continue
            action_idx = [i for i, s in enumerate(steps) if s.get("uses") == ACTION_REF]
            assert action_idx, f"{wf.name}:{name} runs pytest without {ACTION_REF}"
            assert action_idx[0] < pytest_idx[0], f"{wf.name}:{name} installs after pytest"
            assert not any(
                "playwright install" in s.get("run", "") for s in steps
            ), f"{wf.name}:{name} still installs Playwright inline"
            checked.append(name)
    assert {"test", "integration-test"} <= set(checked)


def test_shared_action_caches_browsers_and_pins_by_sha():
    action = yaml.safe_load((ACTION_DIR / "action.yml").read_text(encoding="utf-8"))
    assert action["runs"]["using"] == "composite"
    steps = action["runs"]["steps"]
    uses = [s["uses"] for s in steps if "uses" in s]
    assert uses, "expected the actions/cache step"
    for ref in uses:
        assert _PINNED.match(ref), f"{ref} must be pinned to a full commit SHA"
    cache = next(s for s in steps if s.get("uses", "").startswith("actions/cache@"))
    assert cache["with"]["path"] == "~/.cache/ms-playwright"
    assert "steps.pw.outputs.version" in cache["with"]["key"]
    assert any("install.sh" in s.get("run", "") for s in steps)


def test_dependabot_watches_local_composite_actions():
    cfg = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    gha = next(u for u in cfg["updates"] if u["package-ecosystem"] == "github-actions")
    assert "/.github/actions/*" in gha.get("directories", [])


def test_dockerfile_apt_retries_before_first_apt_call():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'Acquire::Retries "5"' in text
    assert text.index("Acquire::Retries") < text.index("apt-get update")


def test_dockerfile_installs_libatomic_before_playwright():
    # Playwright >= 1.65's bundled Node needs libatomic.so.1; without it
    # `playwright install` exits 127 before --with-deps can install anything.
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    apt = re.search(r"apt-get install[^\n]*\n[^\n]*\blibatomic1\b", text)
    assert apt, "libatomic1 must be in the base apt-get install"
    assert apt.end() < text.index("playwright install --with-deps chromium &&")


# --- install.sh behaviour, against fake playwright/python ---------------------

_BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(
    _BASH is None or sys.platform == "win32",
    reason="install.sh runs on Linux CI runners; needs a POSIX bash + coreutils timeout",
)

# Each fake pops its next exit code from a space-separated sequence in a file
# (last value repeats), logs its argv, and "hangs" when the code is "hang".
_FAKE = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    echo "{name} $*" >> "$FAKE_DIR/calls.log"
    seq_file="$FAKE_DIR/{name}-$1.seq"
    [ -f "$seq_file" ] || exit 0
    read -r -a codes < "$seq_file"
    code="${{codes[0]}}"
    if [ "${{#codes[@]}}" -gt 1 ]; then echo "${{codes[@]:1}}" > "$seq_file"; fi
    if [ "$code" = hang ]; then exec sleep 30; fi
    exit "$code"
    """
)


def _run_script(tmp_path: Path, **seqs: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run install.sh with fakes; ``seqs`` maps e.g. ``python_launch="1 0"``."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("playwright", "python"):
        fake = bindir / name
        fake.write_text(_FAKE.format(name=name), encoding="utf-8")
        fake.chmod(0o755)
    for key, seq in seqs.items():
        name, _, arg = key.partition("_")
        # python's first arg is "-" (stdin script); key it as "launch" for readability.
        arg = "-" if arg == "launch" else arg.replace("_", "-")
        (tmp_path / f"{name}-{arg}.seq").write_text(seq, encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DIR": str(tmp_path),
        "PW_RETRY_DELAY": "0",
        "PW_DEPS_TIMEOUT": "2",
        "PW_LAUNCH_TIMEOUT": "2",
    }
    result = subprocess.run(  # noqa: S603 - fixed script path, fake executables only
        [_BASH, str(SCRIPT)],
        check=False,  # tests assert on returncode themselves
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    log = tmp_path / "calls.log"
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result, calls


@needs_bash
def test_script_skips_apt_when_chromium_launches(tmp_path):
    result, calls = _run_script(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "skipping apt" in result.stdout
    assert calls == ["playwright install chromium", "python -"]


@needs_bash
def test_script_falls_back_to_apt_when_launch_fails(tmp_path):
    result, calls = _run_script(tmp_path, python_launch="1 0")
    assert result.returncode == 0, result.stderr
    assert "::warning::" in result.stdout
    assert calls.count("playwright install-deps chromium") == 1
    assert calls[-1] == "python -"


@needs_bash
def test_script_retries_apt_once(tmp_path):
    result, calls = _run_script(tmp_path, python_launch="1 0", playwright_install_deps="1 0")
    assert result.returncode == 0, result.stderr
    assert calls.count("playwright install-deps chromium") == 2


@needs_bash
def test_script_fails_clearly_when_apt_is_down(tmp_path):
    result, calls = _run_script(tmp_path, python_launch="1", playwright_install_deps="100")
    assert result.returncode == 1
    assert "::error::Chromium can't launch" in result.stdout
    assert calls.count("playwright install-deps chromium") == 2


@needs_bash
def test_script_times_out_a_hung_apt_instead_of_hanging(tmp_path):
    result, calls = _run_script(tmp_path, python_launch="1", playwright_install_deps="hang")
    assert result.returncode == 1
    assert "::error::Chromium can't launch" in result.stdout
    assert calls.count("playwright install-deps chromium") == 2


@needs_bash
def test_script_retries_then_fails_on_browser_download_error(tmp_path):
    result, calls = _run_script(tmp_path, playwright_install="1")
    assert result.returncode == 1
    assert "::error::Couldn't download" in result.stdout
    assert calls == ["playwright install chromium"] * 2  # never tried to launch


@needs_bash
def test_script_recovers_from_one_download_failure(tmp_path):
    result, calls = _run_script(tmp_path, playwright_install="1 0")
    assert result.returncode == 0, result.stderr
    assert calls == ["playwright install chromium"] * 2 + ["python -"]


# --- Docker base image vs CI Python version ------------------------------------

_FROM_PYTHON = re.compile(r"^FROM\s+python:(\d+\.\d+)[^\s]*", re.MULTILINE)


def dockerfile_python(text: str) -> str | None:
    """The ``X.Y`` of the Dockerfile's ``python:`` base image, if any."""
    m = _FROM_PYTHON.search(text)
    return m.group(1) if m else None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("FROM python:3.14-slim@sha256:" + "a" * 64, "3.14"),
        ("FROM python:3.15-slim", "3.15"),
        ("FROM python:3.14.2-slim-trixie", "3.14"),
        ("FROM debian:trixie-slim", None),
        ("# FROM python:3.15-slim", None),
    ],
)
def test_dockerfile_python_parser(line, expected):
    assert dockerfile_python(line) == expected


def test_ci_tests_the_python_the_docker_image_ships():
    # A base-image bump (e.g. Dependabot's python 3.14 -> 3.15, #277) must
    # move CI's python-version with it, or CI stops testing what ships.
    image = dockerfile_python((ROOT / "Dockerfile").read_text(encoding="utf-8"))
    assert image, "Dockerfile should build FROM a python: base image"
    ci_versions = set()
    for wf in WORKFLOWS.glob("*.yml"):
        for job in _jobs(wf).values():
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("actions/setup-python@"):
                    ci_versions.add(str(step["with"]["python-version"]))
    assert ci_versions == {image}


def test_dependabot_holds_python_base_image_below_315():
    cfg = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    docker = next(u for u in cfg["updates"] if u["package-ecosystem"] == "docker")
    ignored = {i["dependency-name"]: i.get("versions") for i in docker.get("ignore", [])}
    assert ignored.get("python") == [">=3.15"]
