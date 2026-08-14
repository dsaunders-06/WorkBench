"""Gaussian HMM core (spec §E, paper §11.1): fits n latent states on the
stationary feature matrix and characterizes each by its mean return/vol
signature so the fusion layer (fusion.py) can map unlabeled HMM states onto
the paper's seven named regimes - the HMM itself has no concept of "Bull" or
"Recession", only statistically distinct states ("one state producing high
mean and low variance ('low-vol bull'), another negative mean and high
variance ('high-vol bear')" - paper §11.1).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from hmmlearn.hmm import GaussianHMM

_LOG_RETURN_COL = 0
_REALIZED_VOL_COL = 1


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
        # False, not unset: "no fit has converged" is a legitimate reading of
        # "no fit has happened yet", and this is an observability accessor -
        # reading it early must never raise the way `state_signatures` does.
        self._converged = False

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
        model.fit(feature_matrix)
        self._model = model
        self._state_signatures = self._characterize_states(feature_matrix)
        self._converged = bool(model.monitor_.converged)

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
    def converged(self) -> bool:
        """Whether the most recent `fit()` converged inside `n_iter`.

        `hmmlearn` still returns a usable model when this is False - EM
        stopped at the iteration cap rather than at a fixed point - and the
        fit is used exactly as any other. This exists so a caller can RECORD
        that, not so it can decide anything differently.
        """
        return self._converged

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
