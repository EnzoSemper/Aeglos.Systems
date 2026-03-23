"""
AEGLOS Analytics Pro — Prophet-Compatible Threat Forecaster

Implements the core Prophet algorithm (piecewise linear trend + Fourier
seasonality + uncertainty via residual bootstrap) using only numpy/scipy.
No CmdStan/Stan required — fully bundleable with PyInstaller.

References: Taylor & Letham (2018) "Forecasting at Scale"
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.stats import pearsonr

logger = logging.getLogger("prophet_engine")

SEV_WEIGHT = {"critical": 4.0, "high": 3.0, "moderate": 2.0, "low": 1.0}
MIN_POINTS_FOR_FIT = 6          # min hourly buckets needed to fit
MIN_POINTS_FOR_SEASONALITY = 24 # min points before daily seasonality is meaningful
MIN_POINTS_FOR_WEEKLY = 120     # min points before weekly seasonality is meaningful


# ── Core forecaster ───────────────────────────────────────────────────────────

class ProphetEngine:
    """
    Lightweight Prophet-compatible forecaster.
    Piecewise linear trend + Fourier seasonality, fitted via L-BFGS-B MAP.
    """

    def __init__(
        self,
        n_changepoints: int = 20,
        changepoint_prior: float = 0.05,
        seasonality_prior: float = 10.0,
        daily_fourier: int = 6,
        weekly_fourier: int = 3,
        uncertainty_samples: int = 300,
        interval_width: float = 0.80,
    ):
        self.n_changepoints = n_changepoints
        self.changepoint_prior = changepoint_prior
        self.seasonality_prior = seasonality_prior
        self.daily_fourier = daily_fourier
        self.weekly_fourier = weekly_fourier
        self.uncertainty_samples = uncertainty_samples
        self.interval_width = interval_width

        self._fitted = False
        self._params: np.ndarray | None = None
        self._t0 = 0.0
        self._t_scale = 1.0
        self._y_scale = 1.0
        self._changepoints: np.ndarray | None = None
        self._n_cp = 0
        self._n_seas = 0
        self._use_daily = False
        self._use_weekly = False
        self._residuals: np.ndarray | None = None

    # ── Feature builders ─────────────────────────────────────────────────────

    def _seas_features(self, t: np.ndarray) -> np.ndarray:
        """Fourier seasonality design matrix."""
        cols: list[np.ndarray] = []
        if self._use_daily:
            for n in range(1, self.daily_fourier + 1):
                cols += [np.cos(2 * math.pi * n * t),
                         np.sin(2 * math.pi * n * t)]
        if self._use_weekly:
            for n in range(1, self.weekly_fourier + 1):
                cols += [np.cos(2 * math.pi * n * t / 7),
                         np.sin(2 * math.pi * n * t / 7)]
        return np.column_stack(cols) if cols else np.zeros((len(t), 0))

    def _changepoint_matrix(self, t: np.ndarray) -> np.ndarray:
        A = np.zeros((len(t), self._n_cp))
        for j, cp in enumerate(self._changepoints):  # type: ignore[union-attr]
            A[:, j] = (t >= cp).astype(float)
        return A

    def _trend(self, t: np.ndarray, k: float, m: float, delta: np.ndarray) -> np.ndarray:
        A = self._changepoint_matrix(t)
        gamma = -self._changepoints * delta  # type: ignore[operator]
        return (k + A @ delta) * t + (m + A @ gamma)

    # ── Fit ──────────────────────────────────────────────────────────────────

    def fit(self, t_unix: np.ndarray, y: np.ndarray) -> bool:
        """
        Fit model.  t_unix: array of Unix timestamps (seconds).
                    y:      observed values (event severity score per hour).
        Returns True on success.
        """
        n = len(t_unix)
        if n < MIN_POINTS_FOR_FIT:
            return False

        self._t0 = float(t_unix.min())
        self._t_scale = max(float(t_unix.max() - t_unix.min()), 3600.0)
        self._y_scale = max(float(y.max()), 1e-6)

        t = (t_unix - self._t0) / self._t_scale
        y_n = y / self._y_scale

        # Seasonal flags
        self._use_daily  = n >= MIN_POINTS_FOR_SEASONALITY
        self._use_weekly = n >= MIN_POINTS_FOR_WEEKLY

        # Changepoints in first 80% of history
        n_cp = min(self.n_changepoints, max(1, n // 5))
        hist_end = t[int(0.8 * n)]
        self._changepoints = np.linspace(t[0] + 1e-9, hist_end, n_cp + 2)[1:-1]
        self._n_cp = len(self._changepoints)

        S = self._seas_features(t)
        self._n_seas = S.shape[1]
        # param layout: [k, m, delta × n_cp, beta × n_seas]
        n_params = 2 + self._n_cp + self._n_seas

        def loss(p: np.ndarray) -> float:
            k, m = p[0], p[1]
            delta = p[2:2 + self._n_cp]
            beta = p[2 + self._n_cp:]
            yhat = self._trend(t, k, m, delta)
            if self._n_seas:
                yhat = yhat + S @ beta
            resid = y_n - yhat
            mse = float(np.mean(resid ** 2))
            reg = self.changepoint_prior * float(np.sum(np.abs(delta)))
            if self._n_seas:
                reg += float(np.sum(beta ** 2)) / (self.seasonality_prior ** 2)
            return mse + reg

        x0 = np.zeros(n_params)
        # Initialise trend slope from data
        if n > 1:
            x0[0] = float(np.mean(np.diff(y_n) / np.diff(t)))
        x0[1] = float(y_n[0])

        try:
            res = minimize(loss, x0, method="L-BFGS-B",
                           options={"maxiter": 2000, "ftol": 1e-10})
            self._params = res.x
            # Compute residuals for uncertainty bootstrap
            k, m = self._params[0], self._params[1]
            delta = self._params[2:2 + self._n_cp]
            beta = self._params[2 + self._n_cp:]
            yhat = self._trend(t, k, m, delta)
            if self._n_seas:
                yhat = yhat + S @ beta
            self._residuals = y_n - yhat
            self._fitted = True
            return True
        except Exception as exc:
            logger.warning("ProphetEngine fit error: %s", exc)
            return False

    # ── Predict ──────────────────────────────────────────────────────────────

    def predict(self, t_unix_future: np.ndarray) -> list[dict]:
        """
        Predict for future timestamps.
        Returns list of dicts with yhat, yhat_lower, yhat_upper, trend, seasonal.
        """
        if not self._fitted or self._params is None:
            return []

        t = (t_unix_future - self._t0) / self._t_scale
        k, m = self._params[0], self._params[1]
        delta = self._params[2:2 + self._n_cp]
        beta = self._params[2 + self._n_cp:]

        trend_n = self._trend(t, k, m, delta)
        S = self._seas_features(t)
        seas_n = S @ beta if self._n_seas else np.zeros(len(t))
        yhat_n = trend_n + seas_n

        # Bootstrap uncertainty from residuals
        if (self._residuals is not None and len(self._residuals) > 1
                and self.uncertainty_samples > 0):
            rng = np.random.default_rng(42)
            noise = rng.choice(self._residuals,
                               size=(self.uncertainty_samples, len(t)), replace=True)
            sims = yhat_n[np.newaxis, :] + noise
            alpha = (1.0 - self.interval_width) / 2.0
            lower_n = np.quantile(sims, alpha, axis=0)
            upper_n = np.quantile(sims, 1 - alpha, axis=0)
        else:
            lower_n = upper_n = yhat_n

        sc = self._y_scale
        results = []
        for i in range(len(t_unix_future)):
            results.append({
                "t": float(t_unix_future[i]),
                "yhat":        max(0.0, float(yhat_n[i] * sc)),
                "yhat_lower":  max(0.0, float(lower_n[i] * sc)),
                "yhat_upper":  max(0.0, float(upper_n[i] * sc)),
                "trend":       float(trend_n[i] * sc),
                "seasonal":    float(seas_n[i] * sc),
            })
        return results

    # ── Decompose ─────────────────────────────────────────────────────────────

    def decompose(self) -> dict:
        """Extract trend/changepoint summary for pattern display."""
        if not self._fitted or self._params is None:
            return {}
        delta = self._params[2:2 + self._n_cp]
        k = float(self._params[0])
        # Effective slope at end of history = k + sum(delta), per hour
        slope_normalised = k + float(np.sum(delta))
        slope_per_hour = slope_normalised * self._y_scale / (self._t_scale / 3600.0)
        sig = np.where(np.abs(delta) > 0.01 * np.max(np.abs(delta) + 1e-9))[0]
        residual_std = float(np.std(self._residuals) * self._y_scale) if self._residuals is not None else 0.0
        return {
            "trend_slope_per_hour": round(slope_per_hour, 4),
            "trend_direction":      ("increasing" if slope_per_hour > 0.05
                                     else "decreasing" if slope_per_hour < -0.05
                                     else "stable"),
            "n_significant_changepoints": int(len(sig)),
            "residual_std": round(residual_std, 4),
            "uses_daily_seasonality":  self._use_daily,
            "uses_weekly_seasonality": self._use_weekly,
        }


# ── Time-series builder ───────────────────────────────────────────────────────

def events_to_hourly(
    events: list[Any],
    region: str | None = None,
    hours_back: int = 168,          # 1 week max history
) -> tuple[np.ndarray, np.ndarray]:
    """
    Aggregate events into hourly buckets (severity-weighted score).
    Returns (t_unix array, y_score array) covering up to hours_back.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours_back)

    hourly: dict[int, float] = {}  # bucket_hour_unix -> cumulative score

    for ev in events:
        try:
            ts = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
        except Exception:
            continue
        if ts < cutoff:
            continue
        if region and ev.region != region:
            continue
        bucket = int(ts.timestamp()) // 3600 * 3600
        hourly[bucket] = hourly.get(bucket, 0.0) + SEV_WEIGHT.get(ev.severity, 1.0)

    if not hourly:
        return np.array([]), np.array([])

    # Fill in zero-score hours between first and now
    t_min = min(hourly.keys())
    t_max = int(now.timestamp()) // 3600 * 3600
    buckets = list(range(t_min, t_max + 3600, 3600))
    t_arr = np.array(buckets, dtype=float)
    y_arr = np.array([hourly.get(b, 0.0) for b in buckets], dtype=float)
    return t_arr, y_arr


