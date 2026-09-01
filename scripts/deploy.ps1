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

# ⚠️ IS THE BUILD ACTUALLY FROM HEAD? Found on this script's own first dry run:
# it planned to record HEAD while the exe had been built two commits earlier, so
# the deploy record would have named a commit that was not what was installed -
# item 29's exact failure with a new cause, in item 29's own fix.
#
# The exe's mtime against HEAD's commit time is the cheap, checkable form of
# "was this built from what you are about to record".
$exeTime  = (Get-Item $exe).LastWriteTime
$headTime = [datetime]::Parse((git show -s --format=%cI HEAD))
if ($exeTime -lt $headTime) {
    Write-Output "  ⚠️ THE BUILD PREDATES HEAD."
    Write-Output "     exe built : $($exeTime.ToString('yyyy-MM-dd HH:mm:ss'))"
    Write-Output "     HEAD      : $($headTime.ToString('yyyy-MM-dd HH:mm:ss'))  $commit"
    Write-Output "     Recording $commit would name a commit this exe was not built from."
    Write-Output "     Run ``invoke build`` and ``invoke sign`` again, then retry."
    exit 1
}
Write-Output "  build is at or after HEAD            OK"

# ⚠️ THE MTIME CHECK ABOVE IS A PROXY, AND SIGNING DEFEATS IT. `invoke sign`
# REWRITES the exe, so an exe built from commit A, left in dist while commit B
# is made, and then signed, gets an mtime NEWER than HEAD and sails through -
# while the binary is still A. Copying an old exe into dist does the same.
#
# The manifest is not a proxy: `invoke package` writes it beside the exe, after
# PyInstaller succeeds, from the same MILESTONE and commit the build stamp is
# frozen with. A failed build leaves none.
#
# Added 1 September 2026 after dist was found holding a 31/08 16:10 exe -
# byte-identical to the installed M159 - while the handover recorded M160 as
# "BUILT" and M160's source had landed at 17:18. The mtime guard did catch that
# one. This closes the case it cannot see.
$manifestPath = Join-Path $src "BUILD_MANIFEST.json"
if (-not (Test-Path $manifestPath)) {
    Write-Output "  ⚠️ NO BUILD_MANIFEST.json IN $src"
    Write-Output "     This exe was not produced by a current ``invoke package``, so nothing"
    Write-Output "     outside it can say which source it came from - and the label about to"
    Write-Output "     be recorded is derived from HEAD, not from the binary."
    Write-Output "     Run ``invoke build`` and ``invoke sign``, then retry."
    exit 1
}
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
if ($manifest.milestone -ne $milestone -or $manifest.short_sha -ne $commit) {
    Write-Output "  ⚠️ THE BUILD IS NOT FROM THE SOURCE ABOUT TO BE RECORDED."
    Write-Output "     manifest : $($manifest.milestone) ($($manifest.short_sha)) built $($manifest.built_at)"
    Write-Output "     recording: $milestone ($commit)"
    Write-Output "     Installing this would put one build on disk under another's name -"
    Write-Output "     which is what DEPLOYED being wrong ten times looked like."
    Write-Output "     Run ``invoke build`` and ``invoke sign``, then retry."
    exit 1
}
Write-Output "  manifest matches $milestone ($commit)  OK"

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
