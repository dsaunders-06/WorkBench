# ASX-only removal proof — 20 October 2026

This report accompanies `cleanup/asx-only`. QAT was not started; no Gateway, order, or account store was accessed. The CI result is recorded in the review handoff after the branch push.

## Scope and retained historical dependencies

- The selectable broker is mock or IBKR; the selectable market is ASX; Alpaca market data is invalid. Synthetic data remains a selectable offline source and the ASX paper preflight still fails it.
- The old broker-versus-market preflight refusal covered Alpaca or IBKR paired with a US/ASX market choice. Settings now rejects Alpaca and US before preflight. No allowed selector combination reaches that refusal, so the obsolete preflight check was removed.
- ASX normalisation of inputs such as `BHP-AX` to `BHP.AX` remains and has dedicated tests. The ASX watchlist and side-table assertions from the deleted Alpaca symbol-pruning file were moved to an ASX-specific test.
- New York-stamped ASX earnings conversion, FRED macro inputs to the ASX regime, historical USD ledger rows, and Phase 2 research dependencies are retained. The five protected Phase 2 backtester source files and authoritative swing strategy were not changed.
- Old evidence and dated reports remain historical. The user manual and current narrative documents carry historical notices where they describe US/Alpaca operation.

## Production files changed

- `src/qat/config.py`
- `src/qat/data/alpaca_source.py` — deleted
- `src/qat/data/broker/alpaca_adapter.py` — deleted
- `src/qat/data/broker/alpaca_client_protocol.py` — deleted
- `src/qat/data/broker/capabilities.py`
- `src/qat/data/broker/ib_translate.py`
- `src/qat/data/broker/mock_broker.py`
- `src/qat/data/broker/simulated_broker.py`
- `src/qat/data/broker/ticks.py`
- `src/qat/data/earnings.py`
- `src/qat/data/history.py`
- `src/qat/data/symbols.py`
- `src/qat/data/universe.py`
- `src/qat/data/validation.py`
- `src/qat/domain/autonomy/gate.py`
- `src/qat/domain/market_calendar.py`
- `src/qat/domain/performance/reporter.py`
- `src/qat/domain/session_controller.py`
- `src/qat/preflight.py`
- `src/qat/presentation/runtime.py`
- `src/qat/presentation/screener.py`
- `src/qat/presentation/session_panel.py`
- `src/qat/presentation/settings.py`

## Files deleted outside production

- `scripts/analysis/capture_split_state.py`
- `scripts/analysis/exercise_m54.py`
- `scripts/analysis/probe_alpaca_splits.py`
- `scripts/analysis/probe_entry_basis.py`
- `scripts/analysis/probe_feed_entitlement.py`
- `scripts/analysis/probe_live_announcements.py`
- `scripts/analysis/probe_mark_source.py`
- `scripts/analysis/probe_market_data.py`
- `scripts/analysis/realised_slippage.py`
- `scripts/analysis/verify_gating_figures.py`
- `scripts/analysis/when_do_trades_land.py`
- `scripts/migrate_ledger_eras.py`
- `scripts/retire_alpaca_era.py`
- `tests/data/broker/test_alpaca_adapter.py`
- `tests/data/test_alpaca_source.py`
- `tests/data/test_symbol_pruning.py`

## Deleted or retargeted original tests

Every original test function removed from the branch base is listed below. The description states the US or Alpaca behavior that it covered; a replacement is called out where ASX or fail-closed coverage remains. Assertions of existing ASX tests were preserved except the specifically approved Alpaca-source preflight change and the separately approved historical guard retarget.

### `tests/data/broker/test_account_balances.py`

- `test_the_balance_sheet_is_translated_from_the_broker` — The balance sheet is translated from the broker.
- `test_unreported_fields_stay_none_rather_than_becoming_zero` — Unreported fields stay NONE rather than becoming zero.
- `test_the_cash_rule_still_sees_a_concrete_number` — The cash rule still sees a concrete number.

### `tests/data/broker/test_alpaca_adapter.py`

