<#
    QAT overnight session check - READ ONLY.

    Set-Location "C:\Claude Programming"
    & "C:\Claude Programming\scripts\session_check.ps1"

    INVOKE IT EXACTLY LIKE THAT, WITH NO ARGUMENTS, EVERY TIME.

    That is the entire point of this script. Claude Code stores PowerShell
    permissions as EXACT COMMAND STRINGS, so a command whose text varies between
    runs - an hourly check with the hour in a filter - can never be allowlisted
    and prompts the operator every single time. It offers only "approve once"
    because a durable rule would never match the next command. One fixed string
    can be approved once and then runs unattended.

    Adding a parameter to this script re-breaks that. If a future check needs a
    different window, widen what the script REPORTS rather than what the caller
    passes.

    WHY POWERSHELL AND NOT PYTHON. Two independent reasons, both measured:

      * The Bash tool's sandbox is PER-FILE and covers writes as well as reads.
        It sees equity_curve.csv frozen at 301 rows while PowerShell sees 10,000+,
        yet both see risk_decisions.csv identically - so a spot-check on the
        wrong file confirms Bash is fine and the next read is thousands of rows
        short. A pre-deploy backup run from Bash on 13 August copied 20 files,
        printed success, and wrote nothing to the real filesystem.
      * Settings(_env_file=None).data_dir resolves to the LIVE data directory.
        conftest protects tests; scripts run outside pytest are not protected,
        and two W2 probes wrote a row for a symbol named AAA into the live
        record on 12 August. A script that cannot import qat cannot do that.

    THIS SCRIPT NEVER WRITES. It uses Get-Content, Import-Csv, Get-Process,
    Get-FileHash and Measure-Object, and nothing else. Keep it that way: it runs
    against the live record of a trial whose whole value is that record.

    It reports the CURRENT OR MOST RECENT session, derived from the log rather
    than passed in, so the same invocation serves the bell, the hourly checks,
    the pre-close tighten and the morning brief.

    PowerShell 5.1 compatible - the operator's terminal is 5.1, so no ternary,
    no null-coalescing, no -Parallel.
#>

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$dataDir = Join-Path $env:LOCALAPPDATA 'QuantAdvisoryTerminal\data'
$logPath = Join-Path $dataDir 'logs\qat.log'

function Write-Section($title) {
    Write-Output ''
    Write-Output "=== $title ==="
}

Write-Output "QAT SESSION CHECK   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')   (read only)"
Write-Output "data: $dataDir"

