"""Turning one rail off, without editing the code that decides trades (W2 step 6).

A rail is disabled by setting its existing `Settings` value beyond reach, so the
shipped `RiskEngine` and `PortfolioGovernor` run exactly as they trade. Nothing
in the trading path is edited, which is what makes this compatible with a freeze
whose test is *would this change which trades happen*.

REJECTED, and it will be proposed again: threading a rail set through
`RiskEngine` and `PortfolioGovernor` with `if enabled(...)` guards. "Off" would
be genuinely off, and the two imperfect rows below would disappear. It puts new
branches inside the code that decides which trades happen, and a guard
defaulting to on is still an edit to the decision path - as well as a second
implementation of the rules this whole harness exists to avoid having.

TWO RAILS CANNOT BE MADE PERFECTLY ABSENT, and `IMPERFECT` says so rather than
the table pretending otherwise:

* the aggregate cap at 1.0 still refuses when risk-at-stop reaches 100% of
  equity, which is reachable through positions carrying no known stop;
* cost-to-risk at 1.0 still refuses a trade whose round trip exceeds its whole
  1R.

Every value here is inside its field's own validator, and
`test_every_neutral_value_survives_its_own_validator` constructs each one rather
than trusting this sentence.
"""

from __future__ import annotations

from collections.abc import Sequence

from qat.config import Settings

# The regime gate has no knob: it arrives as `RegimeEvent.exposure_scalar`.
# Ablating it means not starting the regime engine, which is the caller's job -
# accepted by name here so one list can name every rail.
REGIME_RAIL = "regime_gate"

# Refused by name, with the reason, because it is the one plausible-looking
# choice that would silently confound a result. `apply_costs_in_paper` is read
# by `RiskEngine._costs_apply` for the RAIL and by `TradeLedger.__init__` for
# whether costs are charged into recorded P&L.
_TWO_CONSUMERS = {
    "apply_costs_in_paper": (
        "`apply_costs_in_paper` has two consumers - the cost rail and the trade ledger's "
        "cost accounting. Disabling it would switch off the rail AND make every recorded "
        "trade free, so the no-rail arm would win for a reason that has nothing to do with "
        "the rail. Ablate `cost_to_risk` instead."
    )
}

RAILS: dict[str, dict[str, object]] = {
    "position_limit": {"max_concurrent_positions": 10_000},
    "aggregate_risk_cap": {"max_aggregate_risk_at_stop_pct": 1.0},
    "single_name_cap": {"max_single_name_concentration_pct": 1.0},
    "sector_cap": {"max_sector_concentration_pct": 1.0},
    # BOTH knobs. The percentage alone leaves a perfectly correlated pair still
    # forming a cluster; the threshold alone leaves the cap in place for one.
    "correlated_cluster": {
        "correlation_cluster_threshold": 1.0,
        "max_correlated_cluster_pct": 1.0,
    },
    "gap_risk": {"max_gap_risk_at_shock_pct": 1.0},
    "portfolio_es": {"portfolio_es_limit_pct": 1e6},
    "cost_to_risk": {"max_cost_to_risk_pct": 1.0},
    "minimum_hold": {"enforce_min_holding_period": False},
    "time_stop": {"enforce_time_stop": False},
    "churn_cap": {"max_entries_per_week": 10_000},
    "earnings_trim": {"enforce_earnings_event_risk": False},
}

# Neither is perfectly absent when neutralised. Named so the manifest can state
# it rather than a reader having to remember it.
IMPERFECT: dict[str, str] = {
    "aggregate_risk_cap": "still refuses at 100% of equity at risk",
    "cost_to_risk": "still refuses a round trip exceeding the whole 1R",
}


# ⚠️ Regime FEATURE columns, which are a different question from rails and get
# their own table (Milestone C). A rail is a Settings knob set beyond reach; a
# feature is a column omitted from `regime_features`.
#
# Each entry is a claim about consequence, not a wish list.
FEATURES: dict[str, str] = {
    "vix_level": "the incumbent volatility measure (VIXCLS - US)",
    "yield_curve_slope": "the recession term (T10Y3M - US)",
    "credit_spread": "the stress term (BAA10Y - US, and +0.004 against forward ASX vol)",
    "breadth": "the participation term, derived from the traded universe",
}