# ── Correlation engine ────────────────────────────────────────────────────────

def compute_correlation_matrix(
    events: list[Any],
    min_events_per_region: int = 3,
) -> dict:
    """
    Compute Pearson correlation matrix across regions using aligned hourly
    severity-score time series (not hour-of-day buckets — actual time series).
    """
    # Gather per-region hourly series
    regions: dict[str, dict[int, float]] = {}
    for ev in events:
        r = ev.region
        if r == "Global":
            continue
        try:
            ts = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
        except Exception:
            continue
        bucket = int(ts.timestamp()) // 3600 * 3600
        regions.setdefault(r, {})
        regions[r][bucket] = regions[r].get(bucket, 0.0) + SEV_WEIGHT.get(ev.severity, 1.0)

    # Filter regions with enough events
    regions = {r: v for r, v in regions.items() if sum(v.values()) >= min_events_per_region}
    if len(regions) < 2:
        return {"regions": [], "correlation_matrix": [], "source_heatmap": [], "note": "insufficient_data"}

    # Build aligned time axis
    all_buckets = sorted(set(b for v in regions.values() for b in v))
    if len(all_buckets) < 4:
        return {"regions": [], "correlation_matrix": [], "source_heatmap": [], "note": "insufficient_data"}

    region_names = sorted(regions.keys())
    vectors = {
        r: np.array([regions[r].get(b, 0.0) for b in all_buckets])
        for r in region_names
    }

    # Pearson correlation matrix
    n = len(region_names)
    matrix_rows = []
    for i, ri in enumerate(region_names):
        row_vals = []
        for j, rj in enumerate(region_names):
            if i == j:
                row_vals.append(1.0)
            else:
                vi, vj = vectors[ri], vectors[rj]
                if np.std(vi) < 1e-9 or np.std(vj) < 1e-9:
                    row_vals.append(0.0)
                else:
                    try:
                        r_val, _ = pearsonr(vi, vj)
                        row_vals.append(round(float(r_val), 3) if not math.isnan(r_val) else 0.0)
                    except Exception:
                        row_vals.append(0.0)
        matrix_rows.append({"region": ri, "values": row_vals})

    # Source × Region heatmap
    source_region: dict[str, dict[str, int]] = {}
    for ev in events:
        if ev.region == "Global":
            continue
        src = ev.source
        source_region.setdefault(src, {})
        source_region[src][ev.region] = source_region[src].get(ev.region, 0) + 1

    top_sources = sorted(source_region.keys(),
                         key=lambda s: sum(source_region[s].values()),
                         reverse=True)
    heatmap = [{"source": s, "regions": source_region[s]} for s in top_sources]

    return {
        "regions": region_names,
        "correlation_matrix": matrix_rows,
        "source_heatmap": heatmap,
        "n_timepoints": len(all_buckets),
        "note": "ok",
    }