# --- processes -------------------------------------------------------------
Write-Section 'PROCESSES'
$app = Get-Process -Name QuantAdvisoryTerminal -ErrorAction SilentlyContinue
if ($app) {
    foreach ($p in $app) {
        # DAYS, not just hh:mm:ss. A TimeSpan formatted 'hh\:mm\:ss' silently
        # drops its Days component, so a process up 28 hours reported "up
        # 04:04:36" - which reads as a restart four hours ago and sent a reader
        # hunting for a re-adoption that never happened. Measured 18 August.
        $span = (Get-Date) - $p.StartTime
        $up = if ($span.TotalDays -ge 1) {
            '{0}d {1:00}:{2:00}:{3:00}' -f $span.Days, $span.Hours, $span.Minutes, $span.Seconds
        } else {
            $span.ToString('hh\:mm\:ss')
        }
        Write-Output ("app      PID {0,-7} up {1}" -f $p.Id, $up)
    }
} else {
    Write-Output 'app      NOT RUNNING'
}
$watch = Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'watch_session' }
if ($watch) {
    # The venv python.exe is a LAUNCHER that re-execs the base interpreter, so a
    # single watcher shows up as two processes in a parent/child pair. That is
    # one watcher, not two - killing the child stops the watcher.
    Write-Output ("watcher  {0} process(es): {1}   (a venv launcher plus its child is ONE watcher)" -f `
        @($watch).Count, (($watch | ForEach-Object { $_.ProcessId }) -join ', '))
} else {
    Write-Output 'watcher  NOT RUNNING'
}

if (-not (Test-Path $logPath)) {
    Write-Output ''
    Write-Output 'LOG MISSING - nothing further can be checked.'
    exit 0
}

# --- locate the session ----------------------------------------------------
# Bounded tail, then slice from the last "session started". Parsing every line
# of a multi-megabyte log on 5.1 is slow enough to discourage running the check.
$raw = Get-Content $logPath -Tail 20000
$startIndex = -1
for ($i = $raw.Count - 1; $i -ge 0; $i--) {
    if ($raw[$i] -cmatch 'Trading session started') { $startIndex = $i; break }
}
if ($startIndex -lt 0) {
    Write-Output ''
    Write-Output 'No "Trading session started" in the last 20,000 log lines - no session to report.'
    exit 0
}

$rows = @()
foreach ($line in $raw[$startIndex..($raw.Count - 1)]) {
    $obj = $null
    try { $obj = $line | ConvertFrom-Json } catch { continue }
    if ($obj) { $rows += $obj }
}

# ([datetime]$o.ts) is a DateTime, not a string - format it, never .Substring it.
$sessionStart = ([datetime]$rows[0].ts).ToLocalTime()
$sessionStartUtcIso = ([datetime]$rows[0].ts).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss')
$standDown = $rows | Where-Object { $_.message -cmatch 'Trading session stood down' } | Select-Object -Last 1

Write-Section 'SESSION'
Write-Output ("started    {0}" -f $sessionStart.ToString('yyyy-MM-dd HH:mm:ss'))
if ($standDown) {
    Write-Output ("stood down {0}" -f ([datetime]$standDown.ts).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss'))
} else {
    Write-Output 'stood down (still running)'
}
$build = $rows | Where-Object { $_.message -cmatch '^Build:' } | Select-Object -Last 1
if (-not $build) {
    # The build banner is printed at launch, which may precede the session start.
    $build = $raw | Where-Object { $_ -cmatch '"Build: ' } | Select-Object -Last 1 | ForEach-Object {
        try { $_ | ConvertFrom-Json } catch { $null }
    }
}
if ($build) { Write-Output ("build      {0}" -f $build.message) }

# --- the four bell checks --------------------------------------------------
Write-Section 'THE FOUR CHECKS'
$regime = $rows | Where-Object { $_.message -cmatch '^REGIME ' } | Select-Object -First 1
if ($regime) {
    $delay = (([datetime]$regime.ts) - ([datetime]$rows[0].ts)).TotalSeconds
    Write-Output ("1 regime   CLASSIFIED after {0:N0}s: {1}" -f $delay, $regime.message)
} else {
    Write-Output '1 regime   *** NO REGIME PUBLISHED *** every strategy is gating on the sideways DEFAULT'
}
$default = @($rows | Where-Object { $_.message -cmatch 'sideways DEFAULT' })
if ($default.Count -gt 0) {
    $lastDefault = ([datetime]$default[-1].ts).ToLocalTime()
    # THREE cases, not two. `$rows` runs from the last session start to the END
    # of the log, so it also contains any LATER launch's warm-up warnings - and
    # comparing one of those against THIS session's regime publication reported
    # a healthy app as failing at every launch. Measured 15-18 August: it cried
    # wolf on four consecutive launches.
    #
    # A warning only means something went wrong if it landed after the regime
    # published AND before the session stood down. After stand-down it belongs
    # to the next launch, where gating on the default is exactly what warm-up is.
    $regimeAt = if ($regime) { ([datetime]$regime.ts).ToLocalTime() } else { $null }
    $standDownAt = if ($standDown) { ([datetime]$standDown.ts).ToLocalTime() } else { $null }
    if ($standDownAt -and $lastDefault -gt $standDownAt) {
        $note = 'at a LATER launch, before that session opened - normal warm-up'
    } elseif ($regimeAt -and $lastDefault -gt $regimeAt) {
        $note = '*** AFTER the regime published - this is the failure ***'
    } else {
        $note = 'before the open, which is normal and clears at the bell'
    }
    Write-Output ("           {0} sideways-default warning(s), last {1} - {2}" -f `
        $default.Count, $lastDefault.ToString('HH:mm:ss'), $note)
}
$down = @($rows | Where-Object { $_.message -cmatch 'MARKET DATA DOWN' })
Write-Output ("2 feed     MARKET DATA DOWN x{0}" -f $down.Count)
# Searched across the WHOLE tail, not the session slice. Adoption happens at
# LAUNCH, which is always before the bell - scoping this to the session made the
# single most important check unable to pass, every time. Found by running it.
$stops = $null
for ($i = $raw.Count - 1; $i -ge 0; $i--) {
    if ($raw[$i] -cmatch 'carry a stop resting at the broker') {
        try { $stops = $raw[$i] | ConvertFrom-Json } catch { $stops = $null }
        break
    }
}
if ($stops) {
    Write-Output ("3 stops    {0} (at {1})" -f $stops.message, ([datetime]$stops.ts).ToLocalTime().ToString('MM-dd HH:mm:ss'))
} else {
    Write-Output '3 stops    *** NO ADOPTION LINE FOUND *** protection is unverified'
}
$unprot = @($rows | Where-Object { $_.message -cmatch 'POSITION UNPROTECTED' })
Write-Output ("4 unprot   POSITION UNPROTECTED x{0}" -f $unprot.Count)

