"""Gaussian HMM core (spec §E, paper §11.1): fits n latent states on the
stationary feature matrix and characterizes each by its mean return/vol
signature so the fusion layer (fusion.py) can map unlabeled HMM states onto
the paper's seven named regimes - the HMM itself has no concept of "Bull" or
"Recession", only statistically distinct states ("one state producing high
mean and low variance ('low-vol bull'), another negative mean and high
variance ('high-vol bear')" - paper §11.1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from hmmlearn.hmm import GaussianHMM

_LOG_RETURN_COL = 0
_REALIZED_VOL_COL = 1

_HMMLEARN_LOGGER_NAME = "hmmlearn.base"


class _NonMonotonicFilter(logging.Filter):
    """Counts hmmlearn's own "Model is not converging" warnings.

    Counting the LIBRARY'S OWN WARNING rather than re-deriving the condition
    from `monitor_`: the decrease it reports happens BETWEEN iterations, and
    `ConvergenceMonitor.history` is a two-element window by the time `fit`
    returns, so the intermediate steps are gone. The warning is the only
    place the fact survives.
    """

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage().startswith("Model is not converging"):
            self.count += 1
        return True  # count it, never suppress it


@dataclass(frozen=True, slots=True)
class StateSignature:
    mean_return: float
    mean_vol: float


class HMMRegimeModel:
    def __init__(self, n_states: int = 4, random_state: int = 0, n_iter: int = 100) -> None:
        self.n_states = n_states
        self.random_state = random_state
        self.n_iter = n_iter
        self._model: GaussianHMM | None = None
        self._state_signatures: dict[int, StateSignature] | None = None
        # 0, not unset: "no fit has logged the warning" is a legitimate
        # reading of "no fit has happened yet", and this is an observability
        # accessor - reading it early must never raise the way
        # `state_signatures` does.
        self._decreasing_loglik_warnings = 0

    def fit(self, feature_matrix: np.ndarray) -> None:
        if feature_matrix.shape[0] < self.n_states * 2:
            raise ValueError(
                f"Need at least {self.n_states * 2} rows to fit a {self.n_states}-state HMM, "
                f"got {feature_matrix.shape[0]}"
            )
        model = GaussianHMM(
            n_components=self.n_states,
            covariance_type="diag",
            random_state=self.random_state,
            n_iter=self.n_iter,
        )
        hmmlearn_logger = logging.getLogger(_HMMLEARN_LOGGER_NAME)
        warning_filter = _NonMonotonicFilter()
        hmmlearn_logger.addFilter(warning_filter)
        try:
            model.fit(feature_matrix)
        finally:
            hmmlearn_logger.removeFilter(warning_filter)
        # Assigned immediately after `model.fit`, before `_characterize_states`
        # below: that call reads `self._model`, so it must already be set for
        # it to run at all, but if it raises after that, the observability
        # counter must not be left describing the PREVIOUS fit while
        # `is_fitted` already reports the new one.
        self._decreasing_loglik_warnings = warning_filter.count
        self._model = model
        self._state_signatures = self._characterize_states(feature_matrix)

    def predict_proba(self, feature_matrix: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("fit() must be called before predict_proba()")
        result: np.ndarray = self._model.predict_proba(feature_matrix)
        return result

    @property
    def state_signatures(self) -> dict[int, StateSignature]:
        if self._state_signatures is None:
            raise RuntimeError("fit() must be called before state_signatures is available")
        return self._state_signatures

    @property
    def is_fitted(self) -> bool:
        return self._model is not None

    @property
    def decreasing_loglik_warnings(self) -> int:
        """How many times the most recent `fit()` logged hmmlearn's own
        "Model is not converging" warning - the EM log-likelihood decreased
        between two iterations of that fit.

        This is NOT derived from `monitor_.converged`. hmmlearn counts
        exhausting `n_iter` as converged - `ConvergenceMonitor.converged` is
        `self.iter == self.n_iter or (...)`, so that flag cannot distinguish
        a clean stop from simply running out of iterations, and a counter
        built on it can never reliably fire. Counting the warning instead
        measures a real, narrower fact - the log-likelihood went backward -
        that `converged` never reports either way.

        `hmmlearn` still returns a usable model when this is nonzero, and the
        fit is used exactly as any other. This exists so a caller can RECORD
        that, not so it can decide anything differently.

        Safe to read before any fit: 0, same as `is_fitted` being False.
        """
        return self._decreasing_loglik_warnings

    def _characterize_states(self, feature_matrix: np.ndarray) -> dict[int, StateSignature]:
        model = self._model
        if model is None:
            raise RuntimeError("fit() must set self._model before characterizing states")
        states = model.predict(feature_matrix)
        signatures: dict[int, StateSignature] = {}
        for state in range(self.n_states):
            mask = states == state
            if not mask.any():
                # Genuinely undefined, not zero: this state was never assigned
                # any observations (a legitimate outcome when the data doesn't
                # support n_states distinct regimes). NaN lets score_from_hmm
                # (fusion.py) exclude it from the z-score population instead
                # of treating a fabricated "0.0" as a real data point.
                signatures[state] = StateSignature(mean_return=float("nan"), mean_vol=float("nan"))
                continue
            signatures[state] = StateSignature(
                mean_return=float(feature_matrix[mask, _LOG_RETURN_COL].mean()),
                mean_vol=float(feature_matrix[mask, _REALIZED_VOL_COL].mean()),
            )
        return signatures
