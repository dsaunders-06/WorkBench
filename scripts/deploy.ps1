# Install the built exe over the working install, and RECORD it (item 29).
#
#   pwsh scripts\deploy.ps1              # dry run - prints the plan, changes nothing
#   pwsh scripts\deploy.ps1 -Apply       # installs, verifies, updates DEPLOYED
#
# Everything is DERIVED - the milestone, the commit, the hash, the rollback
# name. Nothing is typed per deploy, because the one value that WAS typed per
# deploy (`handoff_state.DEPLOYED`) has been wrong ten times: for a day after
# M104, across the whole M130 deploy, two hours after M139, and through every
# deploy of 28 August.
#
# The deploy record is rewritten only AFTER the installed copy is verified, so
# it can never claim a build that is not there.
param([switch]$Apply)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$src  = Join-Path $repo "dist\QuantAdvisoryTerminal"
$dst  = "C:\QuantAdvisoryTerminal"
$py   = Join-Path $repo ".venv\Scripts\python.exe"

Write-Output "=== PRE-FLIGHT ==="

$running = Get-Process | Where-Object { $_.ProcessName -match 'QuantAdvisory' }
if ($running) {
    Write-Output "  REFUSED: the app is running (PID $($running.Id -join ', ')). Close it first."
    Write-Output "           Close it NORMALLY - a clean shutdown is what makes the fill"
    Write-Output "           watermark trustworthy on the next launch."
    exit 1
}
Write-Output "  app not running                      OK"

$exe = Join-Path $src "QuantAdvisoryTerminal.exe"
if (-not (Test-Path $exe)) { Write-Output "  REFUSED: no built exe at $src"; exit 1 }

$sig = Get-AuthenticodeSignature $exe
if ($sig.Status -ne "Valid") {
    Write-Output "  REFUSED: signature is $($sig.Status). Run `invoke sign` first."
    exit 1
}
Write-Output "  built exe signed and Valid           OK"

$hash = (Get-FileHash $exe -Algorithm SHA256).Hash
if (-not (Test-Path $dst)) {
    Write-Output "  REFUSED: no existing install at $dst - this replaces, it does not create"
    exit 1
}

# Derived, never typed. The OUTGOING milestone names the rollback directory, so
# a reader can tell what a .bak actually contains.
Push-Location $repo
$commit    = (git rev-parse --short HEAD).Trim()
# ⚠️ `-join`, not `.Trim()`. A CLEAN tree makes `git status --porcelain`
# return $null, and calling a method on it throws - so the guard against a
# dirty tree crashed on the only state it should permit. The happy path was
# the untested one, which is why the dry run is run before the apply.
$dirty     = (git status --porcelain) -join "`n"
$milestone = ((Select-String -Path "src\qat\version.py" -Pattern '^MILESTONE = "(.+)"').Matches[0].Groups[1].Value)
$outgoing  = (Get-Content "scripts\handoff_state.py" | Select-String -Pattern '^DEPLOYED = "(.+)"').Matches[0].Groups[1].Value
Pop-Location

if ($dirty) {
    Write-Output "  ⚠️ WORKING TREE IS DIRTY - the installed build will not match any commit."
    Write-Output "     Refusing: a deploy whose provenance cannot be stated is not a deploy."
    exit 1
}
Write-Output "  tree clean at $commit ($milestone)   OK"

$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$bak   = "QuantAdvisoryTerminal.bak-$outgoing-$stamp"

Write-Output ""
Write-Output "=== PLAN ==="
Write-Output "  install   $milestone ($commit)"
Write-Output "  sha256    $hash"
Write-Output "  1. rename $dst -> C:\$bak"
Write-Output "  2. copy   $src -> $dst"
Write-Output "  3. verify installed sha256 and signature"
Write-Output "  4. record DEPLOYED = $commit  (was $outgoing)"

if (-not $Apply) {
    Write-Output ""
    Write-Output "DRY RUN - nothing was changed. Re-run with -Apply."
    exit 0
}

Write-Output ""
Write-Output "=== APPLYING ==="
Rename-Item -Path $dst -NewName $bak
Write-Output "  renamed to C:\$bak"
Copy-Item -Path $src -Destination $dst -Recurse
Write-Output "  copied"

$newHash = (Get-FileHash (Join-Path $dst "QuantAdvisoryTerminal.exe") -Algorithm SHA256).Hash
$newSig  = Get-AuthenticodeSignature (Join-Path $dst "QuantAdvisoryTerminal.exe")
Write-Output ""
Write-Output "=== VERIFY THE INSTALLED COPY ==="
Write-Output "  sha256 matches   : $($newHash -eq $hash)"
Write-Output "  signature        : $($newSig.Status)"
if ($newHash -ne $hash -or $newSig.Status -ne "Valid") {
    Write-Output ""
    Write-Output "  ⚠️ INSTALL DID NOT VERIFY. The deploy record was NOT updated."
    Write-Output "     Roll back by renaming C:\$bak back to $dst"
    exit 1
}

# ⚠️ ONLY NOW. The record must never claim a build that is not verified there.
& $py (Join-Path $PSScriptRoot "record_deploy.py") $commit
if ($LASTEXITCODE -ne 0) {
    Write-Output "  ⚠️ INSTALLED, but the deploy record could not be updated - fix it by hand."
    exit 1
}

Write-Output ""
Write-Output "INSTALLED AND RECORDED. Rollback: C:\$bak"
Write-Output "Launch, then read the build stamp off its own log - the copy is not the check."