# --- failures --------------------------------------------------------------
Write-Section 'ERRORS AND HALTS'
$errs = @($rows | Where-Object { $_.level -eq 'ERROR' -or $_.level -eq 'CRITICAL' })
Write-Output ("ERROR/CRITICAL since the bell: {0}" -f $errs.Count)
foreach ($e in $errs) {
    Write-Output ("  {0} {1} {2}" -f ([datetime]$e.ts).ToLocalTime().ToString('HH:mm:ss'), $e.level, $e.message)
}
# The startup window - THIS LAUNCH to the bell - reported separately rather than
# dropped. Scoping errors to the session alone hid a macro fetch failure at
# 23:05 against a 23:30 open, and launch is exactly where startup problems show.
#
# Bounded at the launch banner, not at the top of the tail. Unbounded, this
# walked back to 27 July and printed 1,965 errors from sessions long finished -
# a check nobody would read, which is the same as no check.
$launchIndex = 0
for ($i = $startIndex; $i -ge 0; $i--) {
    if ($raw[$i] -cmatch '"Build: ') { $launchIndex = $i; break }
}
$pre = @()
if ($startIndex -gt $launchIndex) {
    foreach ($line in $raw[$launchIndex..($startIndex - 1)]) {
        if ($line -cmatch '"level":\s*"(ERROR|CRITICAL)"') {
            try { $pre += ($line | ConvertFrom-Json) } catch { continue }
        }
    }
}
Write-Output ("ERROR/CRITICAL between launch and the bell: {0}" -f $pre.Count)
foreach ($e in $pre) {
    Write-Output ("  {0} {1} {2}" -f ([datetime]$e.ts).ToLocalTime().ToString('MM-dd HH:mm:ss'), $e.level, $e.message)
}
$kill = @($rows | Where-Object { $_.message -match 'kill-switch' -and $_.message -notmatch 'kill-switch-engine' })
$recon = @($rows | Where-Object { $_.message -cmatch 'reconciliation mismatch' })
$fills = @($rows | Where-Object { $_.message -cmatch 'BROKER-SIDE FILL' })
Write-Output ("kill-switch mentions: {0}   reconciliation mismatch: {1}" -f $kill.Count, $recon.Count)
Write-Output ("BROKER-SIDE FILL absorbed: {0}" -f $fills.Count)
foreach ($f in $fills) {
    Write-Output ("  {0} {1}" -f ([datetime]$f.ts).ToLocalTime().ToString('HH:mm:ss'), $f.message)
}

# --- staleness -------------------------------------------------------------
# -cmatch, not -match. "excluded from signals" matches a SIGNAL pattern
# case-insensitively, which once inflated a signal count to 42 against a true 0.
Write-Section 'STALENESS'
$out = @($rows | Where-Object { $_.message -cmatch 'excluded from signals' })
$back = @($rows | Where-Object { $_.message -cmatch 'is printing again after' })
Write-Output ("excluded {0}   printing again {1}" -f $out.Count, $back.Count)
if ($out.Count -gt 0) {
    $outSym = $out | ForEach-Object { ($_.message -split ' ')[0] }
    $backSym = @($back | ForEach-Object { ($_.message -split ' ')[0] })
    $never = @($outSym | Where-Object { $backSym -notcontains $_ } | Sort-Object -Unique)
    if ($never.Count -gt 0) {
        Write-Output ("  STILL EXCLUDED: {0}" -f ($never -join ', '))
    } else {
        Write-Output '  every excluded symbol printed again'
    }
}