- `test_account_translates_alpacas_string_fields` — Account translates alpacas string fields.
- `test_positions_are_translated` — Positions are translated.
- `test_the_current_mark_is_carried_so_the_risk_cap_can_use_it` — The current mark is carried so the risk cap can use it.
- `test_a_broker_reporting_no_mark_yields_None_not_zero` — A broker reporting no mark yields NONE not zero.
- `test_place_order_submits_and_adopts_the_broker_order_id` — Place order submits and adopts the broker order id.
- `test_place_order_reports_what_actually_filled_not_what_was_asked` — Place order reports what actually filled not what was asked.
- `test_place_order_leaves_an_unfilled_order_at_its_requested_size` — Place order leaves an unfilled order at its requested size.
- `test_cancel_order_calls_through_and_returns_the_order` — Cancel order calls through and returns the order.
- `test_defaults_to_the_paper_endpoint` — Defaults to the paper endpoint.
- `test_live_mode_requires_explicit_confirmation` — Live mode requires explicit confirmation.
- `test_live_mode_with_confirmation_targets_the_live_endpoint` — Live mode with confirmation targets the live endpoint.
- `test_status_mapping` — Status mapping.
- `test_market_data_is_explicitly_unsupported` — Market data is explicitly unsupported.
- `test_a_bracketed_entry_is_gtc_so_its_stop_outlives_the_session` — A bracketed entry is GTC so its stop outlives the session.
- `test_a_plain_entry_stays_day` — A plain entry stays day.
- `test_a_protective_stop_is_submitted_as_a_stop_order_gtc` — A protective stop is submitted as a stop order GTC.
- `test_a_stop_order_without_a_stop_price_is_refused_before_submission` — A stop order without a stop price is refused before submission.
- `test_a_stop_with_a_target_is_submitted_as_a_single_oco` — A stop with a target is submitted as a single OCO.
- `test_an_oco_stop_leg_counts_as_resting_protection` — An OCO stop leg counts as resting protection.
- `test_the_orders_query_asks_for_nested_legs` — The orders query asks for nested legs.
- `test_a_live_leg_under_a_filled_parent_is_seen` — A live leg under a filled parent is seen.
- `test_a_dead_leg_is_not_read_as_protection` — A dead leg is not read as protection.
- `test_the_scan_is_bounded_by_the_symbols_actually_held` — The scan is bounded by the symbols actually held.
- `test_nothing_held_asks_the_broker_nothing` — Nothing held asks the broker nothing.
- `test_a_symbol_the_broad_scan_misses_is_looked_up_before_it_reads_naked` — A symbol the broad scan misses is looked up before it reads naked.
- `test_a_leg_that_fills_today_is_seen_though_its_parent_is_months_old` — A leg that fills today is seen though its parent is months old.
- `test_the_window_is_applied_to_fill_time_not_submission_time` — The window is applied to fill time not submission time.
- `test_the_fill_query_is_bounded_by_symbol_and_not_by_submission_date` — The fill query is bounded by symbol and not by submission date.
- `test_tracking_nothing_asks_the_broker_nothing` — Tracking nothing asks the broker nothing.
- `test_the_deep_scan_stops_rather_than_walking_forever` — The deep scan stops rather than walking forever.
- `test_a_forward_split_ratio_is_new_over_old` — A forward split ratio is new over old.
- `test_a_reverse_split_inverts_the_ratio` — A reverse split inverts the ratio.
- `test_the_query_is_bounded_by_symbol` — The query is bounded by symbol.
- `test_a_record_with_no_ex_date_is_skipped` — A record with no ex date is skipped.
- `test_a_record_with_no_rates_is_skipped` — A record with no rates is skipped.
- `test_a_payable_date_before_the_ex_date_is_kept_as_is` — A payable date before the ex date is kept as is.
- `test_a_datetime_ex_date_is_narrowed_to_a_date` — A datetime ex date is narrowed to a date.
- `test_no_announcements_is_an_empty_list` — No announcements is an empty list.
- `test_a_range_inside_the_cap_is_one_request` — A range inside the cap is one request.
- `test_a_range_over_the_cap_is_split_and_every_piece_fits` — A range over the cap is split and every piece fits.
- `test_the_windows_are_contiguous_and_cover_the_whole_range` — The windows are contiguous and cover the whole range.
- `test_an_inverted_range_asks_nothing` — An inverted range asks nothing.
- `test_the_adapter_issues_one_request_per_window` — The adapter issues one request per window.
- `test_a_record_returned_by_two_windows_is_reported_once` — A record returned by two windows is reported once.