# ⚠️ REFUSED, with the reason, the way `_TWO_CONSUMERS` refuses
# `apply_costs_in_paper`. `hmm_core._characterize_states` reads these two
# columns' means to build each fitted state's signature, and
# `fusion.score_from_hmm` turns those into the z-scores that decide which state
# is called bull and which bear. hmmlearn numbers states arbitrarily, so this is
# the only thing that gives an index a NAME.
#
# Removing either would not ablate a signal. It would RENAME every label, and
# the run would look entirely normal - which is worse than an error.
UNABLATABLE_FEATURES: dict[str, str] = {
    name: (
        f"{name!r} is not an ordinary feature: `fusion` reads its state statistics to "
        f"decide which fitted state is called bull and which bear. Ablating it would not "
        f"remove a signal, it would RENAME every label - and the run would still look "
        f"normal. Ablate one of: {', '.join(sorted(FEATURES))}."
    )
    for name in ("log_return", "realized_vol")
}


class UnablatableFeature(ValueError):
    """A regime feature this module will not neutralise.

    Its own class rather than a reuse of `UnablatableRail`, so a caller can tell
    a rail problem from a feature problem without parsing a message - and so
    `--feature cost_to_risk`, a real name in the wrong arm, cannot be caught by
    a handler meant for something else.
    """


def feature_settings(base: Settings, disabled: Sequence[str]) -> Settings:
    """`base` with every named feature column removed from `regime_features`.

    Re-validated rather than copied, for the reason `ablated_settings` gives:
    `model_copy(update=...)` writes fields without running their validators.
    """
    if not disabled:
        return base
    for feature in disabled:
        if feature in UNABLATABLE_FEATURES:
            raise UnablatableFeature(UNABLATABLE_FEATURES[feature])
        if feature not in FEATURES:
            # ⚠️ A RAIL name lands here, and that is the point. `--feature
            # cost_to_risk` is the easy typo - a real name in the wrong arm -
            # and without this it would narrow nothing, run two identical
            # baselines and report no difference, which reads as "the feature
            # costs nothing".
            hint = (
                " - that is a RAIL, not a regime feature; use --rail for it"
                if feature in RAILS or feature == REGIME_RAIL
                else ""
            )
            raise UnablatableFeature(
                f"{feature!r} is not an ablatable regime feature{hint}. "
                f"Known features: {', '.join(sorted(FEATURES))}."
            )
    removed = set(disabled)
    kept = tuple(f for f in base.regime_features if f not in removed)
    return Settings.model_validate({**base.model_dump(), "regime_features": kept})


class UnablatableRail(ValueError):
    """A rail this module cannot neutralise.

    Raised rather than ignored. Silently running a baseline twice and reporting
    no difference is indistinguishable from a rail that costs nothing, and that
    confusion is the failure this design is shaped to prevent.
    """


def ablated_settings(base: Settings, disabled: Sequence[str]) -> Settings:
    """`base` with every named rail's knob set beyond reach.

    Re-validated rather than copied. `model_copy(update=...)` writes fields
    without running their validators, so a neutral value outside a field's
    bounds would be accepted here and only fail somewhere far away - or worse,
    not fail at all and quietly not neutralise.
    """
    overrides: dict[str, object] = {}
    for rail in disabled:
        if rail in _TWO_CONSUMERS:
            raise UnablatableRail(_TWO_CONSUMERS[rail])
        if rail == REGIME_RAIL:
            continue
        if rail not in RAILS:
            raise UnablatableRail(
                f"{rail!r} is not ablatable - no known Settings knob neutralises it. "
                f"Known rails: {', '.join(sorted(RAILS))}, {REGIME_RAIL}."
            )
        overrides.update(RAILS[rail])
    if not overrides:
        return base
    return Settings.model_validate({**base.model_dump(), **overrides})
