# Phase 2C market-regime proxy source audit

The strategy-independent proxy uses 200 complete end-month S&P/ASX 200 observations, January 2010 to August 2026. The [ASX current table](https://www.asx.com.au/about/market-statistics/historical-market-statistics) and [archive](https://www.asx.com.au/about/market-statistics/historical-market-statistics/historical-market-statistics-archive) are the approved monthly source. The [RBA F18 archive](https://www.rba.gov.au/statistics/tables/pdf-disc/f18.pdf) supplies 37 overlapping monthly values, May 2021 to May 2024. [RBA lists F18 as discontinued](https://www.rba.gov.au/statistics/discontinued-data.html); its PDF lacks ten years of monthly rows. Yahoo ^AXJO daily closes supply realised volatility only, except the one September 2023 month-end value selected by the operator's discrepancy rule.

## Frozen inputs

Raw snapshots are outside the repository at C:\Users\mailm\Documents\Codex\phase2c-market-regime-snapshots. Retrieval was on 4 October 2026 UTC. The external source-manifest.json records exact times, URLs, acquisition call, byte counts and hashes. No strategy outcome, trade result, static-cache or promotion data was used.

| Frozen file | Source URL | Retrieved UTC | SHA-256 |
| --- | --- | --- | --- |
| rba-f18-discontinued-2024.pdf | https://www.rba.gov.au/statistics/tables/pdf-disc/f18.pdf | 12:01:03.906 | e62d6f5abdec8d6a88afe57ef7d22f658eb8752713992e6bcfb7ae8e413ed5d6 |
| asx-historical-market-statistics.html | https://www.asx.com.au/about/market-statistics/historical-market-statistics | 12:01:04.015 | 0ae81e7cb9e2454d3c278449978ce989496e74227cb956fe50683809a4fca30c |
| asx-historical-market-statistics-archive.html | https://www.asx.com.au/about/market-statistics/historical-market-statistics/historical-market-statistics-archive | 12:01:04.063 | 3deda2aa6b8cfe43aaa70eae7ba1bf14540612925111297f8364e8dc0de1766a |
| yfinance-AXJO-daily-close-2010-2026-08.csv | https://finance.yahoo.com/quote/%5EAXJO/history/ | 12:01:48.322742 | b1017f700c50c95fdeb0a202658e4b835838eac02f119eb536c450ab0179dc4d |
| asx-cash-market-week-2023-09-29.pdf (date evidence only) | https://www.asx.com.au/content/dam/asx/markets/trade-our-cash-market/acmr/2023/september/acmr-weekly-20230929.pdf | 12:18:03.447 | 74abed65137560b57ba25624ac05efae8d7bd363a78469d5efc1692cc3e9f3bb |

The daily snapshot contains 4,205 closes from 4 January 2010 through 31 August 2026. Acquisition used yfinance 1.7.0 with symbol ^AXJO, start 2010-01-01, exclusive end 2026-09-01, auto_adjust=False, actions=False, repair=False, threads=False; only Close was retained. The ASX tables pass checks for 200 unique consecutive months, descending order within each year, and January–December coverage in each year before 2026 (January–August 2026).

## Discrepancy decisions

The return gate is a strict difference greater than 0.1 percentage point in simple month-on-month returns. Two anomalous ASX levels create four flagged returns as each level reverts the following month.

| Month | ASX end-month level | Yahoo final bar date / close | ASX return | Yahoo return | ASX − Yahoo | Decision |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| July 2014 | 5623.9 | 31 Jul 2014 / 5632.8999 | 4.229294% | 4.396088% | −0.166794 pp | Keep ASX; run Yahoo substitution sensitivity. |
| August 2014 | 5625.9 | 29 Aug 2014 / 5625.9000 | 0.035563% | −0.124270% | +0.159832 pp | July level causes this return gap. |
| September 2023 | 7084.6 | 29 Sep 2023 / 7048.6001 | −3.021094% | −3.513883% | +0.492789 pp | Use Yahoo; RBA F18 supports it. |
| October 2023 | 6780.7 | 31 Oct 2023 / 6780.7002 | −4.289586% | −3.800753% | −0.488833 pp | September level causes this return gap. |

The ASX tables name end-month values but not the trading date. I stepped backward from each civil month end with the repository [ASX market calendar](../src/qat/domain/market_calendar.py), whose is_trading_day rule combines weekdays, ASX public holidays and explicit extra closures. It returns 31 July 2014 and 29 September 2023; neither month has a listed ASX holiday or extra closure. Yahoo's final bars have those same dates. The [ASX cash market report for 25–29 September 2023](https://www.asx.com.au/content/dam/asx/markets/trade-our-cash-market/acmr/2023/september/acmr-weekly-20230929.pdf) independently records trading on 29 September. The repository calendar is rules-based and has no signed historical exchange-session ledger, so July 2014 remains an inferred date supported by the Yahoo bar, not a separately verified official session record. No date mismatch is evident for either disputed month.

For September 2023, RBA F18 Australia is 570.8 in August, 550.8 in September and 529.8 in October. RBA's September return is −3.503854%, 0.010029 pp from Yahoo and 0.482760 pp from ASX. Its October return is −3.812636%, 0.011883 pp from Yahoo and 0.476950 pp from ASX. Among the 36 RBA overlap returns, RBA–Yahoo has no 0.1 pp breach, while RBA–ASX has these two. This supports Yahoo's September level under the approved two-of-three rule.

For July 2014, the RBA PDF has no monthly row. The [S&P DJI index page](https://www.spglobal.com/spdji/en/indices/equity/sp-asx-200/) did not expose a July 31, 2014 close, and the [ASX cash market report archive](https://www.asx.com.au/markets/trade-our-cash-market/australian-cash-market-report) begins in 2021. No eligible official third July close was accessible. The approved fallback retains ASX 5623.9 and repeats the analysis with Yahoo 5632.8999. The sensitivity does not change the recommended persistence set.

## Persistence estimate

Monthly return is log(P_m/P_(m-1)); absolute return is its magnitude. Monthly realised volatility is sqrt(252 × mean(daily log return squared)) from Yahoo daily closes, with January 2010 dropped because the previous December close is absent. Each series has 199 monthly observations. The table gives ordinary sample autocorrelation at monthly lags.

| Lag | Monthly return | Absolute return | Realised volatility |
| ---: | ---: | ---: | ---: |
| 1 | −0.0875 | 0.2435 | 0.4524 |
| 2 | −0.1422 | 0.1272 | 0.2689 |
| 3 | 0.0210 | 0.0095 | 0.2401 |
| 4 | −0.1010 | −0.0074 | 0.1471 |
| 5 | −0.0169 | −0.0848 | 0.0621 |
| 6 | 0.0424 | −0.0230 | 0.0383 |
| 7 | 0.0235 | 0.0341 | 0.0719 |
| 8 | −0.0680 | 0.0416 | 0.0328 |
| 9 | −0.0228 | −0.0287 | −0.0173 |
| 10 | −0.0220 | −0.0699 | −0.0383 |
| 11 | −0.0798 | −0.0949 | −0.0648 |
| 12 | 0.0817 | −0.0679 | −0.1087 |

Under an AR(1) approximation, log(0.5)/log(ACF at lag 1) gives half-lives of 0.49 month for absolute returns and 0.87 month for realised volatility. Monthly returns have negative lag-one correlation and no positive exponential half-life. These are descriptive estimates, not fitted regime durations. Realised-volatility autocorrelation remains positive through lag 4 (0.1471) and drops to 0.0621 at lag 5. The recommended mandatory generic persistence set is 1, 2, 3 and 4 months, in addition to calibrated block-resampled scenarios. Six and twelve months are disclosed sensitivity scenarios; the 36-month holdout cannot reliably qualify a 12-month persistence method.

Replacing July 2014 with Yahoo changes the return and absolute-return autocorrelations by at most 0.0009 and 0.0007; realised-volatility values are unchanged. The half-lives and 1–4-month recommendation are unchanged. Lag 4 realised-volatility correlation is only just above the rough white-noise reference band ±1.96/sqrt(199) ≈ ±0.139, so the four-month boundary is conservative, not a precise duration estimate.

## Regeneration

From the repository root, the current Codex host provides pypdf in its bundled Python site-packages. The project virtual environment already has beautifulsoup4. This command uses those existing dependencies:

    $env:PYTHONPATH = "C:\Users\mailm\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages"
    .\.venv\Scripts\python.exe scripts\research\phase2_market_regime_proxy.py C:\Users\mailm\Documents\Codex\phase2c-market-regime-snapshots
    .\.venv\Scripts\python.exe -m pytest -q tests\research\test_phase2_market_regime_proxy.py

The script verifies all five snapshot hashes, rejects missing, duplicate or unordered ASX months, checks final trading dates against the repository ASX calendar, enforces the 0.1 pp return gate and approved decisions, then prints both persistence runs as JSON. The saved regeneration command exited 0 on 4 October 2026 and reproduced 200 ASX months, 37 RBA months, 4,205 daily bars, the four ASX–Yahoo return flags and all reported autocorrelations. It downloads nothing. New inputs must be fetched only from the approved ASX, RBA and Yahoo URLs above, with the acquisition call and original hashes preserved here.
