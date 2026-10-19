# ASX-only reference inventory — 19 October 2026

Scope: `src/`, `tests/`, `scripts/`, and non-archived `docs/` at `cleanup/asx-only`. This is an inventory only; no code or test was removed. The scan covers Alpaca, US/USD markers, US venues and time zone, US macro/benchmark terms, and prominent US tickers. Every matching line and token is indexed below. Dated reports and plans are listed as historical references, not edited.

The scan found **2219 matching lines in 300 files**: 60 source, 132 test, 28 script, and 80 documentation files.

## References by file

- `docs/2026-08-19-us-trial-close.md`: 1 (US); 3 (US); 147 (Alpaca); 149 (US); 150 (Alpaca); 157 (US)
- `docs/CLAUDE_ERROR_LOG.md`: 43 (US); 60 (USD); 61 (USD); 150 (US); 773 (US); 775 (US); 1212 (US); 1257 (AAPL); 1301 (US); 1339 (US)
- `docs/DATA_SOURCES.md`: 6 (Alpaca); 8 (US); 9 (Alpaca, US); 47 (Alpaca, US); 60 (Alpaca); 68 (ALPACA); 69 (ALPACA, Alpaca); 97 (Alpaca, US); 118 (AAPL, MSFT); 140 (US); 144 (US)
- `docs/GTP Maturity Assessment 1 Aug 2026.md`: 153 (Alpaca)
- `docs/HANDOFF.md`: 68 (US); 69 (alpaca, ALPACA); 101 (USD); 106 (USD); 108 (USD); 295 (US); 415 (US); 1022 (US); 1161 (US); 1873 (Alpaca); 1882 (Alpaca); 1883 (Alpaca); 1884 (Alpaca); 2127 (alpaca, Alpaca); 2128 (alpaca, US); 2130 (Alpaca); 2131 (US); 2857 (US); 2868 (US); 2873 (US); 2974 (Alpaca); 3049 (USD); 3051 (USD); 3057 (USD); 3087 (Alpaca); 3128 (Alpaca); 3133 (alpaca); 3135 (alpaca); 3136 (alpaca); 3141 (alpaca, US); 3142 (alpaca); 3143 (US); 3147 (Alpaca); 3153 (alpaca); 3157 (US); 3163 (alpaca); 3168 (alpaca); 3190 (Alpaca); 3237 (US); 4071 (Alpaca); 4475 (Alpaca); 4536 (Alpaca); 4537 (alpaca); 4549 (Alpaca, US); 4574 (US, Alpaca); 4582 (US); 4584 (US); 4600 (US); 4713 (Alpaca); 4932 (Alpaca); 4980 (Alpaca); 5651 (US); 5661 (US); 5663 (US); 5664 (US); 5721 (US); 5749 (US); 5856 (US); 5858 (US); 5859 (US); 6492 (Wall Street); 6508 (AAPL, MSFT); 6509 (AAPL); 6514 (US); 6653 (US); 6667 (US); 6683 (Wall Street); 6912 (US); 6968 (ALPACA)
- `docs/INTENT.md`: 25 (US)
- `docs/LIVE_TRADING_READINESS.md`: 4 (Alpaca, US); 9 (US); 35 (Alpaca); 37 (US); 75 (Alpaca); 77 (US); 78 (US)
- `docs/MARKET_DATA_FINDINGS.md`: 3 (US, ALPACA); 4 (Alpaca); 7 (US); 24 (Alpaca); 116 (Alpaca, alpaca, ALPACA); 121 (Alpaca); 128 (AAPL); 149 (Alpaca); 203 (Alpaca); 213 (Alpaca); 221 (Alpaca); 222 (Alpaca)
- `docs/MNST_SPLIT_TEST.md`: 8 (Alpaca); 19 (Alpaca); 31 (Alpaca); 34 (Alpaca); 36 (Alpaca); 45 (Alpaca); 71 (US); 79 (Alpaca); 84 (Alpaca); 198 (Alpaca)
- `docs/PHASE3_UNWIND_BACKUP_MANIFEST_2026-10-16.json`: 967 (ALPACA); 1007 (ALPACA); 1103 (ALPACA); 1187 (ALPACA)
- `docs/PRODUCT_BLUEPRINT.html`: 185 (US); 186 (Alpaca)
- `docs/PRODUCT_DESCRIPTION.md`: 3 (US, Alpaca); 28 (US); 45 (US, Alpaca); 61 (Alpaca); 172 (Alpaca); 256 (US); 277 (Alpaca); 284 (Alpaca); 305 (Alpaca)
- `docs/QAT_CAPABILITY_TECHNICAL_2026-09-12.md`: 41 (US); 89 (US); 162 (US); 446 (US); 450 (US); 533 (US)
- `docs/UI_UX_APPROACH.md`: 83 (Alpaca); 157 (Alpaca)
- `docs/audit/2026-09-design-recovery/00-progress-tracker.md`: 266 (US); 314 (US)
- `docs/audit/2026-09-design-recovery/01-executive-summary.md`: 59 (US)
- `docs/audit/2026-09-design-recovery/03-current-baseline.md`: 105 (US); 192 (US)
- `docs/audit/2026-09-design-recovery/04-original-design-intent.md`: 13 (Alpaca); 150 (US); 175 (USD); 196 (S&P 500); 304 (Alpaca, US)
- `docs/audit/2026-09-design-recovery/05-current-architecture.md`: 41 (US); 180 (US); 181 (US)
- `docs/audit/2026-09-design-recovery/07-design-drift-map.md`: 73 (US, Alpaca); 76 (US); 106 (US); 131 (US)
- `docs/audit/2026-09-design-recovery/08-strategy-integrity.md`: 61 (US); 71 (US); 89 (Alpaca)
- `docs/audit/2026-09-design-recovery/12-regime.md`: 39 (US); 58 (SPY); 89 (SPY); 107 (US); 136 (US); 140 (US); 149 (US); 150 (US); 151 (US); 167 (US); 176 (US); 177 (US); 190 (US); 194 (US); 199 (US); 211 (US); 237 (SPY); 243 (SPY); 260 (US); 285 (US)
- `docs/audit/2026-09-design-recovery/13-data-evidence-integrity.md`: 125 (US, alpaca); 165 (US, alpaca, Alpaca)
- `docs/audit/2026-09-design-recovery/14-failure-to-control-mapping.md`: 34 (US)
- `docs/audit/2026-09-design-recovery/15-accidental-complexity.md`: 22 (US)
- `docs/audit/2026-09-design-recovery/18-original-intent-architecture.md`: 71 (US)
- `docs/audit/2026-09-design-recovery/19-design-drift-architecture.md`: 56 (US); 92 (US)
- `docs/audit/2026-09-design-recovery/21-outstanding-unknowns.md`: 64 (US)
- `docs/audit/2026-09-design-recovery/A-anomalies-register.md`: 55 (US); 68 (US)
- `docs/audit/2026-09-design-recovery/B-evidence-index.md`: 190 (ALPACA); 204 (ALPACA)
- `docs/audit/2026-09-design-recovery/P-development-chronology.md`: 24 (US); 46 (USD); 121 (US); 130 (US); 135 (US)
- `docs/audit/2026-09-design-recovery/QAT-Design-Recovery-Audit-Final-Report.md`: 105 (US); 199 (US); 221 (USD); 296 (US); 305 (US); 310 (US); 709 (US); 796 (US); 836 (Alpaca); 973 (US); 998 (USD); 1019 (S&P 500); 1127 (Alpaca, US); 1303 (US); 1442 (US); 1443 (US); 1638 (US, Alpaca); 1641 (US); 1671 (US); 1696 (US); 1830 (US); 1840 (US); 1858 (Alpaca); 2696 (US); 2715 (SPY); 2746 (SPY); 2764 (US); 2793 (US); 2797 (US); 2806 (US); 2807 (US); 2808 (US); 2824 (US); 2833 (US); 2834 (US); 2847 (US); 2851 (US); 2856 (US); 2868 (US); 2894 (SPY); 2900 (SPY); 2917 (US); 2942 (US); 3074 (US, alpaca); 3114 (US, alpaca, Alpaca); 3239 (US); 3301 (US); 3787 (US); 3881 (US); 3917 (US); 4091 (US); 4593 (US); 4606 (US); 4843 (ALPACA); 4857 (ALPACA); 5003 (US); 5026 (US); 5027 (US); 5028 (US); 5029 (US); 5030 (US); 5084 (US); 5099 (US)
- `docs/audit/2026-09-design-recovery/backfill/00-backfill-register.md`: 40 (US); 63 (US); 64 (US); 65 (US); 66 (US); 67 (US); 121 (US); 136 (US)
- `docs/audit/2026-09-design-recovery/backfill/tools/error_log_table.py`: 24 (US)
- `docs/audit/2026-09-design-recovery/s-chronology/tools/chronology.py`: 11 (US); 38 (US)
- `docs/audit/2026-09-design-recovery/s09-s10-ai-and-regime/tools/regime_evidence.py`: 16 (US); 213 (US)
- `docs/audit/2026-09-design-recovery/stage3/investigator-1-data-to-signal.md`: 20 (US, SPY); 27 (alpaca, Alpaca); 37 (alpaca, Alpaca, US); 40 (Alpaca); 45 (Alpaca, alpaca); 47 (US); 57 (Alpaca, alpaca); 67 (alpaca, Alpaca); 73 (Alpaca, alpaca); 96 (alpaca); 115 (Alpaca); 134 (Alpaca, alpaca); 140 (Alpaca, alpaca); 374 (US); 376 (alpaca); 377 (alpaca); 385 (SPY, AAPL, MSFT, GOOGL); 403 (Alpaca, alpaca); 429 (Alpaca)
- `docs/audit/2026-09-design-recovery/stage3/investigator-2-signal-to-pending-order.md`: 54 (US); 222 (US); 397 (US)
- `docs/audit/2026-09-design-recovery/stage3/investigator-3-signoff-to-reconciliation.md`: 442 (US); 511 (Alpaca)
- `docs/audit/2026-09-design-recovery/stage3/investigator-4-wiring-ledger-ai.md`: 124 (Alpaca, alpaca); 125 (Alpaca, alpaca); 126 (alpaca); 497 (US)
- `docs/audit/2026-09-design-recovery/stage4/authority-evidence.md`: 278 (US); 301 (US); 304 (US)
- `docs/phase3-paper-unwind-halt-2026-10-16.md`: 58 (alpaca)
- `docs/superpowers/plans/2026-08-08-position-anomaly-seam.md`: 126 (AAPL); 128 (AAPL); 130 (AAPL); 134 (AAPL); 138 (AAPL); 145 (AAPL); 149 (AAPL); 168 (AAPL); 171 (AAPL); 173 (AAPL); 182 (AAPL); 189 (AAPL); 198 (AAPL)
- `docs/superpowers/plans/2026-08-12-absorb-watermark-window.md`: 35 (Alpaca); 302 (Alpaca); 358 (Alpaca)
- `docs/superpowers/plans/2026-08-12-broker-capability-audit.md`: 34 (Alpaca); 283 (alpaca, Alpaca); 287 (alpaca, Alpaca); 337 (alpaca); 402 (alpaca); 568 (Alpaca); 613 (Alpaca); 660 (alpaca); 671 (alpaca)
- `docs/superpowers/plans/2026-08-12-corporate-actions.md`: 5 (Alpaca); 16 (alpaca); 86 (Alpaca); 98 (Alpaca); 177 (Alpaca); 324 (alpaca); 431 (alpaca); 437 (Alpaca)
- `docs/superpowers/plans/2026-08-12-replay-g1.md`: 9 (Alpaca); 13 (Alpaca); 96 (SPY); 129 (Alpaca); 134 (SPY)
- `docs/superpowers/plans/2026-08-12-replay-regime.md`: 211 (SPY); 328 (SPY)
- `docs/superpowers/plans/2026-08-12-simulated-broker.md`: 14 (Alpaca); 306 (USD); 831 (alpaca, Alpaca); 835 (alpaca, Alpaca); 841 (alpaca, Alpaca); 851 (alpaca, Alpaca)
- `docs/superpowers/plans/2026-08-13-ablation-switch-and-run-manifest.md`: 244 (SPY); 257 (SPY); 408 (SPY); 421 (SPY); 761 (SPY); 774 (SPY); 1466 (SPY); 1661 (SPY); 1662 (SPY)
- `docs/superpowers/plans/2026-08-14-asx-macro.md`: 5 (US); 53 (US); 302 (US); 515 (US); 531 (US); 538 (US); 541 (US); 647 (US); 648 (US); 649 (US)
- `docs/superpowers/plans/2026-08-19-ibkr-move.md`: 5 (Alpaca); 9 (US); 43 (Alpaca); 74 (US); 82 (Alpaca); 163 (Alpaca); 203 (Alpaca); 221 (US); 251 (alpaca); 285 (USD); 291 (USD); 296 (USD, US); 298 (US); 303 (US); 316 (alpaca); 317 (alpaca); 384 (US); 386 (USD); 388 (US); 411 (US); 427 (USD); 428 (US); 437 (US); 443 (US); 450 (Alpaca)
- `docs/superpowers/plans/2026-08-21-asx-auctions.md`: 7 (US); 20 (US); 34 (US); 332 (US); 340 (US); 383 (US); 384 (US); 389 (US); 449 (US); 458 (US); 460 (US); 635 (AAPL); 703 (US); 704 (US); 1133 (Alpaca); 1139 (Alpaca)
- `docs/superpowers/plans/2026-08-22-symbol-verdict.md`: 1277 (SPY)
- `docs/superpowers/plans/2026-08-24-resting-order-reconciliation.md`: 33 (US); 183 (US)
- `docs/superpowers/plans/2026-08-26-absorb-cumulative-quantity.md`: 7 (Alpaca); 15 (Alpaca); 80 (Alpaca); 236 (Alpaca); 323 (Alpaca); 334 (Alpaca)
- `docs/superpowers/plans/2026-08-26-macro-milestone-b.md`: 72 (US)
- `docs/superpowers/plans/2026-08-26-regime-feature-standardisation.md`: 68 (US); 569 (Alpaca)
- `docs/superpowers/plans/2026-08-27-feature-ablation.md`: 611 (US); 624 (US); 632 (US)
- `docs/superpowers/plans/2026-08-30-absent-price-refusal.md`: 51 (US)
- `docs/superpowers/plans/2026-08-31-reconciliation-in-flight-remainder.md`: 22 (Alpaca)
- `docs/superpowers/plans/2026-09-01-manual-position-close.md`: 21 (Alpaca)
- `docs/superpowers/plans/2026-09-03-order-rejections-and-feed-health.md`: 20 (alpaca, Alpaca, US)
- `docs/superpowers/plans/2026-09-11-fill-basis-and-commission-check.md`: 18 (Alpaca); 330 (Alpaca); 754 (Alpaca); 1249 (USD)
- `docs/superpowers/plans/2026-09-12-design-recovery-audit-plan.md`: 366 (Alpaca)
- `docs/superpowers/specs/2026-08-08-dashboard-balances-design.md`: 9 (Alpaca); 140 (Alpaca)
- `docs/superpowers/specs/2026-08-08-position-anomaly-seam-design.md`: 27 (Alpaca); 43 (alpaca); 112 (Alpaca); 116 (Alpaca)
- `docs/superpowers/specs/2026-08-08-risk-at-stop-current-prices-design.md`: 37 (Alpaca); 72 (Alpaca); 140 (Alpaca)
- `docs/superpowers/specs/2026-08-12-asx-transferable-validation-design.md`: 23 (US); 29 (US); 66 (Alpaca); 131 (Alpaca); 137 (alpaca); 146 (Alpaca); 149 (Alpaca); 166 (US); 167 (US); 180 (Alpaca); 184 (US); 191 (CBOE, US); 193 (US); 213 (US); 214 (US); 249 (alpaca); 346 (Alpaca); 350 (US); 354 (US); 355 (US); 359 (US); 375 (US); 444 (US)
- `docs/superpowers/specs/2026-08-12-corporate-actions-design.md`: 16 (Alpaca); 33 (Alpaca); 35 (Alpaca); 99 (Alpaca); 104 (Alpaca); 121 (Alpaca); 158 (US)
- `docs/superpowers/specs/2026-08-12-research-harness-design.md`: 53 (Alpaca); 203 (US)
- `docs/superpowers/specs/2026-08-13-ablation-switch-and-run-manifest-design.md`: 49 (SPY); 147 (SPY); 166 (SPY); 167 (SPY); 168 (SPY)
- `docs/superpowers/specs/2026-08-19-ibkr-announcements-decision.md`: 146 (Alpaca); 160 (USD); 166 (USD); 216 (USD); 220 (USD); 241 (USD); 242 (USD); 250 (USD)
- `docs/superpowers/specs/2026-08-19-ibkr-capability-measurement.md`: 25 (Alpaca); 26 (alpaca); 32 (USD); 33 (USD); 41 (alpaca); 121 (AAPL, NASDAQ, AMEX, NYSE); 145 (US); 159 (US); 192 (US); 227 (US)
- `docs/superpowers/specs/2026-08-21-asx-auctions-design.md`: 111 (US); 112 (US); 115 (US); 116 (US); 117 (US); 266 (US)
- `docs/superpowers/specs/2026-08-25-macro-layer-research.md`: 16 (United States); 20 (US); 21 (US); 22 (US); 23 (CBOE); 41 (US); 49 (US); 57 (US); 73 (USD); 78 (CBOE); 79 (US); 114 (US); 115 (US); 126 (US); 279 (US); 315 (US)
- `docs/superpowers/specs/2026-08-27-feature-ablation-design.md`: 162 (US); 165 (US)
- `docs/superpowers/specs/2026-09-03-order-rejections-and-feed-health-design.md`: 11 (US); 80 (alpaca); 94 (alpaca); 132 (Alpaca); 133 (US); 205 (alpaca, Alpaca); 206 (alpaca, US); 207 (US)
- `docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`: 115 (US); 116 (US); 118 (US); 179 (US); 192 (US); 202 (US); 327 (US); 342 (US); 343 (US); 344 (US)
- `docs/superpowers/specs/2026-09-11-fill-basis-and-commission-check-design.md`: 26 (Alpaca); 196 (Alpaca)
- `scripts/analysis/README.md`: 55 (alpaca, Alpaca); 65 (Alpaca)
- `scripts/analysis/capture_split_state.py`: 6 (Alpaca); 26 (alpaca); 27 (alpaca); 28 (alpaca); 33 (alpaca)
- `scripts/analysis/exercise_m54.py`: 4 (Alpaca); 32 (alpaca); 35 (alpaca, Alpaca); 69 (alpaca); 76 (Alpaca)
- `scripts/analysis/g1/README.md`: 54 (US)
- `scripts/analysis/g1/harness_decisions.csv`: 6 (SPY)
- `scripts/analysis/g1/harness_decisions.open.csv`: 8 (SPY)
- `scripts/analysis/g1/risk_decisions.frozen.csv`: 5 (SPY); 8 (SPY); 10 (SPY); 13 (SPY); 14 (SPY); 15 (SPY); 16 (SPY); 17 (SPY); 18 (SPY); 19 (SPY); 20 (SPY); 21 (SPY); 22 (SPY); 23 (SPY); 24 (SPY); 25 (SPY); 26 (SPY); 27 (SPY); 28 (SPY); 30 (SPY); 49 (SPY); 50 (SPY); 51 (SPY); 53 (SPY); 58 (SPY); 59 (SPY); 60 (SPY); 61 (SPY); 62 (SPY); 63 (SPY); 64 (SPY); 65 (SPY); 66 (SPY); 67 (SPY); 68 (SPY); 69 (SPY); 70 (SPY); 71 (SPY); 72 (SPY); 73 (SPY); 74 (SPY); 75 (SPY); 76 (SPY); 77 (SPY); 78 (SPY); 79 (SPY); 80 (SPY); 81 (SPY); 82 (SPY); 83 (SPY); 84 (SPY); 85 (SPY); 86 (SPY); 87 (SPY); 88 (SPY); 89 (SPY); 90 (SPY); 91 (SPY); 92 (SPY); 93 (SPY); 94 (SPY); 95 (SPY); 96 (SPY); 97 (SPY); 98 (SPY); 99 (SPY); 100 (SPY); 101 (SPY); 102 (SPY); 103 (SPY); 104 (SPY); 105 (SPY); 106 (SPY); 107 (SPY); 108 (SPY); 109 (SPY); 110 (SPY); 111 (SPY); 112 (SPY); 113 (SPY); 114 (SPY); 115 (SPY); 116 (SPY); 117 (SPY); 118 (SPY); 119 (SPY); 120 (SPY); 121 (SPY); 122 (SPY); 123 (SPY); 124 (SPY); 125 (SPY); 126 (SPY); 127 (SPY); 128 (SPY); 129 (SPY); 130 (SPY); 131 (SPY); 132 (SPY); 133 (SPY); 134 (SPY); 135 (SPY); 136 (SPY); 137 (SPY); 138 (SPY); 139 (SPY); 140 (SPY); 141 (SPY); 142 (SPY); 143 (SPY); 144 (SPY); 145 (SPY); 146 (SPY); 147 (SPY); 148 (SPY); 149 (SPY); 150 (SPY); 151 (SPY); 152 (SPY); 153 (SPY); 154 (SPY); 155 (SPY); 156 (SPY); 157 (SPY); 158 (SPY); 159 (SPY); 160 (SPY); 161 (SPY); 162 (SPY); 163 (SPY); 164 (SPY); 165 (SPY); 166 (SPY); 167 (SPY); 168 (SPY); 169 (SPY); 170 (SPY); 171 (SPY); 172 (SPY); 173 (SPY); 174 (SPY); 175 (SPY); 176 (SPY); 177 (SPY); 178 (SPY); 179 (SPY); 180 (SPY); 181 (SPY); 182 (SPY); 183 (SPY); 184 (SPY); 185 (SPY); 186 (SPY); 187 (SPY); 188 (SPY); 189 (SPY); 190 (SPY); 191 (SPY); 192 (SPY); 193 (SPY); 194 (SPY); 195 (SPY); 196 (SPY); 197 (SPY); 198 (SPY); 199 (SPY); 200 (SPY); 201 (SPY); 202 (SPY); 203 (SPY); 204 (SPY); 205 (SPY); 206 (SPY); 207 (SPY); 208 (SPY); 209 (SPY); 210 (SPY); 211 (SPY); 212 (SPY); 213 (SPY); 214 (SPY); 215 (SPY); 216 (SPY); 217 (SPY); 218 (SPY); 219 (SPY); 220 (SPY); 221 (SPY); 222 (SPY); 223 (SPY); 224 (SPY); 225 (SPY); 226 (SPY); 227 (SPY); 228 (SPY); 229 (SPY); 230 (SPY); 231 (SPY); 232 (SPY); 233 (SPY); 234 (SPY); 235 (SPY); 236 (SPY); 237 (SPY); 238 (SPY); 239 (SPY); 240 (SPY); 241 (SPY); 242 (SPY); 243 (SPY); 244 (SPY); 245 (SPY); 246 (SPY); 247 (SPY); 248 (SPY); 249 (SPY); 250 (SPY); 251 (SPY); 252 (SPY); 253 (SPY); 254 (SPY); 255 (SPY); 256 (SPY); 257 (SPY); 258 (SPY); 259 (SPY); 260 (SPY); 261 (SPY); 262 (SPY); 263 (SPY); 264 (SPY); 265 (SPY); 266 (SPY); 267 (SPY); 268 (SPY); 269 (SPY); 270 (SPY); 271 (SPY); 272 (SPY); 273 (SPY); 274 (SPY); 275 (SPY); 276 (SPY); 277 (SPY); 278 (SPY); 279 (SPY); 280 (SPY); 281 (SPY); 282 (SPY); 283 (SPY); 284 (SPY); 285 (SPY); 286 (SPY); 287 (SPY); 288 (SPY); 289 (SPY); 290 (SPY); 291 (SPY); 292 (SPY); 293 (SPY); 294 (SPY); 295 (SPY); 296 (SPY); 297 (SPY); 298 (SPY); 299 (SPY); 300 (SPY); 301 (SPY); 302 (SPY)
- `scripts/analysis/g1/run_g1.py`: 93 (US); 97 (SPY)
- `scripts/analysis/probe_alpaca_splits.py`: 8 (alpaca); 22 (alpaca); 23 (alpaca); 24 (alpaca); 26 (alpaca); 99 (alpaca)
- `scripts/analysis/probe_entry_basis.py`: 20 (alpaca); 22 (alpaca)
- `scripts/analysis/probe_feed_entitlement.py`: 5 (Alpaca); 22 (alpaca); 23 (alpaca); 24 (alpaca); 28 (alpaca); 30 (alpaca); 57 (AAPL); 58 (AAPL); 69 (AAPL); 74 (AAPL); 85 (AAPL); 90 (AAPL)
- `scripts/analysis/probe_live_announcements.py`: 1 (Alpaca); 22 (alpaca, Alpaca); 29 (Alpaca)
- `scripts/analysis/probe_mark_source.py`: 3 (Alpaca); 19 (alpaca); 20 (alpaca); 21 (alpaca); 22 (alpaca); 23 (alpaca); 25 (alpaca)
- `scripts/analysis/probe_market_data.py`: 4 (alpaca); 26 (alpaca); 27 (alpaca); 28 (alpaca); 29 (alpaca); 31 (alpaca)
- `scripts/analysis/realised_slippage.py`: 30 (alpaca); 37 (Alpaca); 39 (Alpaca); 45 (Alpaca); 49 (alpaca); 71 (alpaca); 181 (US)
- `scripts/analysis/render_balances_panel.py`: 37 (USD)
- `scripts/analysis/verify_gating_figures.py`: 28 (alpaca); 29 (alpaca); 31 (alpaca)
- `scripts/analysis/when_do_trades_land.py`: 31 (US)
- `scripts/build_manual.py`: 109 (SPY, AAPL, MSFT); 130 (GOOGL, AAPL, SPY); 178 (AAPL); 179 (MSFT); 180 (SPY); 181 (GOOGL); 182 (AAPL); 258 (America/New_York); 313 (AAPL); 335 (US)
- `scripts/handoff_state.py`: 166 (New York)
- `scripts/manual_body.py`: 244 (Alpaca); 248 (Alpaca); 249 (Alpaca); 362 (Alpaca); 363 (US); 650 (Alpaca); 1232 (US); 1257 (US); 1642 (US); 1645 (US); 1660 (Alpaca); 1664 (Alpaca); 1666 (Alpaca); 1682 (Alpaca, US); 1712 (US); 1741 (US); 1744 (Alpaca, US); 1745 (Alpaca); 1746 (Alpaca); 1753 (Alpaca); 1758 (Alpaca); 1763 (US); 1820 (SPY); 2425 (US); 2671 (alpaca); 2685 (alpaca); 2692 (ALPACA); 2693 (US); 3000 (CBOE); 3113 (Alpaca)
- `scripts/migrate_ledger_eras.py`: 1 (alpaca); 5 (Alpaca, alpaca); 32 (Alpaca, US, USD); 59 (US); 66 (USD); 86 (Alpaca); 88 (US); 93 (US); 155 (Alpaca); 156 (US)
- `scripts/probe_halts_streaming.py`: 35 (USD)
- `scripts/research/run_ablation.py`: 163 (US); 187 (US); 188 (US); 192 (US); 197 (US)
- `scripts/research/run_asx_replay.py`: 15 (US); 88 (US); 113 (US); 114 (US); 115 (US)
- `scripts/retire_alpaca_era.py`: 1 (Alpaca, US); 3 (alpaca); 4 (alpaca); 10 (Alpaca); 21 (US); 229 (Alpaca); 231 (Alpaca); 264 (alpaca)
- `scripts/session_check.ps1`: 288 (Alpaca)
- `scripts/watch_session.py`: 53 (US)
- `src/qat/config.py`: 162 (alpaca, Alpaca, US); 164 (alpaca); 263 (US); 661 (US); 693 (alpaca); 759 (Alpaca); 761 (US); 765 (alpaca); 767 (Alpaca); 768 (alpaca); 792 (Alpaca); 907 (US); 911 (SPY, AAPL, MSFT); 915 (SPY, AAPL, MSFT, GOOGL)
- `src/qat/data/alpaca_source.py`: 1 (Alpaca); 3 (Alpaca); 12 (US); 20 (US, Alpaca); 24 (alpaca); 52 (Alpaca); 58 (Alpaca); 61 (ALPACA); 62 (Alpaca); 65 (alpaca); 67 (alpaca); 74 (Alpaca); 77 (Alpaca); 83 (alpaca); 89 (Alpaca); 95 (Alpaca); 96 (Alpaca); 98 (Alpaca); 110 (Alpaca); 123 (Alpaca); 144 (Alpaca); 161 (Alpaca); 167 (Alpaca); 186 (Alpaca); 188 (Alpaca); 204 (Alpaca); 214 (Alpaca); 221 (alpaca); 247 (alpaca); 253 (Alpaca); 272 (Alpaca); 273 (Alpaca); 285 (Alpaca); 299 (Alpaca); 309 (Alpaca); 364 (alpaca); 365 (alpaca); 366 (alpaca); 368 (Alpaca); 372 (Alpaca); 396 (Alpaca); 402 (Alpaca)
- `src/qat/data/broker/account_poller.py`: 4 (Alpaca)
- `src/qat/data/broker/adapter.py`: 106 (Alpaca); 111 (Alpaca); 188 (Alpaca); 260 (Alpaca); 361 (Alpaca); 465 (Alpaca)
- `src/qat/data/broker/alpaca_adapter.py`: 1 (Alpaca); 2 (alpaca, Alpaca); 13 (Alpaca); 22 (Alpaca, US); 43 (alpaca, Alpaca); 51 (ALPACA); 52 (ALPACA); 73 (Alpaca); 85 (Alpaca); 91 (Alpaca); 92 (Alpaca); 95 (Alpaca); 100 (Alpaca); 103 (Alpaca); 111 (Alpaca); 113 (Alpaca); 118 (Alpaca); 119 (alpaca); 124 (Alpaca); 126 (Alpaca); 128 (Alpaca); 130 (Alpaca); 145 (Alpaca); 197 (Alpaca); 218 (Alpaca); 224 (Alpaca); 230 (alpaca); 231 (alpaca); 278 (Alpaca); 291 (Alpaca); 349 (Alpaca); 364 (alpaca); 365 (alpaca); 366 (alpaca); 396 (alpaca); 397 (alpaca); 398 (alpaca); 465 (Alpaca); 529 (alpaca); 530 (alpaca); 590 (Alpaca); 611 (Alpaca); 626 (Alpaca); 654 (alpaca); 658 (Alpaca); 665 (Alpaca); 671 (Alpaca); 677 (Alpaca); 696 (Alpaca); 706 (alpaca); 729 (Alpaca); 752 (Alpaca); 772 (Alpaca); 842 (alpaca); 843 (Alpaca); 849 (alpaca); 852 (alpaca)
- `src/qat/data/broker/alpaca_client_protocol.py`: 1 (alpaca, Alpaca); 6 (alpaca); 8 (alpaca); 9 (alpaca); 17 (Alpaca); 20 (alpaca); 33 (alpaca)
- `src/qat/data/broker/capabilities.py`: 73 (Alpaca); 144 (alpaca, Alpaca); 154 (alpaca, Alpaca)
- `src/qat/data/broker/ib_adapter.py`: 882 (Alpaca); 1099 (Alpaca); 1106 (US); 1107 (Alpaca)
- `src/qat/data/broker/ib_translate.py`: 61 (alpaca); 84 (US); 87 (US, USD); 92 (US); 96 (USD); 100 (USD); 101 (USD, NYSE); 156 (Alpaca); 216 (Alpaca); 331 (Alpaca); 401 (US); 513 (US); 538 (US); 600 (US)
- `src/qat/data/broker/mock_broker.py`: 244 (USD)
- `src/qat/data/broker/simulated_broker.py`: 216 (USD); 275 (Alpaca); 316 (Alpaca)
- `src/qat/data/broker/ticks.py`: 9 (US, Alpaca); 45 (US); 54 (US); 135 (US)
- `src/qat/data/earnings.py`: 68 (US); 107 (US); 246 (US); 278 (US); 281 (America/New_York); 283 (America/New_York); 284 (New York); 317 (US); 341 (New York)
- `src/qat/data/fundamentals.py`: 7 (SPY)
- `src/qat/data/history.py`: 85 (ALPACA); 218 (alpaca); 220 (alpaca, Alpaca); 222 (Alpaca, alpaca); 225 (Alpaca)
- `src/qat/data/ibkr_news.py`: 30 (AAPL, MSFT); 31 (US); 32 (AAPL)
- `src/qat/data/instruments.py`: 21 (AAPL); 22 (MSFT); 23 (NVDA); 24 (AMZN); 25 (GOOGL); 121 (SPY, S&P 500); 122 (QQQ)
- `src/qat/data/news.py`: 189 (US); 221 (US)
- `src/qat/data/sectors.py`: 10 (AAPL); 17 (AAPL); 18 (MSFT); 19 (NVDA); 20 (AMZN); 21 (GOOGL); 67 (SPY); 68 (QQQ)
- `src/qat/data/symbols.py`: 3 (Alpaca); 4 (US); 8 (Alpaca); 26 (US); 43 (US); 80 (USD); 95 (US); 98 (US)
- `src/qat/data/universe.py`: 5 (US); 16 (US); 30 (US); 35 (US, SPY); 38 (AAPL, MSFT, NVDA, AMZN, GOOGL); 39 (SPY, QQQ); 41 (AAPL); 42 (MSFT); 43 (NVDA); 44 (AMZN); 45 (GOOGL); 279 (US); 312 (US)
- `src/qat/data/validation.py`: 94 (America/New_York)
- `src/qat/data/yfinance_fundamentals.py`: 4 (US); 12 (MSFT)
- `src/qat/data/yfinance_source.py`: 155 (SPY)
- `src/qat/domain/autonomy/executor.py`: 121 (US)
- `src/qat/domain/autonomy/gate.py`: 38 (US); 44 (US); 135 (Alpaca)
- `src/qat/domain/backtester/ablation.py`: 86 (US); 87 (US); 88 (US)
- `src/qat/domain/backtester/macro_cache.py`: 29 (US)
- `src/qat/domain/backtester/replay_session.py`: 83 (New York); 85 (US); 86 (US); 118 (SPY); 282 (US); 291 (US); 322 (SPY); 357 (US)
- `src/qat/domain/backtester/research_universe.py`: 11 (US); 46 (US); 48 (SPY); 50 (US); 53 (US); 64 (US); 65 (US); 87 (US)
- `src/qat/domain/backtester/signal_adapter.py`: 16 (AAPL)
- `src/qat/domain/corporate_actions/announcements.py`: 4 (Alpaca); 36 (Alpaca)
- `src/qat/domain/corporate_actions/monitor.py`: 43 (Alpaca)
- `src/qat/domain/decision_journal.py`: 96 (SPY)
- `src/qat/domain/display_dates.py`: 3 (US, Alpaca); 7 (US)
- `src/qat/domain/evaluation/refusals.py`: 307 (Alpaca, US)
- `src/qat/domain/macro_analysis/growth.py`: 16 (US)
- `src/qat/domain/macro_analysis/signal.py`: 151 (US)
- `src/qat/domain/market_calendar.py`: 1 (US); 32 (US); 34 (America/New_York); 37 (US); 43 (US, Alpaca); 44 (USD); 46 (US, USD); 54 (US); 64 (US); 72 (US); 113 (US); 123 (US); 125 (US); 192 (NYSE); 247 (US); 251 (NYSE); 254 (US); 403 (US)
- `src/qat/domain/oms/oms.py`: 491 (Alpaca); 1254 (Alpaca); 1255 (Alpaca); 1355 (Alpaca); 1421 (Alpaca); 2091 (Alpaca); 2275 (Alpaca); 2844 (Alpaca); 2855 (Alpaca); 2997 (Alpaca)
- `src/qat/domain/oms/reconciliation.py`: 9 (Alpaca)
- `src/qat/domain/oms/signal_bridge.py`: 200 (AAPL); 201 (MSFT); 636 (Alpaca); 1077 (AAPL); 1078 (MSFT); 1547 (Alpaca); 1843 (Alpaca)
- `src/qat/domain/performance/edge.py`: 97 (Alpaca, US)
- `src/qat/domain/performance/metrics.py`: 111 (USD)
- `src/qat/domain/performance/reporter.py`: 117 (US)
- `src/qat/domain/performance/reports.py`: 347 (Alpaca)
- `src/qat/domain/performance/trades.py`: 115 (US, Alpaca); 117 (USD); 340 (Alpaca, US); 538 (Alpaca, US); 608 (Alpaca); 633 (Alpaca); 1502 (Alpaca, US); 1544 (Alpaca, US); 1572 (Alpaca, US)
- `src/qat/domain/regime_engine/engine.py`: 253 (Alpaca)
- `src/qat/domain/regime_engine/feature_matrix.py`: 55 (CBOE, US)
- `src/qat/domain/risk_engine/audit.py`: 31 (Alpaca, US)
- `src/qat/domain/risk_engine/engine.py`: 364 (Alpaca)
- `src/qat/domain/session_controller.py`: 66 (US); 107 (Alpaca); 186 (US); 187 (US)
- `src/qat/preflight.py`: 206 (US); 251 (alpaca, US); 256 (alpaca, Alpaca, US); 274 (alpaca, US); 279 (alpaca, Alpaca, US); 317 (ALPACA); 706 (USD, NYSE); 768 (Alpaca); 777 (Alpaca)
- `src/qat/presentation/advisory_account.py`: 165 (Alpaca)
- `src/qat/presentation/balances_panel.py`: 7 (Alpaca); 18 (US); 23 (Alpaca); 61 (USD); 233 (Alpaca); 282 (Alpaca); 293 (US); 300 (Alpaca); 440 (Alpaca)
- `src/qat/presentation/runtime.py`: 180 (alpaca); 181 (US); 183 (alpaca, Alpaca, US); 187 (alpaca, Alpaca); 190 (Alpaca); 191 (alpaca); 192 (alpaca); 195 (alpaca); 199 (Alpaca); 200 (alpaca); 201 (alpaca); 205 (Alpaca); 234 (alpaca); 248 (Alpaca); 288 (alpaca); 289 (US); 291 (alpaca, Alpaca, US); 296 (alpaca, Alpaca); 298 (Alpaca); 300 (Alpaca)
- `src/qat/presentation/screener.py`: 55 (US); 369 (US)
- `src/qat/presentation/session_panel.py`: 239 (US); 263 (US); 327 (US)
- `src/qat/presentation/settings.py`: 57 (US); 61 (alpaca, Alpaca); 65 (alpaca); 76 (alpaca, Alpaca, US); 79 (ALPACA); 84 (ALPACA); 174 (Alpaca); 187 (alpaca); 188 (alpaca, Alpaca); 190 (Alpaca); 193 (Alpaca); 357 (US); 386 (Alpaca, US); 387 (US); 393 (alpaca); 394 (alpaca); 395 (alpaca); 396 (Alpaca, alpaca); 398 (alpaca); 399 (alpaca); 400 (alpaca); 401 (Alpaca, alpaca); 540 (Alpaca); 553 (US); 560 (Alpaca, alpaca); 622 (alpaca); 623 (Alpaca); 624 (alpaca); 625 (Alpaca); 760 (alpaca); 761 (ALPACA); 762 (alpaca); 763 (alpaca, ALPACA); 764 (alpaca); 766 (Alpaca); 768 (Alpaca, alpaca); 770 (alpaca); 771 (Alpaca, US); 778 (alpaca); 779 (alpaca); 780 (alpaca); 815 (Alpaca); 817 (alpaca); 818 (alpaca); 819 (alpaca); 1237 (alpaca); 1239 (alpaca); 1266 (alpaca); 1268 (ALPACA); 1269 (alpaca); 1270 (alpaca); 1272 (ALPACA); 1273 (alpaca); 1356 (ALPACA, alpaca)
- `src/qat/version.py`: 75 (ALPACA); 78 (Alpaca); 81 (US); 94 (Alpaca); 108 (ALPACA); 109 (US); 111 (US); 160 (Alpaca); 194 (Alpaca, US); 195 (US); 197 (Alpaca); 202 (USD); 220 (US); 221 (Alpaca); 237 (US); 288 (alpaca); 314 (US); 365 (Alpaca); 478 (alpaca); 637 (Alpaca); 650 (Alpaca); 682 (America/New_York); 683 (New York); 738 (US); 774 (Alpaca); 778 (Alpaca); 793 (Alpaca); 1163 (Alpaca); 1164 (alpaca, US); 1165 (US); 1277 (Alpaca); 1835 (US); 2019 (Alpaca); 2027 (ALPACA)
- `tests/data/broker/test_account_balances.py`: 3 (Alpaca); 20 (alpaca, Alpaca); 24 (Alpaca); 41 (USD); 54 (Alpaca); 56 (Alpaca); 67 (Alpaca); 68 (Alpaca); 69 (Alpaca); 70 (alpaca); 90 (Alpaca); 124 (Alpaca); 177 (AAPL)
- `tests/data/broker/test_alpaca_adapter.py`: 1 (Alpaca); 6 (Alpaca); 18 (alpaca); 19 (Alpaca); 20 (Alpaca); 32 (AAPL); 35 (Alpaca); 41 (Alpaca); 42 (alpaca); 43 (AAPL); 78 (Alpaca); 87 (Alpaca); 88 (Alpaca); 91 (Alpaca); 94 (Alpaca); 97 (alpaca); 112 (AAPL); 137 (AAPL); 150 (AAPL); 155 (alpaca); 161 (Alpaca); 167 (alpaca); 168 (AAPL); 190 (AAPL); 202 (AAPL); 213 (alpaca); 215 (alpaca); 216 (AAPL); 225 (Alpaca); 226 (Alpaca); 230 (Alpaca); 239 (alpaca); 246 (alpaca); 249 (alpaca); 250 (alpaca); 259 (AAPL); 266 (Alpaca); 272 (Alpaca); 275 (AAPL); 295 (Alpaca); 298 (AAPL); 316 (alpaca); 317 (alpaca); 323 (AAPL); 344 (AAPL); 356 (alpaca); 357 (alpaca); 363 (AAPL); 433 (AAPL); 442 (AAPL); 451 (AAPL); 461 (AAPL); 475 (Alpaca); 480 (AAPL); 506 (AAPL); 551 (alpaca); 560 (Alpaca); 562 (AAPL); 564 (AAPL); 578 (AAPL); 591 (AAPL); 604 (Alpaca); 613 (AAPL); 629 (AAPL); 634 (AAPL); 642 (AAPL, MSFT); 645 (AAPL, MSFT); 664 (alpaca); 676 (Alpaca); 680 (AAPL); 785 (Alpaca); 797 (alpaca); 805 (alpaca); 817 (alpaca); 829 (alpaca); 835 (Alpaca); 845 (Alpaca)
- `tests/data/broker/test_ib_adapter.py`: 101 (AAPL); 205 (AAPL)
- `tests/data/broker/test_ib_contracts.py`: 3 (USD); 9 (USD); 11 (USD); 12 (NYSE); 17 (US); 50 (AAPL); 68 (NYSE); 73 (AAPL); 75 (AAPL); 76 (USD); 168 (Alpaca); 228 (AAPL, USD); 233 (US, AAPL)
- `tests/data/broker/test_ib_order_identity.py`: 3 (Alpaca); 56 (Alpaca); 125 (USD); 134 (AAPL); 257 (AAPL); 271 (AAPL); 298 (AAPL); 307 (AAPL); 317 (AAPL); 336 (AAPL); 342 (AAPL)
- `tests/data/broker/test_ib_position_identity.py`: 94 (USD)
- `tests/data/broker/test_ib_position_marks.py`: 10 (ALPACA)
- `tests/data/broker/test_ib_protective_orders.py`: 17 (Alpaca, alpaca); 80 (Alpaca); 90 (alpaca); 121 (AAPL); 129 (AAPL); 164 (Alpaca)
- `tests/data/broker/test_ib_recent_fills.py`: 16 (Alpaca); 135 (AAPL, US); 237 (AAPL); 239 (US); 241 (AAPL)
- `tests/data/broker/test_ib_resting_stops.py`: 5 (US); 9 (Alpaca); 254 (AAPL); 256 (US, AAPL)
- `tests/data/broker/test_ib_tick_rounding.py`: 3 (US); 4 (Alpaca); 129 (US); 130 (US); 134 (AAPL)
- `tests/data/broker/test_ib_translate.py`: 22 (AAPL); 23 (AAPL); 25 (USD); 29 (AAPL); 37 (AAPL); 45 (AAPL); 46 (AAPL, USD); 58 (AAPL); 59 (AAPL, USD); 70 (AAPL, USD); 75 (AAPL); 83 (USD); 86 (USD); 89 (USD); 91 (USD); 111 (USD)
- `tests/data/broker/test_simulated_broker.py`: 187 (Alpaca); 270 (Alpaca); 294 (Alpaca)
- `tests/data/broker/test_ticks.py`: 63 (US); 64 (US)
- `tests/data/test_alpaca_source.py`: 1 (Alpaca); 3 (Alpaca); 18 (alpaca, Alpaca); 61 (AAPL); 62 (Alpaca); 64 (AAPL); 67 (AAPL); 73 (AAPL); 74 (Alpaca); 76 (AAPL); 84 (Alpaca); 86 (AAPL); 90 (AAPL); 91 (Alpaca); 93 (AAPL); 109 (Alpaca); 113 (AAPL); 121 (Alpaca); 147 (AAPL); 152 (Alpaca); 155 (AAPL); 156 (alpaca); 165 (AAPL); 166 (Alpaca); 168 (AAPL); 178 (Alpaca); 182 (AAPL); 188 (alpaca); 189 (alpaca); 192 (alpaca); 200 (alpaca); 205 (Alpaca); 213 (AAPL); 214 (Alpaca); 216 (AAPL); 225 (AAPL); 226 (Alpaca); 228 (AAPL)
- `tests/data/test_bar_seeding.py`: 17 (Alpaca); 143 (SPY); 144 (AAPL); 145 (SPY); 146 (AAPL); 147 (MSFT)
- `tests/data/test_bars.py`: 215 (AAPL); 216 (MSFT); 217 (AAPL); 219 (AAPL); 220 (MSFT); 221 (AAPL, MSFT); 248 (AAPL); 249 (AAPL); 251 (AAPL)
- `tests/data/test_daily_panel.py`: 62 (SPY, AAPL, MSFT); 64 (SPY, AAPL, MSFT); 68 (SPY, AAPL, MSFT); 74 (SPY); 76 (SPY); 78 (SPY); 88 (SPY, AAPL); 90 (SPY, AAPL); 98 (SPY, AAPL); 100 (SPY, AAPL); 101 (SPY)
- `tests/data/test_earnings_asx_fallback.py`: 61 (America/New_York); 62 (America/New_York); 65 (New York); 72 (America/New_York); 77 (New York); 84 (America/New_York); 87 (US)
- `tests/data/test_feature_engine.py`: 28 (AAPL); 30 (AAPL); 34 (AAPL); 53 (AAPL); 57 (AAPL); 81 (AAPL); 96 (AAPL); 105 (AAPL)
- `tests/data/test_feed_health.py`: 66 (AAPL); 78 (AAPL); 88 (AAPL); 103 (AAPL); 113 (AAPL); 131 (AAPL)
- `tests/data/test_fundamentals.py`: 10 (AAPL); 54 (AAPL); 55 (AAPL)
- `tests/data/test_fundamentals_cache.py`: 21 (AAPL); 55 (AAPL); 57 (AAPL); 64 (AAPL); 66 (AAPL); 70 (AAPL); 82 (AAPL); 84 (AAPL); 85 (AAPL); 94 (AAPL); 98 (AAPL); 103 (AAPL); 105 (AAPL); 112 (AAPL); 113 (AAPL); 121 (AAPL); 124 (AAPL); 134 (AAPL); 143 (SPY); 145 (SPY); 147 (SPY)
- `tests/data/test_history.py`: 59 (AAPL); 60 (AAPL); 62 (AAPL); 67 (AAPL); 68 (MSFT); 75 (AAPL); 84 (AAPL); 95 (AAPL); 99 (AAPL); 108 (AAPL)
- `tests/data/test_market_data_feed.py`: 32 (AAPL); 39 (AAPL); 55 (AAPL); 56 (AAPL); 71 (AAPL); 79 (AAPL); 92 (AAPL)
- `tests/data/test_mock_broker.py`: 14 (AAPL); 15 (AAPL); 23 (AAPL); 32 (AAPL); 39 (AAPL); 43 (AAPL); 53 (AAPL)
- `tests/data/test_news_corroboration.py`: 18 (US); 176 (US); 215 (US); 243 (US)
- `tests/data/test_panel_failure_names_the_source.py`: 10 (ALPACA)
- `tests/data/test_parquet_store.py`: 16 (AAPL); 17 (AAPL)
- `tests/data/test_quote_freshness.py`: 162 (AAPL); 167 (AAPL)
- `tests/data/test_sectors.py`: 4 (AAPL); 18 (AAPL); 19 (MSFT); 22 (SPY); 33 (AAPL); 43 (AAPL)
- `tests/data/test_symbol_pruning.py`: 3 (Alpaca); 12 (alpaca, Alpaca); 17 (Alpaca); 36 (AAPL, MSFT, NVDA, AMZN); 37 (Alpaca); 39 (alpaca); 42 (AAPL, MSFT, NVDA, AMZN); 47 (Alpaca); 49 (AAPL, MSFT, NVDA); 51 (AAPL, MSFT, NVDA); 57 (Alpaca); 59 (AAPL, MSFT, NVDA); 61 (AAPL, MSFT, NVDA); 72 (Alpaca, AAPL, MSFT, NVDA); 74 (alpaca); 75 (AAPL, MSFT, NVDA); 77 (AAPL, MSFT, NVDA); 85 (AAPL); 86 (AAPL); 93 (AAPL); 113 (Alpaca)
- `tests/data/test_symbols_asx.py`: 3 (US); 4 (Alpaca); 15 (US); 40 (AAPL)
- `tests/data/test_universe.py`: 11 (US); 19 (AAPL); 20 (AAPL); 22 (AAPL); 23 (MSFT); 28 (SPY, AAPL, MSFT, GOOGL); 39 (US)
- `tests/data/test_validation.py`: 32 (AAPL); 44 (AAPL); 45 (AAPL); 46 (AAPL); 63 (AAPL); 64 (AAPL); 79 (AAPL); 81 (America/New_York); 85 (America/New_York); 95 (AAPL); 96 (AAPL); 99 (AAPL); 113 (AAPL); 114 (AAPL); 117 (AAPL); 128 (AAPL)
- `tests/data/test_yfinance_fundamentals.py`: 16 (MSFT); 33 (SPY); 89 (MSFT); 92 (MSFT); 103 (MSFT); 113 (MSFT); 124 (MSFT); 137 (MSFT); 147 (MSFT); 157 (MSFT); 164 (MSFT); 175 (MSFT); 214 (SPY); 227 (SPY); 254 (AAPL); 265 (MSFT); 280 (MSFT); 286 (MSFT)
- `tests/data/test_yfinance_source.py`: 38 (AAPL, MSFT); 81 (AAPL); 82 (MSFT); 146 (SPY); 185 (AAPL); 194 (AAPL); 203 (AAPL); 214 (AAPL, MSFT); 219 (AAPL, MSFT); 250 (AAPL); 294 (AAPL); 319 (AAPL); 340 (AAPL); 350 (AAPL)
- `tests/domain/ai_advisory/test_context.py`: 8 (AAPL); 11 (AAPL); 16 (AAPL); 23 (AAPL); 41 (AAPL); 62 (AAPL); 79 (AAPL); 92 (AAPL); 104 (AAPL)
- `tests/domain/ai_advisory/test_prompts.py`: 13 (AAPL); 30 (AAPL); 36 (AAPL)
- `tests/domain/ai_advisory/test_router.py`: 18 (AAPL); 29 (AAPL)
- `tests/domain/autonomy/test_absent_price_refusal.py`: 30 (New York); 32 (US)
- `tests/domain/backtester/test_feature_ablation.py`: 45 (US)
- `tests/domain/backtester/test_manifest.py`: 307 (US); 314 (US); 317 (US)
- `tests/domain/backtester/test_market_cost_profiles.py`: 123 (US); 126 (US); 128 (US)
- `tests/domain/backtester/test_replay_opening_book.py`: 50 (SPY)
- `tests/domain/backtester/test_replay_regime.py`: 28 (US); 89 (SPY); 96 (SPY)
- `tests/domain/backtester/test_replay_starts_every_engine.py`: 7 (SPY); 75 (US)
- `tests/domain/backtester/test_research_universe.py`: 26 (US); 36 (US); 37 (US); 38 (SPY); 72 (US); 86 (US)
- `tests/domain/backtester/test_signal_adapter.py`: 94 (AAPL)
- `tests/domain/backtester/test_swing_dataset.py`: 339 (USD); 778 (USD); 891 (USD)
- `tests/domain/corporate_actions/test_announcement_store.py`: 3 (Alpaca); 42 (Alpaca)
- `tests/domain/evaluation/test_replay_agreement.py`: 100 (US)
- `tests/domain/macro_analysis/test_curve_calibration.py`: 10 (US); 19 (US); 24 (US); 28 (US)
- `tests/domain/macro_analysis/test_growth_axis.py`: 13 (US)
- `tests/domain/oms/test_adopted_positions.py`: 31 (AAPL)
- `tests/domain/oms/test_own_fill_identity.py`: 328 (Alpaca)
- `tests/domain/oms/test_signal_bridge_policy.py`: 75 (Alpaca)
- `tests/domain/performance/test_commission_audit.py`: 70 (USD)
- `tests/domain/performance/test_reporter_schedule.py`: 20 (America/New_York); 22 (US)
- `tests/domain/performance/test_scorecard_and_reports.py`: 262 (US); 263 (US); 268 (US); 347 (Alpaca)
- `tests/domain/performance/test_trade_shape_metrics.py`: 39 (AAPL)
- `tests/domain/regime_engine/test_feature_scaling.py`: 8 (US)
- `tests/domain/regime_engine/test_feature_selection.py`: 62 (US)
- `tests/domain/regime_engine/test_regime_engine.py`: 40 (SPY); 49 (SPY); 262 (SPY); 278 (SPY); 302 (Alpaca); 354 (SPY); 366 (SPY); 396 (SPY); 402 (SPY); 413 (SPY); 420 (AAPL); 421 (MSFT); 435 (SPY); 444 (SPY); 459 (SPY); 466 (SPY); 477 (SPY); 479 (SPY); 500 (SPY); 505 (SPY); 528 (SPY); 537 (SPY); 565 (SPY); 581 (SPY); 598 (SPY)
- `tests/domain/regime_engine/test_the_vix_source_is_not_hardcoded.py`: 4 (CBOE, US); 48 (US); 56 (US)
- `tests/domain/risk_engine/test_binding_pairs.py`: 112 (SPY)
- `tests/domain/risk_engine/test_cost_rail.py`: 157 (Alpaca)
- `tests/domain/risk_engine/test_kill_switch.py`: 116 (AAPL)
- `tests/domain/test_bus.py`: 18 (AAPL); 37 (AAPL); 66 (AAPL); 74 (AAPL); 90 (AAPL); 108 (AAPL); 124 (AAPL)
- `tests/domain/test_decision_journal.py`: 21 (SPY); 26 (SPY); 35 (SPY); 36 (SPY); 37 (SPY); 38 (SPY); 47 (SPY); 48 (AAPL)
- `tests/domain/test_display_dates.py`: 23 (US)
- `tests/domain/test_market_calendar.py`: 17 (America/New_York); 46 (US); 65 (US); 66 (US); 122 (US); 126 (US); 129 (US); 138 (US); 140 (US); 145 (US); 147 (US); 154 (US); 161 (US); 177 (US); 183 (US); 190 (US); 197 (US); 200 (US); 205 (US); 217 (US); 228 (US); 237 (US); 243 (US); 249 (US); 254 (US); 263 (US); 271 (US); 277 (US); 287 (US); 288 (US); 289 (US); 290 (US); 335 (US); 336 (US); 341 (US); 392 (US)
- `tests/domain/test_session_controller.py`: 16 (America/New_York); 18 (US); 50 (US); 143 (US); 144 (US); 170 (US); 231 (Alpaca)
- `tests/domain/test_session_time_display.py`: 46 (US)
- `tests/domain/test_warm_start.py`: 76 (SPY, AAPL); 78 (AAPL); 79 (SPY); 85 (SPY); 86 (AAPL); 96 (SPY, AAPL); 100 (SPY); 102 (SPY); 107 (SPY); 110 (SPY, AAPL, MSFT); 112 (AAPL, MSFT); 113 (SPY); 132 (Alpaca); 134 (AAPL, SPY); 144 (AAPL, SPY); 154 (SPY); 155 (AAPL, SPY)
- `tests/operational/test_operational_history.py`: 118 (USD)
- `tests/operational/test_operational_isolation.py`: 41 (alpaca); 261 (alpaca)
- `tests/presentation/test_balances_day_pnl_fallback.py`: 16 (Alpaca)
- `tests/presentation/test_balances_label_elision.py`: 19 (Alpaca)
- `tests/presentation/test_balances_levels.py`: 160 (Alpaca)
- `tests/presentation/test_balances_panel.py`: 14 (Alpaca); 26 (USD); 122 (US)
- `tests/presentation/test_broker_connection_test.py`: 4 (alpaca); 7 (Alpaca)
- `tests/presentation/test_close_prompt.py`: 106 (Alpaca); 111 (alpaca); 115 (Alpaca)
- `tests/presentation/test_corporate_action_visibility.py`: 304 (Alpaca)
- `tests/presentation/test_first_run_level.py`: 28 (alpaca, US)
- `tests/presentation/test_ibkr_wiring.py`: 175 (Alpaca)
- `tests/presentation/test_regime_note_acknowledgement.py`: 108 (US); 109 (US)
- `tests/presentation/test_risk_console_refusals.py`: 37 (US); 43 (US); 44 (US); 71 (AAPL); 72 (MSFT); 73 (NVDA)
- `tests/presentation/test_screener_screen.py`: 86 (US)
- `tests/presentation/test_session_panel.py`: 20 (America/New_York); 44 (US); 47 (US); 53 (US); 69 (US); 77 (US); 86 (US); 94 (US); 98 (US); 99 (US); 156 (US); 160 (US); 165 (US); 169 (US); 170 (US)
- `tests/presentation/test_settings_defaults_and_dirty.py`: 64 (Alpaca); 69 (alpaca); 73 (Alpaca)
- `tests/presentation/test_settings_screen.py`: 26 (US); 44 (alpaca); 45 (Alpaca); 51 (alpaca); 53 (alpaca); 56 (Alpaca, US); 57 (alpaca); 61 (alpaca)
- `tests/presentation/test_verdict_day_pnl_source.py`: 9 (Alpaca)
- `tests/safety/test_an_order_is_transmitted_once.py`: 77 (alpaca)
- `tests/safety/test_autonomous_executor.py`: 25 (America/New_York); 87 (AAPL); 207 (AAPL, MSFT, NVDA); 231 (AAPL); 233 (MSFT); 237 (AAPL); 251 (AAPL); 315 (AAPL); 319 (US); 331 (AAPL); 332 (MSFT); 336 (AAPL, MSFT)
- `tests/safety/test_autonomy_gate.py`: 20 (America/New_York); 23 (US); 45 (AAPL); 168 (AAPL, US); 171 (US); 173 (AAPL); 346 (AAPL); 363 (Alpaca); 472 (US); 473 (US)
- `tests/safety/test_broker_accepts_our_orders.py`: 4 (Alpaca); 12 (Alpaca); 34 (Alpaca); 35 (Alpaca); 69 (AAPL); 81 (Alpaca); 92 (Alpaca); 109 (Alpaca); 122 (Alpaca); 127 (Alpaca); 145 (Alpaca); 181 (Alpaca)
- `tests/safety/test_cash_check_fails_closed_without_a_price.py`: 5 (Alpaca); 6 (Alpaca); 26 (Alpaca)
- `tests/safety/test_delever_sweep.py`: 74 (Alpaca)
- `tests/safety/test_edge_estimator.py`: 54 (US); 57 (US); 58 (USD)
- `tests/safety/test_entry_allow_list.py`: 85 (AAPL); 98 (AAPL); 122 (AAPL); 124 (AAPL); 133 (AAPL); 135 (AAPL); 146 (AAPL)
- `tests/safety/test_foreign_holding_gate.py`: 53 (USD)
- `tests/safety/test_live_entry_price_correction.py`: 30 (Alpaca); 56 (Alpaca); 392 (Alpaca)
- `tests/safety/test_live_exit_price_correction.py`: 36 (Alpaca)
- `tests/safety/test_manual_close_end_to_end.py`: 50 (America/New_York); 51 (US); 55 (AAPL)
- `tests/safety/test_own_fills_and_duplicates.py`: 39 (Alpaca); 44 (Alpaca); 64 (Alpaca); 168 (Alpaca)
- `tests/safety/test_partial_fill_at_signoff.py`: 4 (Alpaca); 6 (alpaca); 50 (Alpaca)
- `tests/safety/test_pending_orders_are_retried.py`: 31 (America/New_York)
- `tests/safety/test_phase2_strategy_isolation.py`: 105 (alpaca)
- `tests/safety/test_phase3_auction_contract.py`: 12 (alpaca, Alpaca); 102 (Alpaca)
- `tests/safety/test_promotion_evidence_enforced.py`: 57 (America/New_York); 69 (AAPL)
- `tests/safety/test_promotion_evidence_gate.py`: 21 (America/New_York); 67 (AAPL)
- `tests/safety/test_protection_level_drift.py`: 57 (AAPL); 59 (AAPL); 61 (AAPL); 65 (AAPL); 69 (AAPL); 76 (AAPL); 80 (AAPL); 99 (AAPL); 102 (AAPL); 104 (AAPL); 113 (AAPL); 120 (AAPL)
- `tests/safety/test_protection_pending_is_not_unprotected.py`: 66 (AAPL); 82 (AAPL); 98 (AAPL); 101 (AAPL); 118 (AAPL); 121 (AAPL); 146 (AAPL); 148 (AAPL); 151 (AAPL); 158 (AAPL)
- `tests/safety/test_protective_stop_rearm.py`: 6 (Alpaca); 60 (AAPL, MSFT); 62 (AAPL); 68 (AAPL); 70 (AAPL); 78 (AAPL); 79 (AAPL); 85 (AAPL); 93 (AAPL); 95 (AAPL); 105 (AAPL); 106 (AAPL); 110 (AAPL); 115 (Alpaca); 118 (AAPL); 132 (AAPL); 134 (AAPL); 135 (AAPL); 238 (AAPL); 240 (AAPL); 245 (AAPL); 246 (AAPL); 255 (AAPL); 257 (AAPL); 268 (AAPL); 270 (AAPL); 273 (AAPL); 274 (AAPL)
- `tests/safety/test_reconciliation_adoption.py`: 75 (Alpaca); 77 (AAPL, MSFT); 82 (AAPL, MSFT); 88 (AAPL); 113 (AAPL); 127 (AAPL); 130 (AAPL); 142 (AAPL); 157 (AAPL); 166 (AAPL); 192 (AAPL); 201 (AAPL); 223 (AAPL); 238 (AAPL); 245 (AAPL); 285 (AAPL, MSFT); 289 (AAPL, MSFT); 296 (AAPL, MSFT); 300 (AAPL); 305 (AAPL); 309 (AAPL); 316 (AAPL); 325 (AAPL); 330 (AAPL); 348 (AAPL); 354 (AAPL)
- `tests/safety/test_unattended_end_to_end.py`: 27 (AAPL); 94 (New York); 104 (US)
- `tests/scripts/test_phase3_probe_guards.py`: 355 (NYSE)
- `tests/test_env_file.py`: 14 (US); 16 (US); 45 (US); 50 (US)
- `tests/test_logging_redaction.py`: 32 (AAPL); 37 (AAPL); 42 (MSFT); 47 (MSFT)
- `tests/test_m110_untrue_statements.py`: 140 (Alpaca)
- `tests/test_m111_trading_day.py`: 69 (US); 72 (America/New_York); 74 (US); 239 (US); 245 (US)
- `tests/test_m122_ledger_eras.py`: 4 (Alpaca, US); 6 (USD); 14 (USD); 16 (Alpaca, US); 70 (US, USD); 126 (US); 127 (USD); 140 (US); 148 (US); 167 (US, USD); 178 (USD)
- `tests/test_m127_equity_eras.py`: 8 (Alpaca, US); 13 (US); 35 (Alpaca); 41 (Alpaca)
- `tests/test_m128_tick_timestamps.py`: 106 (US); 112 (AAPL); 116 (AAPL); 120 (AAPL)
- `tests/test_m130_delay_claim.py`: 152 (US)
- `tests/test_m136_symbol_verdict.py`: 161 (SPY)
- `tests/test_manual_documents_every_setting.py`: 38 (alpaca); 64 (Alpaca)
- `tests/test_open_items_are_still_open.py`: 99 (Alpaca, US); 102 (alpaca, US)
- `tests/test_paths_and_migration.py`: 68 (US); 71 (US); 77 (US); 88 (US); 103 (US); 160 (US)
- `tests/test_preflight.py`: 110 (Alpaca, US); 112 (alpaca); 136 (US); 311 (alpaca); 318 (alpaca, US); 319 (alpaca); 323 (alpaca); 616 (Alpaca); 623 (Alpaca)
- `tests/test_session_record.py`: 91 (AAPL); 127 (AAPL); 181 (AAPL); 196 (MSFT); 199 (AAPL, MSFT); 217 (MSFT); 220 (MSFT)