# ── Forecast engine ───────────────────────────────────────────────────────────

def compute_forecast(
    events: list[Any],
    horizon_hours: int = 72,
) -> dict:
    """
    Fit ProphetEngine on global hourly series and per-region, return
    72-hour forecast with trend/uncertainty/regional risk.
    """
    now = datetime.now(timezone.utc)

    # ── Global forecast ──────────────────────────────────────────────────────
    t_arr, y_arr = events_to_hourly(events)
    forecast_points: list[dict] = []
    model_meta: dict = {}

    if len(t_arr) >= MIN_POINTS_FOR_FIT:
        eng = ProphetEngine(uncertainty_samples=300)
        fitted = eng.fit(t_arr, y_arr)
        if fitted:
            # Normalise y to [0,1] threat level for display
            y_max = max(float(y_arr.max()), 1.0)
            t_future = np.array([
                now.timestamp() + i * 3600
                for i in range(horizon_hours)
            ])
            preds = eng.predict(t_future)
            decomp = eng.decompose()
            model_meta = decomp

            for i, p in enumerate(preds):
                forecast_points.append({
                    "hour":       f"+{i}h",
                    "threat":     round(min(p["yhat"] / y_max, 1.0), 4),
                    "upper":      round(min(p["yhat_upper"] / y_max, 1.0), 4),
                    "lower":      round(max(p["yhat_lower"] / y_max, 0.0), 4),
                    "trend":      round(min(p["trend"] / y_max, 1.0), 4),
                    "seasonal":   round(p["seasonal"] / y_max, 4),
                    "confidence": round(max(0.03, math.exp(-0.008 * i) * 0.97), 4),
                })

    # Fallback if insufficient data
    if not forecast_points:
        decay = [{"hour": f"+{i}h", "threat": 0.0, "upper": 0.0, "lower": 0.0,
                  "trend": 0.0, "seasonal": 0.0,
                  "confidence": round(max(0.03, math.exp(-0.008 * i)), 4)}
                 for i in range(horizon_hours)]
        return {
            "points": decay,
            "region_risk": {},
            "model": {"status": "insufficient_data", "total_events_used": len(events)},
            "generated_at": now.isoformat(),
        }

    # ── Per-region risk scores ────────────────────────────────────────────────
    region_risk: dict[str, float] = {}
    region_names = {ev.region for ev in events if ev.region != "Global"}
    for region in region_names:
        t_r, y_r = events_to_hourly(events, region=region)
        if len(t_r) >= MIN_POINTS_FOR_FIT:
            eng_r = ProphetEngine(uncertainty_samples=0)
            if eng_r.fit(t_r, y_r):
                t_48h = np.array([now.timestamp() + i * 3600 for i in range(48)])
                preds_r = eng_r.predict(t_48h)
                if preds_r:
                    avg_threat = float(np.mean([p["yhat"] for p in preds_r]))
                    y_max_r = max(float(y_r.max()), 1.0)
                    region_risk[region] = round(min(avg_threat / y_max_r, 1.0), 3)
        # Fallback: use raw severity-weighted score
        if region not in region_risk:
            region_events = [e for e in events if e.region == region]
            if region_events:
                avg_w = sum(SEV_WEIGHT.get(e.severity, 1.0) for e in region_events) / len(region_events)
                region_risk[region] = round(min(avg_w / 4.0, 1.0), 3)

    return {
        "points": forecast_points,
        "region_risk": region_risk,
        "model": {
            "status": "fitted",
            "total_events_used": len(events),
            "total_hourly_buckets": int(len(t_arr)),
            **model_meta,
        },
        "generated_at": now.isoformat(),
    }


