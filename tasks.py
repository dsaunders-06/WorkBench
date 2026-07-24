"""invoke tasks: build, test, lint, format, run.

Windows-friendly stand-in for a Makefile (spec §B allows "Makefile/invoke tasks").
"""

from __future__ import annotations

from invoke import task


@task
def install(c):
    c.run('pip install -e ".[dev]"')


@task
def test(c):
    c.run("pytest -q")


@task
def lint(c):
    c.run("ruff check .")
    c.run("black --check .")
    c.run("mypy src")
    c.run("bandit -q -r src")


@task
def format(c):
    c.run("ruff check --fix .")
    c.run("black .")


@task
def run(c):
    c.run("python -m qat.app")


@task
def package(c):
    """Build an unsigned Windows executable (spec §M9) via PyInstaller.

    --collect-all is needed for hmmlearn and scikit-learn: both ship data
    files / compiled extension submodules that PyInstaller's default import
    analysis misses, producing a build that launches but crashes on first
    regime-engine fit. Unsigned - see README "Building the Windows
    executable" for the signtool.exe follow-up once a certificate exists.
    """
    c.run(
        "pyinstaller --name QuantAdvisoryTerminal --onedir --windowed "
        "--collect-all hmmlearn --collect-all sklearn "
        "src/qat/app.py"
    )


@task(pre=[lint, test])
def build(c):
    pass