## ASX dependency assessment

Assessment of each `src/` file follows. `Yes` means ASX execution, data, display, or historical isolation uses the file; it does not mean that its Alpaca/US branch is approved. `No` means the matched file is only an Alpaca/US adapter or generated history. Specific cross-market dependencies and Phase 2 references are called out below.

| Source file | ASX behaviour depends on file? | Finding |
| --- | --- | --- |
| `src/qat/config.py` | Yes | Shared settings; US remains the default market, a fail-open ASX risk. |
| `src/qat/data/alpaca_source.py` | No | Alpaca-only quote/history implementation. |
| `src/qat/data/broker/account_poller.py` | Yes | Shared broker account polling; Alpaca mention is historical. |
| `src/qat/data/broker/adapter.py` | Yes | Shared broker order/fill contracts; Alpaca references explain legacy semantics. |
| `src/qat/data/broker/alpaca_adapter.py` | No | Alpaca-only execution adapter. |
| `src/qat/data/broker/alpaca_client_protocol.py` | No | Alpaca-only client contract. |
| `src/qat/data/broker/capabilities.py` | Yes | Shared capability dispatch; still imports the retired adapter. |
| `src/qat/data/broker/ib_adapter.py` | Yes | ASX IBKR adapter; US/Alpaca mentions are historical comparisons. |
| `src/qat/data/broker/ib_translate.py` | Yes | ASX contract/order translation; US defaults and currency mapping coexist. |
| `src/qat/data/broker/mock_broker.py` | Yes | Mock ASX tests; USD default must be assessed before removal. |
| `src/qat/data/broker/simulated_broker.py` | Yes | ASX simulation; USD default and Alpaca comparisons coexist. |
| `src/qat/data/broker/ticks.py` | Yes | ASX price-step rules share a table with US ticks; preserve ASX entries. |
| `src/qat/data/earnings.py` | Yes | ASX earnings date conversion uses New York-stamped vendor values; several functions default to US. |
| `src/qat/data/fundamentals.py` | Yes | ASX fundamentals path; US ticker example is historical. |
| `src/qat/data/history.py` | Yes | ASX history resolver; still carries retired Alpaca branch. |
| `src/qat/data/ibkr_news.py` | No | Unwired IBKR news experiment; US symbols are historical positive controls. |
| `src/qat/data/instruments.py` | Yes | Shared instrument-name mapping includes ASX and US symbols. |
| `src/qat/data/news.py` | Yes | ASX news alias filtering explicitly excludes US OTC cross-listings. |
| `src/qat/data/sectors.py` | Yes | Shared sector mapping includes ASX and US symbols. |
| `src/qat/data/symbols.py` | Yes | ASX symbol conversion shares mapping with US; IBKR conversion defaults to US. |
| `src/qat/data/universe.py` | Yes | ASX watchlists share selector and benchmark table with US lists. |
| `src/qat/data/validation.py` | Yes | Shared bar validation defaults to New York exchange time. |
| `src/qat/data/yfinance_fundamentals.py` | Yes | ASX fundamentals parsing shares US provider examples. |
| `src/qat/data/yfinance_source.py` | Yes | ASX feed/history code has a historical SPY validation example. |
| `src/qat/domain/autonomy/executor.py` | Yes | ASX scheduling; US holiday reference explains a prior gate failure. |
| `src/qat/domain/autonomy/gate.py` | Yes | ASX suffix rule falls back to US for every non-.AX symbol. |
| `src/qat/domain/backtester/ablation.py` | Yes | Phase 2 ASX ablation uses US macro measures; protected backtester. |
| `src/qat/domain/backtester/macro_cache.py` | Yes | Phase 2 ASX replay shares a frozen macro cache with US; protected backtester. |
| `src/qat/domain/backtester/replay_session.py` | Yes | Phase 2 ASX replay includes US session/benchmark paths; protected backtester. |
| `src/qat/domain/backtester/research_universe.py` | Yes | Phase 2 ASX universe shares registry with US_G1; protected backtester. |
| `src/qat/domain/backtester/signal_adapter.py` | Yes | Phase 2 ASX adapter; AAPL result is historical; protected backtester. |
| `src/qat/domain/corporate_actions/announcements.py` | Yes | ASX action normalization retains Alpaca-era ratio evidence. |
| `src/qat/domain/corporate_actions/monitor.py` | Yes | ASX monitoring; Alpaca request-window comment is historical. |
| `src/qat/domain/decision_journal.py` | Yes | ASX decision journal; SPY example is historical. |
| `src/qat/domain/display_dates.py` | Yes | ASX display-date rules distinguish older US records. |
| `src/qat/domain/evaluation/refusals.py` | Yes | ASX evaluation must isolate Alpaca/US ledger era. |
| `src/qat/domain/macro_analysis/growth.py` | Yes | ASX macro interpretation explicitly considers US input. |
| `src/qat/domain/macro_analysis/signal.py` | Yes | ASX regime signal uses US VIX measure. |
| `src/qat/domain/market_calendar.py` | Yes | ASX calendar shares market type/dispatch with US calendar. |
| `src/qat/domain/oms/oms.py` | Yes | ASX OMS shares order/fill paths with Alpaca-era logic and comments. |
| `src/qat/domain/oms/reconciliation.py` | Yes | ASX reconciliation; Alpaca mention explains former mismatch. |
| `src/qat/domain/oms/signal_bridge.py` | Yes | ASX signal bridge; US ticker/Alpaca examples explain shared algorithms. |
| `src/qat/domain/performance/edge.py` | Yes | ASX edge estimates exclude US-era trades. |
| `src/qat/domain/performance/metrics.py` | Yes | ASX metrics isolate USD from AUD. |
| `src/qat/domain/performance/reporter.py` | Yes | ASX report selection shares market dispatch with US. |
| `src/qat/domain/performance/reports.py` | Yes | ASX reports; Alpaca exception is historical. |
| `src/qat/domain/performance/trades.py` | Yes | ASX ledger/reporting depends on explicit Alpaca/US era isolation. |
| `src/qat/domain/regime_engine/engine.py` | Yes | ASX regime engine; Alpaca timestamp comment is historical. |
| `src/qat/domain/regime_engine/feature_matrix.py` | Yes | ASX feature matrix may ingest US VIXCLS. |
| `src/qat/domain/risk_engine/audit.py` | Yes | ASX risk audit distinguishes historical USD/US records. |
| `src/qat/domain/risk_engine/engine.py` | Yes | ASX risk engine; Alpaca commission comparison is historical. |
| `src/qat/domain/session_controller.py` | Yes | ASX session control shares US market default and history. |
| `src/qat/preflight.py` | Yes | ASX startup checks include retired Alpaca rejection and US VIX warnings. |
| `src/qat/presentation/advisory_account.py` | Yes | ASX advisory balances suppress Alpaca-era previous-close assumption. |
| `src/qat/presentation/balances_panel.py` | Yes | ASX balances display handles older Alpaca/US fields. |
| `src/qat/presentation/runtime.py` | Yes | ASX runtime resolver still contains Alpaca broker/feed branches. |
| `src/qat/presentation/screener.py` | Yes | ASX screener shares a US market selector and symbol lists. |
| `src/qat/presentation/session_panel.py` | Yes | ASX session panel shares a US default and dual-market display. |
| `src/qat/presentation/settings.py` | Yes | ASX settings UI still offers US market and Alpaca credentials/feed. |
| `src/qat/version.py` | No | Generated version/change-history notes; no ASX decision path. |

### Stop-point findings

No match was found in `src/qat/domain/strategies/authoritative_swing/`. Matches **were found in the Phase 2 backtester**: `ablation.py`, `macro_cache.py`, `replay_session.py`, `research_universe.py`, and `signal_adapter.py`. The backtester is protected by the prior instruction and was not changed.

ASX behaviour also depends on shared US/Alpaca-era logic outside the backtester: the New York-stamped earnings conversion, US OTC alias rejection for ASX news, ledger-era/currency separation, common calendar/tick/IBKR translation tables, and market defaults/dispatch. The `market="US"` settings default is a current fail-open risk. These dependencies require design review before removal. **This branch stops at inventory; no Alpaca or US path, test, or ASX assertion was removed or changed.**