# ── Pattern engine ────────────────────────────────────────────────────────────

def compute_patterns(events: list[Any]) -> dict:
    """
    Use ProphetEngine decomposition + direct statistics for pattern analysis.
    """
    now = datetime.now(timezone.utc)
    t_arr, y_arr = events_to_hourly(events)

    hourly_count = [0] * 24
    day_count = [0] * 7
    sev_dist: dict[str, int] = {}

    for ev in events:
        try:
            ts = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
            hourly_count[ts.hour] += 1
            day_count[ts.weekday()] += 1
        except Exception:
            continue
        sev_dist[ev.severity] = sev_dist.get(ev.severity, 0) + 1

    # Fit for decomposition insights
    decomp: dict = {}
    if len(t_arr) >= MIN_POINTS_FOR_FIT:
        eng = ProphetEngine(uncertainty_samples=0)
        if eng.fit(t_arr, y_arr):
            decomp = eng.decompose()

    # Build detected patterns
    detected: list[dict] = []
    total = len(events)

    # 1. Trend direction from Prophet
    if decomp:
        direction = decomp.get("trend_direction", "stable")
        slope = decomp.get("trend_slope_per_hour", 0)
        n_cp = decomp.get("n_significant_changepoints", 0)
        conf = min(0.70 + 0.01 * len(t_arr), 0.97)
        if direction == "increasing":
            detected.append({
                "name": "Rising Threat Trend",
                "confidence": round(conf, 2),
                "desc": (f"Prophet model detects an increasing threat trend "
                         f"(+{abs(slope):.2f} severity/hr). "
                         f"{n_cp} significant regime change{'s' if n_cp != 1 else ''} detected.")
            })
        elif direction == "decreasing":
            detected.append({
                "name": "Declining Threat Trend",
                "confidence": round(conf, 2),
                "desc": (f"Threat activity is trending down "
                         f"(-{abs(slope):.2f} severity/hr). "
                         f"Conditions may be stabilising.")
            })
        else:
            detected.append({
                "name": "Stable Baseline Activity",
                "confidence": round(conf, 2),
                "desc": ("No significant trend detected. Activity is oscillating around "
                         "a stable baseline, consistent with routine reporting cycles.")
            })
        # Changepoint alert
        if n_cp >= 2:
            detected.append({
                "name": "Regime Shift Detected",
                "confidence": round(min(0.65 + 0.03 * n_cp, 0.95), 2),
                "desc": (f"Prophet identified {n_cp} significant activity-level shifts "
                         f"in the historical window. These may correspond to escalation "
                         f"events or new source ingestion.")
            })

    # 2. Diurnal peak
    if any(hourly_count):
        peak_h = hourly_count.index(max(hourly_count))
        trough_h = hourly_count.index(min(hourly_count))
        ratio = max(hourly_count) / max(min(hourly_count), 1)
        if ratio > 1.5:
            detected.append({
                "name": "Diurnal Activity Peak",
                "confidence": round(min(0.60 + 0.01 * total, 0.92), 2),
                "desc": (f"Event volume peaks at {peak_h:02d}:00 UTC "
                         f"({hourly_count[peak_h]} events) — "
                         f"{ratio:.1f}× the trough at {trough_h:02d}:00 UTC. "
                         f"{'Consistent with US/EU daytime reporting cycles.' if 12 <= peak_h <= 18 else 'Consistent with APAC/Middle East reporting cycles.' if 0 <= peak_h <= 8 else ''}")
            })

    # 3. Severity concentration
    critical_pct = round(100 * sev_dist.get("critical", 0) / max(total, 1))
    if critical_pct >= 15:
        detected.append({
            "name": "Elevated Critical Event Rate",
            "confidence": round(min(0.70 + 0.005 * sev_dist.get("critical", 0), 0.96), 2),
            "desc": (f"{critical_pct}% of events classified CRITICAL "
                     f"({sev_dist.get('critical', 0)} of {total}). "
                     f"Above the 15% baseline threshold — indicates heightened global threat environment.")
        })

    # 4. Regional concentration
    if events:
        region_counts: dict[str, int] = {}
        for ev in events:
            if ev.region != "Global":
                region_counts[ev.region] = region_counts.get(ev.region, 0) + 1
        if region_counts:
            top_r = max(region_counts, key=region_counts.__getitem__)
            top_pct = round(100 * region_counts[top_r] / max(total, 1))
            if top_pct >= 25:
                detected.append({
                    "name": "Regional Concentration",
                    "confidence": round(min(0.65 + 0.003 * region_counts[top_r], 0.93), 2),
                    "desc": (f"{top_r} accounts for {top_pct}% of all events "
                             f"({region_counts[top_r]} of {total}). "
                             f"Elevated collection density — may indicate emerging crisis or source bias.")
                })

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "hourly_count":       [{"hour": f"{h:02d}:00", "count": hourly_count[h]} for h in range(24)],
        "daily_count":        [{"day": days[d], "count": day_count[d]} for d in range(7)],
        "severity_distribution": sev_dist,
        "detected_patterns":  detected,
        "prophet_decomposition": decomp,
        "total_events_used":  total,
        "generated_at":       now.isoformat(),
    }