### `tests/data/broker/test_ib_contracts.py`

- `test_a_us_symbol_is_unchanged` — A US symbol is unchanged.
- `test_a_class_share_keeps_its_dot` — A class share keeps its dot.
- `test_a_us_contract_is_unchanged` — A US contract is unchanged.
- `test_a_us_position_is_unchanged` — A US position is unchanged.

### `tests/data/broker/test_ib_recent_fills.py`

- `test_a_us_fill_keeps_its_plain_symbol` — A US fill keeps its plain symbol.

### `tests/data/broker/test_ib_resting_stops.py`

- `test_a_us_symbol_keeps_its_plain_form` — A US symbol keeps its plain form.

### `tests/data/broker/test_ib_tick_rounding.py`

- `test_a_us_order_is_unchanged_at_a_cent` — A US order is unchanged at a cent.

### `tests/data/broker/test_ticks.py`

- `test_the_us_tick_is_a_cent_everywhere_this_system_trades` — The US tick is a cent everywhere this system trades.

### `tests/data/test_alpaca_source.py`

- `test_latest_trades_become_ticks` — Latest trades become ticks.
- `test_the_configured_feed_is_sent_on_the_request` — The configured feed is sent on the request.
- `test_a_failed_poll_yields_no_ticks_rather_than_raising` — A failed poll yields no ticks rather than raising.
- `test_zero_or_missing_prices_are_skipped` — Zero or missing prices are skipped.
- `test_the_stream_keeps_retrying_instead_of_ending` — The stream keeps retrying instead of ending.
- `test_backoff_grows_while_down_and_is_capped` — Backoff grows while down and is capped.
- `test_a_recovered_feed_yields_again_and_says_so` — A recovered feed yields again and says so.
- `test_daily_bars_are_translated_without_gap_filling` — Daily bars are translated without gap filling.
- `test_history_falls_back_to_synthetic_but_records_that_it_did` — History falls back to synthetic but records that it did.
- `test_settings_can_select_alpaca_for_both_sources` — Settings can select alpaca for both sources.
- `test_every_documented_feed_is_accepted` — Every documented feed is accepted.
- `test_daily_bars_are_requested_split_and_dividend_adjusted` — Daily bars are requested split and dividend adjusted.
- `test_bulk_daily_bars_are_adjusted_too` — Bulk daily bars are adjusted too.

### `tests/data/test_earnings_asx_fallback.py`

- `test_the_same_instant_reads_as_the_new_york_date_for_a_US_symbol` — The same instant reads as the new york date for a US symbol.

### `tests/data/test_earnings_calendar.py`

- `test_a_us_holiday_is_not_counted` — Retargeted to the Australia Day holiday.

### `tests/data/test_symbol_pruning.py`

- `test_the_one_bad_symbol_is_found_and_dropped` — The one bad symbol is found and dropped.
- `test_several_bad_symbols_are_all_found` — Several bad symbols are all found.
- `test_a_clean_watchlist_costs_exactly_one_probe` — A clean watchlist costs exactly one probe.
- `test_a_total_outage_does_not_empty_the_watchlist` — A total outage does not empty the watchlist.
- `test_class_shares_translate_between_vendor_conventions` — Class shares translate between vendor conventions.
- `test_canonical_accepts_a_watchlist_typed_either_way` — Canonical accepts a watchlist typed either way.
- `test_the_default_watchlist_uses_the_broker_convention` — Its US class-share check was retired; its ASX watchlist and side-table checks were moved to `test_builtin_asx_watchlists_and_side_tables_use_canonical_symbols`.

### `tests/data/test_symbols_asx.py`

- `test_a_us_class_share_is_still_translated` — A US class share is still translated.
- `test_the_round_trip_is_stable_for_both_markets` — Retargeted to the ASX round trip; the ASX assertion remains.

### `tests/data/test_universe.py`

- `test_watchlist_tables_are_non_empty_for_both_markets` — Retargeted to the ASX watchlist tables; the ASX assertion remains.
- `test_resolve_watchlist_curated_matches_settings_default` — Retargeted to the new ASX default watchlist.

### `tests/domain/backtester/test_market_cost_profiles.py`

- `test_us_trading_does_not_inherit_australian_pricing` — US trading does not inherit australian pricing.

### `tests/domain/test_market_calendar.py`