# --- the audit trail, which the log does not show --------------------------
# qat.log is NOT a complete view of decision activity. Hourly checks once
# reported "0 signals, 0 refusals" all night while risk_decisions.csv held 108
# position-limit refusals on AXP. Read both, every time.
Write-Section 'AUDIT TRAIL (risk_decisions.csv - NOT visible in the log)'
$rdPath = Join-Path $dataDir 'risk_decisions.csv'
$rd = @(Import-Csv $rdPath | Where-Object { $_.timestamp -ge $sessionStartUtcIso })
Write-Output ("decisions this session: {0}   (file total {1})" -f `
    $rd.Count, ((Get-Content $rdPath | Measure-Object -Line).Lines - 1))
if ($rd.Count -gt 0) {
    $approved = @($rd | Where-Object { $_.approved -eq 'True' })
    Write-Output ("approved {0}   refused {1}" -f $approved.Count, ($rd.Count - $approved.Count))
    Write-Output ''
    Write-Output ("{0,-8}{1,7}  {2,-8} {3,-8} {4}" -f 'symbol', 'count', 'first', 'last', 'reason')
    foreach ($g in ($rd | Group-Object symbol | Sort-Object Count -Descending)) {
        $s = $g.Group | Sort-Object timestamp
        $reason = $s[0].reason
        if ($reason.Length -gt 62) { $reason = $reason.Substring(0, 62) }
        Write-Output ("{0,-8}{1,7}  {2,-8} {3,-8} {4}" -f `
            $g.Name, $g.Count, $s[0].timestamp.Substring(11, 8), $s[-1].timestamp.Substring(11, 8), $reason)
    }
}

# --- ledgers ---------------------------------------------------------------
Write-Section 'LEDGERS'
foreach ($f in 'closed_trades.csv', 'decision_journal.csv', 'risk_decisions.csv', 'equity_curve.csv') {
    $p = Join-Path $dataDir $f
    if (Test-Path $p) {
        $n = (Get-Content $p | Measure-Object -Line).Lines - 1
        Write-Output ("{0,-22} {1,7} rows   modified {2}" -f $f, $n, (Get-Item $p).LastWriteTime.ToString('MM-dd HH:mm:ss'))
    } else {
        Write-Output ("{0,-22}   MISSING" -f $f)
    }
}
$ctPath = Join-Path $dataDir 'closed_trades.csv'
Write-Output ("closed_trades sha256   {0}" -f (Get-FileHash $ctPath -Algorithm SHA256).Hash)
$ct = @(Import-Csv $ctPath | Where-Object { $_.closed_at -ge $sessionStartUtcIso })
if ($ct.Count -gt 0) {
    Write-Output ''
    Write-Output "*** NEW CLOSED TRADE(S) THIS SESSION - {0} ***" -f $ct.Count
    $ct | Format-List | Out-String | Write-Output
} else {
    Write-Output 'no closed trades this session'
}

# --- equity ----------------------------------------------------------------
Write-Section 'EQUITY'
$eq = @(Import-Csv (Join-Path $dataDir 'equity_curve.csv') | Where-Object { $_.ts -ge $sessionStartUtcIso })
# Bounded at stand-down once the session has ended. The monitor keeps polling
# the broker after the close - positions are marked through post-market and the
# next pre-market - so an unbounded "latest" silently rewrites the session's P&L
# every time the check is re-run.
if ($standDown) {
    $endUtcIso = ([datetime]$standDown.ts).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss')
    $eq = @($eq | Where-Object { $_.ts -le $endUtcIso })
    $label = 'close'
} else {
    $label = 'latest'
}
if ($eq.Count -gt 0) {
    $delta = [double]$eq[-1].equity - [double]$eq[0].equity
    Write-Output ("open {0}   {1} {2}   change {3:N2}" -f $eq[0].equity, $label, $eq[-1].equity, $delta)
    Write-Output ("cash open {0}   cash {1} {2}   (cash unchanged means nothing traded)" -f $eq[0].cash, $label, $eq[-1].cash)
} else {
    Write-Output 'no equity samples in this session window'
}

# --- daily report ----------------------------------------------------------
Write-Section 'DAILY REPORT'
$report = $rows | Where-Object { $_.message -cmatch 'Daily report' } | Select-Object -Last 1
if ($report) {
    Write-Output ("{0} {1}" -f ([datetime]$report.ts).ToLocalTime().ToString('HH:mm:ss'), $report.message)
} else {
    Write-Output 'no daily-report line in this session (expected before ~06:05)'
}

Write-Output ''
Write-Output 'EXPECTED, NOT A FAULT: zero new entries while the aggregate cap is breached and the book is 10 of 10;'
Write-Output 'a staleness burst at the bell that clears; repeated position-limit refusals on one symbol; CRWD'
Write-Output 'corporate action in M39 shadow mode with no SHADOW: or ADJUSTED: line following it.'
