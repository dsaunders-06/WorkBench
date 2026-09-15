# Audit evidence pack: re-run every read-only audit tool and hash every source.
#
#   & "C:\Claude Programming\docs\audit\2026-09-design-recovery\tools\reproduce_evidence.ps1" `
#       -OutDir "$env:USERPROFILE\Documents\QAT-audit-evidence\2026-09-15-final"
#
# Read-only against QAT: it reads the data folder, the logs, the transcripts,
# the IBKR statements and git, and writes ONLY into -OutDir (which must not
# exist yet). PowerShell, not Bash: the Bash sandbox serves a stale copy of
# %LOCALAPPDATA% (HANDOFF, "THE ONE RULE").
#
# The IBKR statement's text is extracted with pdftotext into a temporary
# folder that is deleted afterwards. The statement and its text are never
# written to -OutDir or to the repository (personal details).
#
# Output:
#   tool-outputs\<tool>.txt   one per tool run
#   MANIFEST.csv              sha256 of every tool output
#   SOURCES.csv               sha256 of every source the audit relied on
#   RUN.txt                   git HEAD, time, and the exact commands run

param(
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$Repo = "C:\Claude Programming"
)
# The start dates are the ones each log tool was run with when its section
# was drafted (transcript 0660d19e, 14 Sep): the kill-switch table in R9
# counts from the first live order, the others from the ASX move.
$SinceLive = "2026-08-24"
$SinceAsx = "2026-08-19"
$SinceSeries = "2026-08-18"
$ErrorActionPreference = "Stop"
if (Test-Path -LiteralPath $OutDir) { throw "OutDir already exists: $OutDir (refusing to overwrite evidence)" }

$py = Join-Path $Repo ".venv\Scripts\python.exe"
$audit = Join-Path $Repo "docs\audit\2026-09-design-recovery"
$data = Join-Path $env:LOCALAPPDATA "QuantAdvisoryTerminal\data"
$logs = Join-Path $data "logs"
$transcripts = Join-Path $env:USERPROFILE ".claude\projects\C--Claude-Programming"
$statements = Join-Path $env:USERPROFILE "Documents\QAT-audit-evidence\2026-09-12\broker-statements"
$pdftotext = "C:\Program Files\Git\mingw64\bin\pdftotext.exe"

New-Item -ItemType Directory -Force (Join-Path $OutDir "tool-outputs") | Out-Null
$outputs = Join-Path $OutDir "tool-outputs"
$tmp = Join-Path $env:TEMP ("qat-audit-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $tmp | Out-Null
$stmtText = Join-Path $tmp "statement.txt"
& $pdftotext -raw (Join-Path $statements "DUQ200898_20260824_20260911.pdf") $stmtText

$runs = @(
    @{ n = "s07_rails_by_day";        a = @("$audit\s07-s13-risk-and-interactions\tools\rails_by_day.py", $data) },
    @{ n = "s07_risk_per_trade";      a = @("$audit\s07-s13-risk-and-interactions\tools\risk_per_trade.py", $data) },
    @{ n = "s07_gate_and_halts";      a = @("$audit\s07-s13-risk-and-interactions\tools\gate_and_halts.py", $logs, $SinceLive) },
    @{ n = "s13_aggregate_series";    a = @("$audit\s07-s13-risk-and-interactions\tools\aggregate_series.py", $logs, $SinceSeries) },
    @{ n = "s13_evidence_chain";      a = @("$audit\s07-s13-risk-and-interactions\tools\evidence_chain.py", $data) },
    @{ n = "s08_execution_evidence";  a = @("$audit\s08-s14-execution-and-incidents\tools\execution_evidence.py", $logs, $SinceAsx) },
    @{ n = "s14_incident_episodes";   a = @("$audit\s08-s14-execution-and-incidents\tools\incident_episodes.py", $logs, $SinceAsx) },
    @{ n = "s09_ai_evidence";         a = @("$audit\s09-s10-ai-and-regime\tools\ai_evidence.py", $data) },
    @{ n = "s10_regime_evidence";     a = @("$audit\s09-s10-ai-and-regime\tools\regime_evidence.py", $data) },
    @{ n = "s11_ledger_vs_broker";    a = @("$audit\s11-evidence-integrity\tools\ledger_vs_broker.py", $stmtText, $data) },
    @{ n = "s11_ledger_versions";     a = @("$audit\s11-evidence-integrity\tools\ledger_versions.py", $data) },
    @{ n = "s12_complexity_inventory"; a = @("$audit\s12-s16-complexity\tools\complexity_inventory.py", $Repo) },
    @{ n = "bf_doc_incidents";        a = @("$audit\backfill\tools\doc_incidents.py", $Repo) },
    @{ n = "bf_operator_corrections"; a = @("$audit\backfill\tools\operator_corrections.py", $transcripts) },
    @{ n = "bf_error_log_table";      a = @("$audit\backfill\tools\error_log_table.py", $Repo) },
    @{ n = "chronology";              a = @("$audit\s-chronology\tools\chronology.py", $Repo) }
)
$log = @("git HEAD: " + (git -C $Repo rev-parse HEAD), "run at: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"), "")
foreach ($r in $runs) {
    $out = Join-Path $outputs ($r.n + ".txt")
    & $py @($r.a) *> $out
    $log += "{0}  exit {1}  python {2}" -f $r.n, $LASTEXITCODE, ($r.a -join " ").Replace($stmtText, "<statement text, temporary>")
}
# The two tools that write their own output file.
& $py "$audit\backfill\tools\fix_commits.py" $Repo (Join-Path $outputs "bf_fix_commits.csv") *> (Join-Path $outputs "bf_fix_commits.txt")
$log += "bf_fix_commits  exit $LASTEXITCODE"
& $py "$audit\stage4\tools\ask_answers.py" (Join-Path $outputs "stage4_ask_answers.txt") *> (Join-Path $outputs "stage4_ask_answers.log")
$log += "stage4_ask_answers  exit $LASTEXITCODE"
& $py "$audit\stage4\tools\operator_messages.py" (Join-Path $outputs "stage4_operator_messages.txt") *> (Join-Path $outputs "stage4_operator_messages.log")
$log += "stage4_operator_messages  exit $LASTEXITCODE"

Remove-Item -LiteralPath $tmp -Recurse -Force
$log | Set-Content (Join-Path $OutDir "RUN.txt") -Encoding utf8

# Hash every tool output.
Get-ChildItem -LiteralPath $outputs -File | ForEach-Object {
    [pscustomobject]@{ file = "tool-outputs\" + $_.Name; bytes = $_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
} | Export-Csv (Join-Path $OutDir "MANIFEST.csv") -NoTypeInformation -Encoding utf8

# Hash every source relied on: the data folder (records, backups, reports),
# the logs, the statements, the transcripts.
$sources = @()
foreach ($dir in @($data, $logs, $statements, $transcripts)) {
    Get-ChildItem -LiteralPath $dir -File | Where-Object { $_.Extension -ne ".tmp" } | ForEach-Object {
        $sources += [pscustomobject]@{ source = $_.FullName; bytes = $_.Length; modified = $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss"); sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    }
}
$sources | Export-Csv (Join-Path $OutDir "SOURCES.csv") -NoTypeInformation -Encoding utf8
"tool outputs: " + (Get-ChildItem -LiteralPath $outputs -File).Count + "; sources hashed: " + $sources.Count
