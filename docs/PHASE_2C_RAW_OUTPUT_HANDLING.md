# Phase 2C raw simulation output handling

The [F1 diagnostic summary](PHASE_2C_DEPENDENCE_DIAGNOSTIC.md) is the compact
review record. These two existing JSON artifacts remain tracked and in place:

| Existing artifact | SHA-256 |
| --- | --- |
| `PHASE_2C_DEPENDENCE_DIAGNOSTIC_RESULTS.json` | `d34ae486097bbeb835fe84bc1153d2f1f67831367c26d709874b8b350a8318a7` |
| `PHASE_2C_DEPENDENCE_DIAGNOSTIC_RAW_KERNEL_RESULTS.json` | `b82ee9842979113134a4bf20581959b79bc792951748e9e94d33e1a7706bee0d` |

Future raw simulation outputs go to a directory outside the worktree. The
repository ignores `raw-simulation-outputs/`, `raw_simulation_outputs/`, and
raw-result filenames. Commit the compact summary and output hashes after each
run; do not add another per-draw JSON to the repository.

Regenerate the historical diagnostic into a temporary directory from this
worktree with the following PowerShell commands. The script SHA-256 for the
historical run was `f458dcf5eca0d222c567ea6e2c650b92970e2831405a6c74ffea852be5f01209`; a changed script may change results.

```powershell
$rawOutput = Join-Path $env:TEMP 'phase2c-raw-simulation-outputs'
New-Item -ItemType Directory -Force -Path $rawOutput | Out-Null
.\.venv\Scripts\python.exe scripts/research/diagnose_swing_dependence.py --output (Join-Path $rawOutput 'PHASE_2C_DEPENDENCE_DIAGNOSTIC_RESULTS.json')
.\.venv\Scripts\python.exe scripts/research/diagnose_swing_dependence.py --raw-kernel --output (Join-Path $rawOutput 'PHASE_2C_DEPENDENCE_DIAGNOSTIC_RAW_KERNEL_RESULTS.json')
Get-FileHash (Join-Path $rawOutput 'PHASE_2C_DEPENDENCE_DIAGNOSTIC_RESULTS.json') -Algorithm SHA256
Get-FileHash (Join-Path $rawOutput 'PHASE_2C_DEPENDENCE_DIAGNOSTIC_RAW_KERNEL_RESULTS.json') -Algorithm SHA256
```

Runtime metadata, such as cell seconds and wall seconds, varies across runs,
so the complete JSON file hash is an identity for the stored artifact, not a
claim that a rerun will be byte-identical. The per-cell attempt and retained
p-value digests inside each JSON allow comparison of the simulation results.
