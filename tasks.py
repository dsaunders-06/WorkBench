"""invoke tasks: build, test, lint, format, run.

Windows-friendly stand-in for a Makefile (spec §B allows "Makefile/invoke tasks").
"""

from __future__ import annotations

import pathlib
import sys

from invoke import Exit, task


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
    regime-engine fit. yfinance (M14) is collected for the same reason - it
    loads submodules dynamically, so a default build imports cleanly and then
    fails the first time real market data is requested.

    Invoked through THIS interpreter (`python -m PyInstaller`) rather than a
    bare `pyinstaller`, which resolves to whichever one is first on PATH. A
    global PyInstaller freezes its own interpreter and its own site-packages,
    producing a build that bundles the wrong Python and silently omits every
    dependency installed only in the venv - it still produces a dist/ folder,
    so the failure looks like a successful build until the exe is run.

    Unsigned. Run `invoke sign` afterwards to Authenticode-sign it.
    """
    c.run(
        f'"{sys.executable}" -m PyInstaller '
        "--noconfirm --name QuantAdvisoryTerminal --onedir --windowed "
        "--collect-all hmmlearn --collect-all sklearn --collect-all yfinance "
        "src/qat/app.py"
    )


@task
def sign(c, thumbprint=None, timestamp="http://timestamp.digicert.com"):
    """Authenticode-sign the packaged executable with a cert from the store.

    Signs by thumbprint from the current user's personal store rather than
    from a .pfx on disk, so the private key never has to sit in the repo or
    be passed on a command line.

    A self-signed certificate is trusted only where its root has been
    installed. It gives you a verifiable publisher identity and tamper
    evidence on your own machines; it does NOT suppress SmartScreen elsewhere,
    which needs a CA-issued certificate and reputation.
    """
    exe = pathlib.Path("dist/QuantAdvisoryTerminal/QuantAdvisoryTerminal.exe")
    if not exe.exists():
        raise Exit(f"{exe} not found - run `invoke package` first")

    signtool = _find_signtool()
    if signtool is None:
        raise Exit("signtool.exe not found - install the Windows SDK signing tools")

    if not thumbprint:
        thumbprint = _first_code_signing_thumbprint(c)
    if not thumbprint:
        raise Exit(
            "No code-signing certificate in Cert:\\CurrentUser\\My. Create one with "
            "New-SelfSignedCertificate, or pass --thumbprint."
        )

    # /tr (RFC3161) rather than /t: a timestamped signature stays valid after
    # the certificate expires, which for a 1-2 year cert is the difference
    # between a build that keeps verifying and one that stops.
    c.run(
        f'"{signtool}" sign /sha1 {thumbprint} /fd SHA256 '
        f'/tr {timestamp} /td SHA256 "{exe}"'
    )
    c.run(f'"{signtool}" verify /pa /v "{exe}"', warn=True)


def _find_signtool() -> pathlib.Path | None:
    """Newest x64 signtool from the Windows SDK."""
    roots = [
        pathlib.Path(r"C:\Program Files (x86)\Windows Kits\10\bin"),
        pathlib.Path(r"C:\Program Files\Windows Kits\10\bin"),
    ]
    candidates = [
        path
        for root in roots
        if root.exists()
        for path in root.rglob("signtool.exe")
        if "x64" in str(path)
    ]
    return max(candidates, key=lambda p: str(p)) if candidates else None


def _first_code_signing_thumbprint(c) -> str:
    result = c.run(
        "powershell -NoProfile -Command "
        '"(Get-ChildItem Cert:\\CurrentUser\\My -CodeSigningCert | '
        'Select-Object -First 1).Thumbprint"',
        hide=True,
        warn=True,
    )
    return (result.stdout or "").strip()


@task(pre=[lint, test])
def build(c):
    pass