- `test_us_market_is_closed_on_holidays` — US market is closed on holidays.
- `test_us_thanksgiving_is_the_fourth_thursday_not_the_last` — US thanksgiving is the fourth thursday not the last.
- `test_a_saturday_holiday_is_observed_on_the_friday_before` — A saturday holiday is observed on the friday before.
- `test_a_sunday_holiday_is_observed_on_the_monday_after` — A sunday holiday is observed on the monday after.
- `test_the_two_markets_have_genuinely_different_calendars` — The two markets have genuinely different calendars.
- `test_weekends_are_closed_for_both_markets` — Weekends are closed for both markets.
- `test_market_is_closed_before_the_open` — Market is closed before the open.
- `test_market_is_closed_after_the_close` — Market is closed after the close.
- `test_us_session_phases` — US session phases.
- `test_a_holiday_session_reports_closed_with_a_reason` — A holiday session reports closed with a reason.
- `test_open_markets_switches_by_the_clock` — Open markets switches by the clock.
- `test_black_friday_is_an_early_close_and_shifts_the_phase_boundaries` — Black friday is an early close and shifts the phase boundaries.
- `test_after_an_early_close_the_market_reads_closed` — After an early close the market reads closed.
- `test_opening_volatility_is_not_eligible_for_unattended_execution` — Opening volatility is not eligible for unattended execution.
- `test_midday_lull_is_not_eligible_for_unattended_execution` — Midday lull is not eligible for unattended execution.
- `test_morning_trend_is_eligible` — Morning trend is eligible.
- `test_a_closed_market_is_never_eligible` — A closed market is never eligible.
- `test_next_open_skips_the_weekend` — Next open skips the weekend.
- `test_next_open_skips_a_holiday` — Next open skips a holiday.
- `test_next_open_is_later_today_when_called_before_the_bell` — Next open is later today when called before the bell.
- `test_us_never_reaches_an_auction_state` — US never reaches an auction state.

### `tests/domain/test_session_time_display.py`

- `test_the_us_market_gets_its_own_zone` — The US market gets its own zone.

### `tests/presentation/test_close_prompt.py`

- `test_an_entered_key_is_flagged_without_being_shown` — An entered key is flagged without being shown.

### `tests/presentation/test_regime_note_acknowledgement.py`

- `test_the_caption_follows_the_MARKET_not_the_machine` — The caption follows the MARKET not the machine.

### `tests/presentation/test_settings_defaults_and_dirty.py`

- `test_an_entered_api_key_is_reported_but_never_echoed` — An entered API key is reported but never echoed.

### `tests/presentation/test_settings_screen.py`

- `test_alpaca_feed_row_hides_label_and_field_together` — Alpaca feed row hides label and field together.

### `tests/safety/test_autonomy_gate.py`

- `test_the_symbol_suffix_routes_to_the_right_market_calendar` — Retargeted to ASX routing and refusal of unsuffixed US symbols.
- `test_the_us_open_is_unaffected` — The US open is unaffected.

### `tests/test_m111_trading_day.py`

- `test_trading_date_still_works_for_the_US_market` — Trading date still works for the US market.
- `test_a_US_runtime_gets_new_york_not_sydney` — A US runtime gets new york not sydney.

### `tests/test_m122_ledger_eras.py`

- `test_the_currency_map_covers_every_market` — Retargeted to the ASX/AUD mapping; that assertion remains.

### `tests/test_preflight.py`

- `test_asx_with_a_us_only_data_source_fails` — Retargeted, with DS approval, to Settings rejection of the retired Alpaca data source.
- `test_ibkr_against_a_us_watchlist_warns` — IBKR against a US watchlist warns.
- `test_the_corporate_action_note_is_derived_not_asserted` — The corporate action note is derived not asserted.

## Required verification

- Focused affected tests: 109 passed. The added ASX calendar assertion and its restored predecessor passed together (2 tests).
- ASX symbol tests, including the moved watchlist guard: 13 passed.
- Unchanged close-script, Phase 3 card, probe-guard, and exit-readiness tests: 106 passed.
- Final full suite: 4,471 passed, 24 skipped (1,095 warnings from async-test cleanup and numerical-library deprecations).
- Ruff, Black, mypy, and Bandit: passed.
- CI: reported in the review handoff after push.
