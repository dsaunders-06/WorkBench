"""invoke tasks: build, test, lint, format, run.

Windows-friendly stand-in for a Makefile (spec §B allows "Makefile/invoke tasks").
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime

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
def manual(c):
    """Regenerate the Word user manual, figures included.

    Uses sys.executable for the same reason `package` does: the script imports
    qat and python-docx, so running it under whatever `python` happens to be on
    PATH silently builds against the wrong interpreter.
    """
    c.run(f'"{sys.executable}" scripts/build_manual.py')


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

    Stamps the build first. A frozen application has no git and no repository,
    so provenance has to be captured here or it cannot be recovered later -
    which is how an install sat on M26 while the repository was four milestones
    ahead, with nothing in the running app able to say so.

    Unsigned. Run `invoke sign` afterwards to Authenticode-sign it.
    """
    stamp = _write_build_stamp(c)
    try:
        c.run(
            f'"{sys.executable}" -m PyInstaller '
            "--noconfirm --name QuantAdvisoryTerminal --onedir --windowed "
            "--collect-all hmmlearn --collect-all sklearn --collect-all yfinance "
            "src/qat/app.py"
        )
    finally:
        # The stamp's life is this build. Left behind, the next run from source
        # would report itself as a packaged build of whatever commit was last
        # frozen - precisely the confusion the stamp exists to prevent.
        stamp.unlink(missing_ok=True)


def _write_build_stamp(c) -> pathlib.Path:
    """Freeze the current commit and date into src/qat/_build_stamp.py.

    The `--dirty` marker is the point of doing this at package time rather than
    reading a version constant: a build made from uncommitted changes is not
    reproducible from the commit it claims, and the operator should be able to
    see that on the Settings screen instead of trusting a label.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))
    from qat.domain.display_dates import format_display_date
    from qat.version import MILESTONE, stamp_module_source

    described = c.run("git describe --tags --always --dirty", hide=True, warn=True)
    commit = (described.stdout or "").strip() or "unknown"
    now = datetime.now(UTC)
    built_at = f"{format_display_date(now)} {now:%H:%M} UTC"

    stamp = pathlib.Path("src/qat/_build_stamp.py")
    stamp.write_text(stamp_module_source(MILESTONE, commit, built_at), encoding="utf-8")
    print(f"Build stamp: {MILESTONE} ({commit}, built {built_at})")
    if commit.endswith("-dirty"):
        print("  WARNING: built from a working tree with uncommitted changes")
    return stamp


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
    c.run(f'"{signtool}" sign /sha1 {thumbprint} /fd SHA256 ' f'/tr {timestamp} /td SHA256 "{exe}"')
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
    """The newest usable code-signing certificate in the user's personal store.

    Reads the store through .NET rather than the `Cert:` PSDrive. Two separate
    reasons, both found the first time this was actually needed (M27a), having
    silently reported "no certificate" until then:

    * `-CodeSigningCert` is a provider *dynamic* parameter, and Windows
      PowerShell will not bind it when the path is supplied this way - it fails
      with "a parameter cannot be found", not with an empty result.
    * The `Cert:` drive is not present in every Windows PowerShell host. On the
      build machine it is missing entirely, so even the provider syntax without
      that parameter fails.

    The filter also excludes expired certificates and any without a private
    key, both of which the old query would have happily returned - and signing
    with either produces a build that looks signed and does not verify.
    """
    ps = (
        "$s=New-Object Security.Cryptography.X509Certificates.X509Store('My','CurrentUser'); "
        "$s.Open(0); "
        "$s.Certificates | Where-Object { "
        "$_.HasPrivateKey -and $_.NotAfter -gt (Get-Date) -and "
        "(($_.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.37' })"
        ".EnhancedKeyUsages.Value -contains '1.3.6.1.5.5.7.3.3') } | "
        "Sort-Object NotAfter -Descending | Select-Object -First 1 -ExpandProperty Thumbprint"
    )
    result = c.run(f'powershell -NoProfile -Command "{ps}"', hide=True, warn=True)
    return (result.stdout or "").strip()


@task(pre=[lint, test])
def build(c):
    pass
