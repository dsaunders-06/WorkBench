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


# Every tool is invoked as `<this interpreter> -m <tool>`, for the reason
# `package` gives below and `manual` repeats: a bare name resolves to whatever
# happens to be on PATH, which is not necessarily this venv and may not exist at
# all. On 21 August `invoke build` died on `'ruff' is not recognized` — the
# tools are installed in the venv and nothing had put its Scripts directory on
# PATH, so the one command meant to gate a release could not run.
def _tool(c, module: str, args: str) -> None:
    c.run(f'"{sys.executable}" -m {module} {args}')


@task
def test(c):
    _tool(c, "pytest", "-q")


@task
def lint(c):
    _tool(c, "ruff", "check .")
    _tool(c, "black", "--check .")
    _tool(c, "mypy", "src")
    _tool(c, "bandit", "-q -r src")


@task
def format(c):
    _tool(c, "ruff", "check --fix .")
    _tool(c, "black", ".")


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
        _run_pyinstaller(c)
    finally:
        # The stamp's life is this build. Left behind, the next run from source
        # would report itself as a packaged build of whatever commit was last
        # frozen - precisely the confusion the stamp exists to prevent.
        stamp.unlink(missing_ok=True)
    _write_dist_manifest(c)


def _write_dist_manifest(c) -> None:
    """Record what was frozen, NEXT TO the exe, where `deploy.ps1` can read it.

    ⚠️ WRITTEN BECAUSE A DEPLOY WOULD HAVE MISLABELLED A STALE BUILD.
    `_build_stamp.py` is bundled INSIDE the exe and deleted from the tree, so
    nothing outside the running application can tell which source a `dist\\`
    folder came from. `deploy.ps1` installs whatever sits in `dist\\` but
    derives its label from `git rev-parse HEAD` and `version.py` - it verified
    that the installed copy matched `dist\\`, never that `dist\\` matched the
    source it was naming.

    Found 1 September 2026: `dist\\` held an exe built 31/08 16:10:30, hash
    A077BE40...55C3, byte-identical to the installed M159, while M160's source
    had landed at 17:18 and the handover recorded M160 as "BUILT". A deploy
    would have installed M159 and written DEPLOYED = M161, reporting success.

    Written AFTER PyInstaller succeeds, so a failed build leaves no manifest and
    the deploy refuses rather than reading a stale one.
    """
    import json

    sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))
    from qat.version import MILESTONE

    described = c.run("git describe --tags --always --dirty", hide=True, warn=True)
    short = c.run("git rev-parse --short HEAD", hide=True, warn=True)
    manifest = pathlib.Path("dist/QuantAdvisoryTerminal/BUILD_MANIFEST.json")
    manifest.write_text(
        json.dumps(
            {
                "milestone": MILESTONE,
                "commit": (described.stdout or "").strip() or "unknown",
                "short_sha": (short.stdout or "").strip() or "unknown",
                "built_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Build manifest: {manifest} -> {MILESTONE}")


def _run_pyinstaller(c) -> None:
    c.run(
        f'"{sys.executable}" -m PyInstaller '
        "--noconfirm --name QuantAdvisoryTerminal --onedir --windowed "
        "--collect-all hmmlearn --collect-all sklearn --collect-all yfinance "
        "src/qat/app.py"
    )


def _write_build_stamp(c) -> pathlib.Path:
    """Freeze the current commit and date into src/qat/_build_stamp.py.

    The `--dirty` marker is the point of doing this at package time rather than
    reading a version constant: a build made from uncommitted changes is not
    reproducible from the commit it claims, and the operator should be able to
    see that on the Settings screen instead of trusting a label.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))
    from qat.domain.display_dates import format_display_date, format_session_time
    from qat.domain.market_calendar import MARKET_TIMEZONES
    from qat.version import MILESTONE, stamp_module_source

    described = c.run("git describe --tags --always --dirty", hide=True, warn=True)
    commit = (described.stdout or "").strip() or "unknown"
    # Item 50: this used to render UTC on the Settings screen, among fields that
    # are session-local - "built 25/08/2026 12:01 UTC" for a build made at 22:01
    # AEST. The labelled kind rather than the dangerous kind, but it is the same
    # boundary item 40 drew, so it is converted rather than merely labelled.
    #
    # The DATE is taken from the converted value too, not just the time. A build
    # at 14:00 UTC is the following day in Sydney, and a stamp whose date and
    # time disagreed about which zone they were in would be worse than the UTC
    # it replaced.
    now = datetime.now(UTC)
    local = now.astimezone(MARKET_TIMEZONES["ASX"])
    built_at = f"{format_display_date(local)} {format_session_time(now)}"

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


@task(pre=[lint, test, package])
def build(c):
    """Lint, test, and actually PRODUCE the executable.

    It used to be `pre=[lint, test]` with a `pass` body, so it ran the checks
    and built nothing while returning 0 - and `dist/` kept whatever the last
    real `package` left there. On 21 August that returned success on a green
    2,433-test suite while the exe in `dist/` was three hours and eight
    milestones old, and it was caught by reading the file's timestamp rather
    than by anything the command said.

    The name was the whole defect. `invoke build | tail` is already recorded as
    a trap in this project because a pipe hides the exit code; this was the
    same shape one level up, where the exit code was honest and the NAME was
    not.

    Prints what it produced, because "verify the artefact, not the exit code"
    is only actionable if the artefact is named. Unsigned - run `invoke sign`
    afterwards.
    """
    exe = pathlib.Path("dist/QuantAdvisoryTerminal/QuantAdvisoryTerminal.exe")
    if not exe.exists():
        raise Exit(f"package reported success but {exe} does not exist", code=1)
    stamped = datetime.fromtimestamp(exe.stat().st_mtime)
    print(f"\nbuilt: {exe}  {exe.stat().st_size / 1_048_576:.1f} MB  {stamped:%Y-%m-%d %H:%M:%S}")
    print("UNSIGNED - run `invoke sign` before deploying.")
