# QAT Design Recovery & Design Intent Audit, Annex B: Evidence Index

> **Final report annex, issued 15 September 2026** for the operator's review (Checkpoint B).

Every source the audit relied on, where it is kept, its sha256, and the
sections that use it. Every tool the audit ran, what it reads, the exact
command, and the file its output was archived to.

## B.1 The final evidence pack

**Location:** `Documents\QAT-audit-evidence\2026-09-15-final\`, outside the
repository.

**How it was made:** `tools/reproduce_evidence.ps1` re-ran every repeatable
audit tool against the records as they stand on 15 Sep, at 14:04 AEST, at
git HEAD `7feb11e` (the commit holding the final tools). Every tool exited 0.

**Three earlier runs were superseded**, and are kept in
`2026-09-15-final-superseded\` (CE-067):
* `run1-1350`: all four log tools given one start date, 19 Aug. Two had been
  run from other dates when their sections were drafted;
* `run2-1356`: the transcript tools still counted Claude's own compaction
  summaries as the operator's messages, and `ledger_versions.py` printed
  its rows in an order that changes from run to run (same content);
* `run3-1401`: the tools fixed, but not yet committed.

The pack holds:
* `tool-outputs\`: one file per tool run (B.3);
* `MANIFEST.csv`: the sha256 of every tool output;
* `SOURCES.csv`: the sha256, size and modified time of every source file
  (89 files; B.4);
* `RUN.txt`: git HEAD, the time and the exact commands.

**To reproduce** (PowerShell; read-only against QAT; refuses an existing
folder):

```powershell
& "C:\Claude Programming\docs\audit\2026-09-design-recovery\tools\reproduce_evidence.ps1" -OutDir "$env:USERPROFILE\Documents\QAT-audit-evidence\<new folder>"
```

**The re-run reproduces the report's figures.** QAT's records have not
changed since the last session on 12 Sep (B.4: no record or log file is
modified after 12 Sep 11:19). Checked against the re-run outputs:
* the cash cap cut 18 of 20 proposals; risk taken min 0.13%, median 0.45%,
  max 0.70% (R9 §9.2);
* TNE: ledger net −139.17 against the broker's −7,076.61, a difference of
  +6,937.44 (R13 §13.2);
* 184 modules and 51,473 physical lines (R15 §15.1);
* 1,404 operator messages, 62 with a correction cue, once the tool excludes
  Claude's own compaction summaries (Annex C's correction note; CE-067);
* 67 error-log entries, 21 of them in the audit period: the back-fill's 66
  and CE-067, added at finalisation (Annex C);
* the drift items by period, 39 / 8 / 4 / 8 (Part I).

**Two outputs that change with time, by design:**
* `bf_fix_commits` and `chronology` count every commit, so they include the
  audit's own later commits: 986 at `7feb11e`, against 951 up to the
  deployed build (R2 §2.1).
* `stage4_operator_messages` and `stage4_ask_answers` read every transcript,
  including this audit's own sessions. Their counts grow as the audit
  continues. The authority register (`stage4/authority-evidence.md`) cites
  the operator's words by transcript and time, which do not change.

**Not in the pack:**
* the IBKR statements and the chat export (personal details). The
  statements' text was extracted into a temporary folder, read by
  `ledger_vs_broker.py`, then deleted. Only the statements' hashes are
  recorded (B.4);
* the four interactive transcript helpers (`condense.py`, `find_brief.py`,
  `transcript_spans.py`, `window.py`). They take a passage or a time window
  as arguments and were used to locate the operator's words. What they found
  is quoted, with transcript and time, in `stage4/authority-evidence.md` and
  the investigators' reports;
* the four investigators' reports (`stage3/`), which were written by
  fresh-context agents and are kept verbatim in the repository.

## B.2 The earlier dated snapshots

Each was taken when a stage was committed, with its own `MANIFEST.csv`, in
`Documents\QAT-audit-evidence\`. After the baseline, each is a copy of the
audit's own session transcripts at that point, so that the record of how
each section was made survives Claude Code's clean-up.

| Folder | Files | What it holds |
|---|---|---|
| `2026-09-12` | 466 | the baseline: 454 transcripts, the 7 log files, the claude.ai chat export, the 2 IBKR statements, the manifest and a README |
| `2026-09-14` | 2 | transcript `ede4fc1d` (the brief, 12 Sep, to Checkpoint A) |
| `2026-09-14-stage4` | 3 | `ede4fc1d`, `df2c900c` (the authority register) |
| `2026-09-14-s07-s14` | 3 | `df2c900c`, `0660d19e` (R9, R10, R14) |
| `2026-09-15` | 3 | `0660d19e`, `9b9d429c` (R11, R12) |
| `2026-09-15-s11` | 2 | `9b9d429c` (R13) |
| `2026-09-15-s12-s16` | 3 | `9b9d429c`, `a7821bbf` (R15, R20) |
| `2026-09-15-report-drafted` | 2 | `a7821bbf` (R1–R24 first drafted) |
| `2026-09-15-final` | 25 | this pack (B.1) |
| `2026-09-15-final-superseded` | 75 | the three superseded runs of the pack (B.1), kept |
| `2026-09-15-finalised` | 3 | `a7821bbf`, `9b9d429c` at 14:13, after the compiled report was committed (`4a11381`): the record of the finalisation itself |

Each count includes the folder's manifest. The QAT records themselves are
not copied: they are unchanged since 12 Sep, and their hashes are in B.4.

## B.3 The tools and their outputs

Every tool is read-only, lint-clean (ruff, black), and kept beside the
section it serves. `<data>` is `%LOCALAPPDATA%\QuantAdvisoryTerminal\data`,
`<logs>` is `<data>\logs`, `<transcripts>` is
`~\.claude\projects\C--Claude-Programming`, `<repo>` is
`C:\Claude Programming`. The log tools' start dates are the ones each was
run with when its section was drafted, recovered from the drafting
transcript (`0660d19e`, 14 Sep).

| Tool | Reads | Command | Output | Used in |
|---|---|---|---|---|
| `s07-s13-risk-and-interactions/tools/rails_by_day.py` | the data folder's records | `rails_by_day.py <data>` | `s07_rails_by_day.txt` | R9 |
| `s07-s13-risk-and-interactions/tools/risk_per_trade.py` | `risk_decisions.csv`, `decision_journal.csv` | `risk_per_trade.py <data>` | `s07_risk_per_trade.txt` | R9 §9.2, R12, R16 |
| `s07-s13-risk-and-interactions/tools/gate_and_halts.py` | the log | `gate_and_halts.py <logs> 2026-08-24` | `s07_gate_and_halts.txt` | R9, R10, R14 |
| `s07-s13-risk-and-interactions/tools/aggregate_series.py` | the log | `aggregate_series.py <logs> 2026-08-18` | `s13_aggregate_series.txt` | R9, R16 §16.1 |
| `s07-s13-risk-and-interactions/tools/evidence_chain.py` | `closed_trades.csv` | `evidence_chain.py <data>` | `s13_evidence_chain.txt` | R9, R10, R13, R16 |
| `s08-s14-execution-and-incidents/tools/execution_evidence.py` | the log | `execution_evidence.py <logs> 2026-08-19` | `s08_execution_evidence.txt` | R10, R14 |
| `s08-s14-execution-and-incidents/tools/incident_episodes.py` | the log | `incident_episodes.py <logs> 2026-08-19` | `s14_incident_episodes.txt` | R10, R14 |
| `s09-s10-ai-and-regime/tools/ai_evidence.py` | the log, `daily_reports.md`, `weekly_reports.md` | `ai_evidence.py <data>` | `s09_ai_evidence.txt` | R11 |
| `s09-s10-ai-and-regime/tools/regime_evidence.py` | the log, `risk_decisions.csv`, `closed_trades.csv` | `regime_evidence.py <data>` | `s10_regime_evidence.txt` | R12, R13 |
| `s11-evidence-integrity/tools/ledger_vs_broker.py` | the IBKR statement's text, `closed_trades.csv`, `open_position_entries.json` | `ledger_vs_broker.py <statement text> <data>` | `s11_ledger_vs_broker.txt` | R13 |
| `s11-evidence-integrity/tools/ledger_versions.py` | `closed_trades.csv` and its 12 backups | `ledger_versions.py <data>` | `s11_ledger_versions.txt` | R13 §13.5 |
| `s12-s16-complexity/tools/complexity_inventory.py` | `src/` | `complexity_inventory.py <repo>` | `s12_complexity_inventory.txt` | R15, R17, R20 |
| `backfill/tools/fix_commits.py` | git history | `fix_commits.py <repo> <out.csv>` | `bf_fix_commits.csv`, `.txt` | Annex C |
| `backfill/tools/doc_incidents.py` | HANDOFF, its archive, ROADMAP | `doc_incidents.py <repo>` | `bf_doc_incidents.txt` | Annex C |
| `backfill/tools/operator_corrections.py` | the transcripts | `operator_corrections.py <transcripts>` | `bf_operator_corrections.txt` | Annex C |
| `backfill/tools/error_log_table.py` | the error log | `error_log_table.py <repo>` | `bf_error_log_table.txt` | Annex C, Part I |
| `s-chronology/tools/chronology.py` | R7's drift table, git, the error log | `chronology.py <repo>` | `chronology.txt` | Part I |
| `stage4/tools/operator_messages.py` | the transcripts | `operator_messages.py <out>` | `stage4_operator_messages.txt` | R4, R6, R7 (via `stage4/authority-evidence.md`) |
| `stage4/tools/ask_answers.py` | the transcripts | `ask_answers.py <out>` | `stage4_ask_answers.txt` | R4, R6, R7 (via the register) |

The sha256 of each output, from `MANIFEST.csv`:

<!-- TABLE:outputs -->
| Output | Bytes | sha256 |
|---|---|---|
| `tool-outputs/bf_doc_incidents.txt` | 29,399 | `07BB386318F6A56CE6C918F621EFA50910A9C180EE954DF870C600716A7C08FC` |
| `tool-outputs/bf_error_log_table.txt` | 9,020 | `28ACF75AC148C11D40D095FB4D8A14A93C41ACE22290E48EA68526B9F385BFF9` |
| `tool-outputs/bf_fix_commits.csv` | 95,027 | `2678B8E3E3420D9E08B58D2CD4FC0C7F0C19C9AFAA8B94B8EDE54B93ABC6FFDD` |
| `tool-outputs/bf_fix_commits.txt` | 556 | `CBA95783C91504289A44BFCAD107C73A0D3972129B5F5D4118C6E1D0D9166D5F` |
| `tool-outputs/bf_operator_corrections.txt` | 23,506 | `F90D5AE8382D502764FD61B51B0494C77A2653464E165AE5ED1F6DDBE53CB646` |
| `tool-outputs/chronology.txt` | 14,133 | `0C310A5D3679072DEC7CCB5DF15B3D04764A5A5C4EA8FAB73B6AD8E6CD6183B4` |
| `tool-outputs/s07_gate_and_halts.txt` | 9,682 | `356572B67630DAE248484215FD6CE92F766C7C2A46FAE55753110CE10086AF1E` |
| `tool-outputs/s07_rails_by_day.txt` | 4,419 | `2552266EDECD99AD1AB37AE379F677C7DB19A8F4D9C63BB967C5C32B81C05574` |
| `tool-outputs/s07_risk_per_trade.txt` | 4,366 | `EBE8B2E2D9BE6D96A3FC0E4EDBEBE6AED99F230C401A9E177FE6EC0970FC2A08` |
| `tool-outputs/s08_execution_evidence.txt` | 5,224 | `8DE68A98C49D7E6A2CA6A66B2FF94BEF51478DE8A88694B29164FB0E45B0B897` |
| `tool-outputs/s09_ai_evidence.txt` | 1,732 | `12D8B62D36FE9A1EB5E0BECAF424E1944C21E9D90C96D9201E27F5A14275AD99` |
| `tool-outputs/s10_regime_evidence.txt` | 17,238 | `0B26D442B9C7C5582B125664B149569048FBB09122C6F0F925AAD5EE30CCF38B` |
| `tool-outputs/s11_ledger_versions.txt` | 16,357 | `F64426C7DD7E20C786547F303C4D08D53DF42080EC6A81485CEB7420C0C9646E` |
| `tool-outputs/s11_ledger_vs_broker.txt` | 9,396 | `F38BC5160AC60E5B906D28ADD4CA2352860BBBC41E8C2514B07BE09B8DEE99E7` |
| `tool-outputs/s12_complexity_inventory.txt` | 5,336 | `C6C44B9F1DF210E180FE260F78C79CE91C8411BDFB82D2A079F503887BA0ECF3` |
| `tool-outputs/s13_aggregate_series.txt` | 3,519 | `EFE66691A4F4C51C6ABA71C212F874691393556D288AFE5D73800BF95736593C` |
| `tool-outputs/s13_evidence_chain.txt` | 1,723 | `61F6A02BB3B23595EDFA9EE6B0B288BF338877ED49671E6BE45C14C0CC4E18D4` |
| `tool-outputs/s14_incident_episodes.txt` | 1,469 | `4F3E072A1BDE0D453DCE961A31EE96FD065AD4969FFECC33249A7E1FD717CEE6` |
| `tool-outputs/stage4_ask_answers.log` | 13 | `7BB53FD9B93CA1607DC7B31E9E707E60E2E2831CFD81B1A1B95F3727BC2B6A95` |
| `tool-outputs/stage4_ask_answers.txt` | 209,248 | `ACBCA4220C8EBA5839F01B2B3BEADDB4AD0D3BF434D26E4AC78191814048CAFC` |
| `tool-outputs/stage4_operator_messages.log` | 15 | `75DBE95ECDCEA6C7A27C6499EC3DC0BF5222684627D372F73CCA5754BC56E380` |
| `tool-outputs/stage4_operator_messages.txt` | 878,132 | `5109CACED1B908F2FA6ACB1032359AF291F0A60B59529EA3DF41BA995B2541E9` |
<!-- /TABLE:outputs -->

## B.4 The sources

### QAT's records (`<data>`)

The ledger's hash, `688B7091…`, is the one the handover has checked at the
start of every session since 12 Sep. The file names ending `.bak-…` are the
27 backups; R13 §13.5 traces the seven ledger repairs through them.

<!-- TABLE:records -->
| File | Bytes | Modified | sha256 |
|---|---|---|---|
| `absorbed_fills.json` | 3,695 | 2026-09-12 11:16:09 | `3437AABF882ABE5F38E2920C2B922BCDEF0CAF904DC9FD859B9D1DFAE0E9B0A5` |
| `absorbed_fills.json.bak-20260821-175933` | 835 | 2026-08-21 12:16:56 | `8F38FEF0610AA927B2122E4A5C44CEC39247DE123AFE8BE04ED3C663EB9B637E` |
| `absorbed_fills.json.bak-20260826-150939-PRE-LOV-REPAIR` | 2,583 | 2026-08-26 15:08:16 | `7A6AC5560EA0B35CCB822AFFAD837EFE9CCA92D4D9B5F522B8A2C4CBC56534F5` |
| `closed_trades.bak-preRowRepair-52596.csv` | 1,673 | 2026-08-27 17:04:09 | `55ED5CAAD31637485C290D6D629F45BD808208D3716F0682E3B152D4ECB225DF` |
| `closed_trades.csv` | 3,094 | 2026-09-12 10:52:53 | `688B709185CB1F8FEF552B6AF57FB00FE195C2488003EA95A0C05D70C70C7669` |
| `closed_trades.csv.bak-20260806-084823` | 690 | 2026-08-06 00:18:05 | `9ACCD53E7A3B1A98F2C63E2DC20EF13F1BEE6AF2FFFA2CA2149B4A1C3101D4BC` |
| `closed_trades.csv.bak-20260812-084430-POST-correction` | 651 | 2026-08-12 08:37:02 | `C060F7151511BCA18ACDB44A0F7C88E9ECE71DCDB24C6B4719FAA3D76FF69B7C` |
| `closed_trades.csv.bak-20260821-175452` | 651 | 2026-08-12 08:37:02 | `C060F7151511BCA18ACDB44A0F7C88E9ECE71DCDB24C6B4719FAA3D76FF69B7C` |
| `closed_trades.csv.bak-20260824-152809-PRE-IMPOSSIBLE-TRADE-REPAIR` | 1,943 | 2026-08-24 15:24:31 | `08C2CB33CFAF57A493FD41A3B5E2D27136165B707429A93618AE3D5600F82BC2` |
| `closed_trades.csv.bak-20260826-150939-PRE-LOV-REPAIR` | 1,162 | 2026-08-26 10:09:42 | `E934FFA58B3E5EF0B24F78E915EA0494703AC9EE186734EA0D4805677A2AAA6B` |
| `closed_trades.csv.bak-20260904-134521` | 2,316 | 2026-09-04 13:42:33 | `DDFEF77E533E45894F04FA7352F1B27C4A77BD8C8939B05F4FB1427CE6A4E5AC` |
| `closed_trades.csv.bak-20260909-132411` | 2,526 | 2026-09-09 13:19:17 | `82043D01E75F0D39AEBD8F4B10D77CB1D62F8ECF115FFEFC5A24F940D036D1EB` |
| `closed_trades.csv.bak-20260910-045239-precision` | 2,750 | 2026-09-09 17:18:00 | `CB4703C72DA4E7E00FA12A34B9BAB2A78F2D0CDE5C310827A52974DD429B6A07` |
| `closed_trades.csv.bak-fill-basis-20260912-105253` | 3,007 | 2026-09-11 10:03:22 | `88C259859AAA4FF3E936A171D44A53FD20583C2BB6068218584D0F1C5F0107C6` |
| `closed_trades.csv.bak-repair-20260909-071800` | 2,967 | 2026-09-09 14:59:40 | `7195E75E7688D4527D0F46502457E05907E404BF52DCFC1140C23AFE4466D84A` |
| `closed_trades.mnst.bak-20260811-081723` | 658 | 2026-08-12 08:18:56 | `3836F4324ADEFD62D82F0019ECB36AA05646CCAA9575760DCAB4BE0D2B8E5FDB` |
| `corporate_announcements.json` | 25 | 2026-08-20 19:47:53 | `AA8ACA345812595142E0A37D2084E825377CF1887A6AE95B124688AACBD4341D` |
| `corporate_announcements.json.bak-20260820-PRE-ALPACA-CLEANUP` | 276 | 2026-08-12 15:43:52 | `AF2809F6DC9E4B9EE97230AF0489B4486C73E680D0329BA7C188EDF6CB926FB4` |
| `daily_reports.md` | 44,006 | 2026-09-11 16:03:31 | `FB8249F9B733D007EE4094A850C86A3FB3158A3195AA4CC8B9FD9D06C801D021` |
| `daily_reports.md.bak-20260821-175933` | 74,518 | 2026-08-21 16:02:06 | `047F36534A949DCDCE5351BBC768E9CB00D06CF6D74BFD6761F3B744D45BB251` |
| `daily_reports.md.bak-20260910-preregen` | 33,525 | 2026-09-09 16:04:48 | `98832147E579DD4614C41087C9A6DF1D8391DE6D9CB364D82E77849921D48AFE` |
| `decision_journal.csv` | 83,325 | 2026-09-11 15:55:20 | `FCC60F8163E21D197D3A491200A452999D2C30EFD3F0C792B97A2481AE0CD4BA` |
| `decision_journal.csv.bak-20260821-175933` | 467,950 | 2026-08-20 09:56:24 | `94C71EA16FAEFD5FA242CFA490C9C6F344DAA0F0A16969166D08E475AB6C5AD9` |
| `earnings_cache.json` | 22,402 | 2026-09-12 10:59:51 | `33BC510C040FE62A73E728510B3F75EB359D3EDEF87CCD79DB4C12963D82BB0C` |
| `equity_curve.csv` | 553,257 | 2026-09-12 11:18:09 | `A768B21F30BA3045AB9715DE93B3FC3B7936F59CB5982944EE85EBEB253D2529` |
| `equity_curve.csv.bak-20260821-175452` | 708,733 | 2026-08-21 17:54:23 | `164E37B5ECBE53B7E087A9D792F88D85F2431D135FC704F02A354667C7DD6927` |
| `equity_state.json` | 95 | 2026-09-12 11:18:09 | `012062531140EEFA4BE5F0437F324CC0D3C89D943E367F6F9E89F02101854023` |
| `fundamentals_cache.json` | 159,960 | 2026-09-11 10:27:36 | `8054F41DEE1CC0387145E318CA597527022BBBD84E268D5CCC97B65C1FD6D555` |
| `kill_switch.json` | 43 | 2026-09-10 09:11:05 | `1996F37271D57A50C970D5978ABAC9F91AE21A54D7ADD56705F59BF4B7AE283D` |
| `open_position_entries.json` | 2,217 | 2026-09-12 10:56:09 | `B389974E6286EAEBC871E1610CE0EBAB97348634ABC77875A546DE955B87A0E0` |
| `open_position_entries.json.bak-20260812-090344-PRE-M86-strategy-backfill` | 1,859 | 2026-08-11 23:33:56 | `4211E54B494ABD27A2D031B7A6CB51A3D85999C78DC1ED59E8BE3BAE67B3F8E9` |
| `open_position_entries.json.bak-20260820-PRE-ALPACA-CLEANUP` | 1,888 | 2026-08-12 09:21:19 | `FCBB6CF7D1D611A0837B472372AFEF534FD3A0DE9F5843E967D4B4DDCB6B8122` |
| `open_position_entries.json.bak-20260903-070900` | 2,127 | 2026-09-03 14:52:24 | `39F2234CC7D6FF93B9C7834155B71E089633CCE9A4C8D7DD810B0FA2FA1E36D8` |
| `open_position_entries.json.bak-20260904-083130` | 2,338 | 2026-09-04 16:10:05 | `97216099D9F7F3A7F44BC0701D9EB7F570F2B3EF93B83505FD6F0F0FAD7E8E8F` |
| `open_position_entries.json.bak-fill-basis-20260912-105253` | 1,942 | 2026-09-11 10:03:22 | `278F423397EF451EF587BBE3125F60FBB57FDEB65E24B1981AB67274942AA187` |
| `open_position_entries.json.bak-pre-m33b` | 752 | 2026-08-01 09:10:57 | `157B678955FC095394CB8BA693907261905055C50A78AE9B4A7020B1252229E7` |
| `report_state.json` | 66 | 2026-09-11 16:03:35 | `989FDE652D9453FED92C31CAC3D2A51C45D57FE3C622A3550408998D0BDB1646` |
| `resting_order_anomalies.json` | 23 | 2026-09-10 10:44:06 | `08B5FF7CEA23CE041ED54A6C86F506E0E722C372034CF73BA331B4A38A8E5131` |
| `risk_decisions.csv` | 2,072,000 | 2026-09-11 15:59:36 | `41C838A260906B00FB8B359BDD8CC98E1C33DC0EE35D346D5CF12A5A4B429477` |
| `risk_decisions.csv.bak-20260821-175452` | 1,834,430 | 2026-08-19 04:32:21 | `3F787DED9C0A773949FCB04321856603E3DD554E734121BC189361558841382B` |
| `weekly_reports.md` | 12,134 | 2026-09-11 16:03:35 | `441C7CB5571D01995A245730E90DA1E6DF10977091F6D7E745D71329CB2E7478` |
| `weekly_reports.md.bak-20260821-175933` | 17,582 | 2026-08-21 16:02:10 | `0682806E9AAEAA2427B784B3AAC392DE7DD4C91A8AB41F33463F80A9C41734FC` |
<!-- /TABLE:records -->

### The log (`<logs>`)

`qat.log` and its six rotations cover 27 Jul to 12 Sep, with the 66-minute
hole on 24 Aug (R13 §13.6).

<!-- TABLE:logs -->
| File | Bytes | Modified | sha256 |
|---|---|---|---|
| `qat.log` | 4,652,963 | 2026-09-12 11:19:01 | `EA3452E003AB59760D08A3BC1378C91FEB56B53D78011BA80925EB0764432B70` |
| `qat.log.1` | 5,239,785 | 2026-08-25 14:05:14 | `A3D86300FBF77ECE446CC4C488AA86569FE2489FD9C40176834623CAEA4E87B7` |
| `qat.log.2` | 5,189,387 | 2026-08-25 10:32:55 | `A536403D53F3CED34A0CC23D8625A53EAA4F730D033E787A0985D53B9D01242D` |
| `qat.log.3` | 5,236,571 | 2026-08-25 10:32:20 | `CD4D00A5992C7D5259AB39072A66A0AD8988A988E1E3D657CE5A5661E25F1F4A` |
| `qat.log.4` | 5,216,959 | 2026-08-25 10:30:27 | `1419A301DBEFFAC5ED540C11E5B9ED9BBF1F0EB72B42A60F708AEAE97AF2D0B9` |
| `qat.log.5` | 5,234,075 | 2026-08-24 15:21:49 | `8330B580B42707E741A7C11617F23CE4DE6A96D6B5EB77D28244B012C8C1A140` |
| `qat.log.6` | 5,242,781 | 2026-08-24 10:06:27 | `EFE2ADBFC4FDB8CE2EF11130DFFAF190075D4AE528D95369091245B525B2303D` |
<!-- /TABLE:logs -->

### The broker's record (hash only; never committed)

In `Documents\QAT-audit-evidence\2026-09-12\broker-statements\`.
`DUQ200898_20260824_20260911.pdf` covers 24 Aug to 11 Sep and is the one R13
compares with the ledger; `DUQ200898_20260824.pdf` covers 24 Aug alone.

<!-- TABLE:statements -->
| File | Bytes | Modified | sha256 |
|---|---|---|---|
| `DUQ200898_20260824_20260911.pdf` | 177,147 | 2026-09-12 20:03:28 | `8E578080943089D79D3AC6F2C90D802FBEA533AF250372259D0EDB4DF5D40E69` |
| `DUQ200898_20260824.pdf` | 59,475 | 2026-09-12 20:00:57 | `277D4FC1087573B56688E9F6E391BC313CA33DAA80B38DDA362EFE8FED5D7D55` |
<!-- /TABLE:statements -->

### The transcripts (`<transcripts>`)

The Claude Code session files, the source of the operator's own words (the
authority register) and of the operator's corrections (Annex C). Hashed as
they stand at 13:50 on 15 Sep; the sessions still running (this one) will
change. The four claude.ai chats before 24 Jul are in the `2026-09-12`
snapshot.

<!-- TABLE:transcripts -->
| File | Bytes | Modified | sha256 |
|---|---|---|---|
| `00ce3f0d-aefa-4c7f-ab6a-46ed488efb84.jsonl` | 6,513,633 | 2026-09-07 12:14:04 | `3BAA45219EEA756D1BB5228DAE7F0129189DD6AA0C244735B9441D3F3973CDDD` |
| `017ec6a2-5063-453c-bf0f-ce0da1174078.jsonl` | 62,118 | 2026-09-07 08:24:37 | `B1BAADEF684509D571AB0267F20E942AE9F1CF4420B26B73ED2538ACAB771340` |
| `0660d19e-be6d-4e58-8120-5bc018bfb40c.jsonl` | 4,357,507 | 2026-09-15 08:34:50 | `385200C13A67E9DF1092E8A56C3020DBDDE0BA01303DB8A388B4BEE7BE1BC759` |
| `0cedd561-2889-49c3-982a-188322bbd1b1.jsonl` | 4,215,929 | 2026-09-14 09:20:30 | `8009A87F7AB05BB0BECE32C74A42A5794A91A496694A77E7792C962547FCBDCE` |
| `1111c286-d8ee-4adf-b09a-ddf6545bad56.jsonl` | 5,838,280 | 2026-09-08 08:34:44 | `66F929259FE7DE3A0E39ED6996270D41CB27131148121B1E83975E6142D0766D` |
| `25468f8a-1b49-4f2e-9c5f-d4aeb6f4075e.jsonl` | 4,910,210 | 2026-09-08 14:40:04 | `79B7C4162621B19E19AE3905AE885F3C1F2299F921920EC112C18A3AE0D51B60` |
| `2657e614-ffe4-435f-a1de-7a35b86c9185.jsonl` | 125,884 | 2026-09-07 08:24:37 | `D2301F3FF19F789C187C4C57ADCE14F76C03FC8F11B3430267ED9FBC331466A0` |
| `47042ff9-0d77-423e-9deb-655048571760.jsonl` | 6,740,623 | 2026-09-07 08:24:37 | `943B37060973D659DFD9818C1221087F65CD2DCA6F8FA8CA77FF4BE44A03BCF8` |
| `49741caa-665e-4649-aa98-32d2925b5117.jsonl` | 4,944,124 | 2026-09-12 18:09:59 | `97D4AE38D9652EDD2D6B0D1E2BAE22A619D3764D1247252F282DC95762FA58DB` |
| `4c48ee75-f779-4700-91ad-f34e7492c732.jsonl` | 100,111 | 2026-09-07 08:24:37 | `6C0573B533D4CAB2C52FAB0EDDB920CD643AB55065DF7F630612BAC5DA90CDA9` |
| `58424b93-0d7f-4c7d-b6d6-e3bd1720176f.jsonl` | 7,839,959 | 2026-09-09 09:28:35 | `759E088D211C59CA46C15F9BEA5683B4E7C9358F41E4BD7150E26C179C7B7DF2` |
| `5cbbd672-33d5-47da-9e7b-3eacce364c21.jsonl` | 5,033,205 | 2026-09-07 13:12:03 | `3290AA13A094A8A75B37D9308BDA35C92094D09F3769F691CD158DF77DDDE1F1` |
| `64d334fe-857b-4cf9-8913-f0e154746517.jsonl` | 42,049,608 | 2026-09-07 17:08:49 | `63B8E4D07F76FF900C7674ECEA06D0AF358900F4076AD9DD629E595C1E3D4F40` |
| `6b884879-3650-4d29-83a7-1b8af73cf807.jsonl` | 6,389,247 | 2026-09-09 17:15:43 | `E3FA7FAE0F50D2966C2E7D684AB0F6A275BFC7547F711EE9CB6D9FD3A77EF933` |
| `73e1e19c-d4f5-4465-9264-ce5bb815c68f.jsonl` | 12,315,227 | 2026-08-04 16:31:36 | `2CE4900DF0EC2522EAA8CDB16D50D34F3C0B20A6EEE1AFAD9B93278079F3CEA9` |
| `74fe73ed-9a42-487e-aeae-2cd5a35b7607.jsonl` | 6,613,684 | 2026-09-08 20:53:28 | `86253AD2574ED891006E67E4DEDDD844E42D817E89327AC6DB98AFB0C3FC8334` |
| `87d1b020-5842-4173-8750-cbe72879c5b6.jsonl` | 6,471,481 | 2026-09-12 18:36:18 | `37D7994F3FC660AE6AC82C636B26437AFDE3C604E3C177C42E29F307C0DD2573` |
| `8835f13a-c911-48f3-b073-41e03f9dc7c5.jsonl` | 69,452 | 2026-09-07 08:24:37 | `C50833738E5A19B74FA8EC057B9BFAD620A03F5389F4798DCA1301BCE8C683E8` |
| `9034806e-5174-49a3-9c91-8829eb82560c.jsonl` | 7,025,010 | 2026-09-08 18:05:04 | `A51AB191098FD5CF5C209897ACB4C5C6A948EF6B370BA6A80BAC5C2B3051CFB1` |
| `9083b85e-037d-4e69-838e-1ad2c27b333e.jsonl` | 6,186,479 | 2026-09-09 15:49:41 | `A29D2E8B83C4D8CA983A330741C4F843EC904FC4DE7129ACABADD901830E6196` |
| `9b9d429c-cc46-4151-ad4e-fc280531b9be.jsonl` | 5,029,477 | 2026-09-15 09:48:09 | `1DA7CAF3A720C06A4AAA3767103076FB4C5B033C0049A81130C3697E7787A986` |
| `a7821bbf-48fe-46b6-94cd-86f417154c98.jsonl` | 9,055,483 | 2026-09-15 14:04:46 | `11B9468FFF610EED33FB199F1FB151761151DDA5ED01EDB220B8A4BDB8E04531` |
| `bf81c3b3-0324-48f8-bebb-0e519796582f.jsonl` | 14,363,103 | 2026-09-09 09:28:18 | `F44F27EA5492A299B89B7C2880967AC34269927294396800DDB49234169FC475` |
| `cd2ae64a-a788-4041-8aeb-9baffefabcfb.jsonl` | 7,195,600 | 2026-09-08 09:07:38 | `B2EC524B41903D024A949607A6F0F12B783136BE1BF96FEA693F641FDDA79DC1` |
| `d085983f-7654-4699-bc71-e3b6f2f237f6.jsonl` | 5,726,407 | 2026-09-11 10:02:05 | `A503C33B1D410EA34C4360871E453279F09AA45BAF9AFC87390909EF2D92D0FA` |
| `d5855f73-26f7-4455-a553-f20c3ab9fd00.jsonl` | 11,146,782 | 2026-09-12 18:09:55 | `49BB9E1F68FDD657F0415BF5B038C894EAD8BE72880F9D66CD5777F3AD1EB263` |
| `df2c900c-dd9f-466d-b862-7007784ec396.jsonl` | 5,240,858 | 2026-09-14 14:46:26 | `C1705EF797148669D1023EC7E53E5D2C5965EB5B212E3B9EF2D2102F74ABC25D` |
| `e23c9454-7cd9-4186-b6a1-25c5f87e1775.jsonl` | 5,589,355 | 2026-09-08 13:59:34 | `785D3D4F73CA82C98587BE21CE163AD6331865956099250A358B7DC682E657C0` |
| `e5d2c59a-d016-48f5-94fe-d9f23a1be20a.jsonl` | 62,074 | 2026-09-07 08:24:37 | `F30CFF1D88E6D3674766AE610B414DC51C3D71FCDE53F6DC291755318A6724D1` |
| `e835407f-b766-4cad-9e03-abda6ad5a187.jsonl` | 5,522,840 | 2026-09-09 13:26:02 | `0914CC6B974C807DB1CF3186FA5812233E4FC840A974E5E06A9E9240B9052E2B` |
| `e9657947-9cd1-48de-a0a1-32e8ea6b65e4.jsonl` | 67,422 | 2026-09-07 08:24:37 | `114E7B7C6906A20F7A5BB0543A9FA3F9C5966ADA869D1D0430C57BDC77634FFD` |
| `edc04746-e4db-4500-ae57-25aea71d5b98.jsonl` | 273,295 | 2026-09-07 08:24:37 | `266F33021971320FCCA181E84D04A0D3931CB124DC07DE299D021DEF1AD66E9F` |
| `ede4fc1d-9634-44ed-9292-61ee30179ce1.jsonl` | 6,423,930 | 2026-09-14 13:26:03 | `74C5D8C9B2E00F602FE61D438AD62A18C4E9A03102FF5B9F53199B23AC393D22` |
| `f20567d2-cf0e-45e4-bbe2-2cc995ddd587.jsonl` | 4,974,663 | 2026-09-09 19:05:28 | `D24F987CFB2A97582A9B7F7DBBB001DF0034938DE91AA4F5A38BD2C8ECD93393` |
| `f2d132cc-9579-4ba3-9d21-2c19518fb6c7.jsonl` | 7,015,896 | 2026-09-09 17:12:49 | `217631F2D5C9E86F3C24A5124134C0F446541B946E738D5C3658C8DB7F979DE9` |
| `f549e655-29a8-42dc-92b4-2dba784495dc.jsonl` | 68,190 | 2026-09-07 08:24:37 | `E06EE1AB791DFA74BEB0EDEF21251E2AEEFD9589DD16DC6448C4E036BC3AE121` |
| `f79e139c-dd23-46c2-98e1-73879eb806e5.jsonl` | 8,202,848 | 2026-09-08 08:34:44 | `9A5CEE910DCAAE42F395D54F94FCF9B625602FBC38C932C3F99173616A69DF00` |
| `fc4500e5-6a0b-4cf2-be09-b3bf5bc78061.jsonl` | 5,795,676 | 2026-09-10 09:07:56 | `226D44EFEC16AC4176FEFF501964813394E5C1CE2F41EB402D223C2095878CE5` |
<!-- /TABLE:transcripts -->

## B.5 The repository

* **The system audited:** the deployed build M175, commit `5e322ca`, 951
  commits (R3).
* **The audit:** `docs/audit/2026-09-design-recovery/`, every section, tool,
  investigator report and register, committed and pushed to `origin/master`.
* **The error log:** `docs/CLAUDE_ERROR_LOG.md`, CE-001 onwards (Annex C).
* **The design sources** the audit read as the operator's intent: the paper,
  `Swing Trader methodology.md`, and the reference app in `C:\ShareTrader`
  (R4, R6).
