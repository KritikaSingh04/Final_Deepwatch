"""AI second-opinion anomaly scorer (advisory layer).

An unsupervised model (IsolationForest when scikit-learn is available,
with a dependency-free robust-z fallback) is trained ONCE on the current
dataset's own stable baseline window and then FROZEN — no retraining, no
cross-dataset learning. It corroborates the deterministic pressure-
transient detector, which remains the primary safety signal.

Output is a CALIBRATED anomaly percentile: the current window's score is
ranked against the frozen training distribution using the plotting
position rank/(N+1), so the display can never claim an arbitrary
"100/100" — the ceiling is N/(N+1) of the training population.

Features per rolling window, per sensor, all scale-free (normalised by
that sensor's learned baseline): short-term slope, short-term
variability, and deviation below baseline.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from typing import Optional

try:
    from sklearn.ensemble import IsolationForest
    _HAVE_SKLEARN = True
except Exception:  # pragma: no cover
    _HAVE_SKLEARN = False


def _median(vals):
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else 0.5 * (s[mid - 1] + s[mid])


class OnlineAnomalyScorer:
    WINDOW = 8            # samples per feature window
    MIN_TRAIN = 15        # minimum windows required to fit at all
    TARGET_TRAIN = 300    # stop collecting and freeze once reached

    def __init__(self):
        self._buf_in: deque = deque(maxlen=self.WINDOW)
        self._buf_out: deque = deque(maxlen=self.WINDOW)
        self._train: list[list[float]] = []
        self._model = None
        self._train_scores: list[float] = []   # sorted, frozen at fit time
        self._smooth: Optional[float] = None   # EWMA of the percentile
        self.trained = False
        self.frozen = False

    def update(self, t: float, p_in: float, p_out: float,
               base_in: float, base_out: float,
               training_allowed: bool) -> Optional[dict]:
        """Returns {"pct": anomaly percentile, "n_train": N, ...} once
        trained; None while still collecting normal windows; and
        {"unavailable": True} when training was impossible (too few
        stable samples before the event) — the failure-safe marker the
        UI turns into "AI corroboration unavailable — deterministic
        detector active."""
        self._buf_in.append(p_in)
        self._buf_out.append(p_out)
        if len(self._buf_in) < self.WINDOW or base_in <= 0 or base_out <= 0:
            return self._status_when_unscored()

        feats = (self._features(self._buf_in, base_in)
                 + self._features(self._buf_out, base_out))

        if not self.frozen:
            if training_allowed:
                self._train.append(feats)
                if len(self._train) >= self.TARGET_TRAIN:
                    self._fit()          # enough normal data — freeze now
            else:
                # stable window over (anomaly began): fit on what we have
                if len(self._train) >= self.MIN_TRAIN:
                    self._fit()
                else:
                    self.frozen = True   # insufficient data — stay untrained

        if not self.trained:
            return self._status_when_unscored()
        d = self._decision(feats)
        # anomaly percentile vs the frozen training distribution, using
        # the plotting position rank/(N+1) — bounded away from 0 and 100
        # by construction. _train_scores is sorted ascending and a HIGHER
        # decision value means MORE NORMAL, so `rank` counts training
        # windows strictly more normal than the current one.
        n = len(self._train_scores)
        rank = n - bisect_right(self._train_scores, d)
        pct = 100.0 * rank / (n + 1)
        # a window drawn from the normal population has a uniform
        # percentile, so smooth lightly for display: normal ops hover
        # mid-scale while genuine anomalies pin above the p95 line
        self._smooth = pct if self._smooth is None \
            else 0.7 * self._smooth + 0.3 * pct
        # the calibrated ceiling: "more anomalous than every training
        # window" can never exceed N/(N+1) — report it so the display can
        # scale its alert judgement to what this dataset supports
        ceiling = 100.0 * n / (n + 1)
        return {"pct": round(self._smooth, 1), "raw_pct": round(pct, 1),
                "n_train": n, "ceiling": round(ceiling, 1)}

    # ------------------------------------------------------------------
    def _status_when_unscored(self) -> Optional[dict]:
        """None while still legitimately collecting; the unavailable
        marker once frozen without a model."""
        if self.frozen and not self.trained:
            return {"unavailable": True}
        return None

    @staticmethod
    def _slope(vals) -> float:
        n = len(vals)
        if n < 2:
            return 0.0
        mean = sum(vals) / n
        xbar = (n - 1) / 2
        num = sum((x - xbar) * (v - mean) for x, v in enumerate(vals))
        den = sum((x - xbar) ** 2 for x in range(n))
        return num / den if den else 0.0

    @classmethod
    def _features(cls, buf, baseline) -> list[float]:
        """Per sensor, all normalised by that sensor's learned baseline:
        pressure slope, short-window variance, drop ratio (deviation
        below baseline), and acceleration (change of slope between the
        two half-windows)."""
        vals = list(buf)
        n = len(vals)
        mean = sum(vals) / n
        slope = cls._slope(vals)
        var = sum((v - mean) ** 2 for v in vals) / n
        half = n // 2
        accel = cls._slope(vals[half:]) - cls._slope(vals[:half])
        return [
            slope / baseline,
            (var ** 0.5) / baseline,
            (baseline - mean) / baseline,
            accel / baseline,
        ]

    def _fit(self):
        if _HAVE_SKLEARN:
            self._model = IsolationForest(
                n_estimators=100, random_state=7, contamination="auto")
            self._model.fit(self._train)
        else:
            self._model = _RobustZ(self._train)
        self._train_scores = sorted(self._decision(f) for f in self._train)
        self.trained = True
        self.frozen = True

    def _decision(self, feats) -> float:
        if _HAVE_SKLEARN and isinstance(self._model, IsolationForest):
            return float(self._model.decision_function([feats])[0])
        return self._model.decision(feats)


class _RobustZ:
    """Dependency-free fallback: diagonal robust-z distance model."""

    def __init__(self, train):
        dims = len(train[0])
        self.med = []
        self.sig = []
        for d in range(dims):
            col = [row[d] for row in train]
            m = _median(col)
            mad = _median([abs(v - m) for v in col])
            self.med.append(m)
            self.sig.append(max(1.4826 * mad, 1e-9))

    def decision(self, feats) -> float:
        # negative max-z so that "higher = more normal", like IsolationForest
        z = max(abs(f - m) / s for f, m, s in zip(feats, self.med, self.sig))
        return -z
