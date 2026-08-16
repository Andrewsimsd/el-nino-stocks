"""Out-of-sample ENSO predictive screening with multiple-test correction."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import t as student_t


def _hac_regression(y: np.ndarray, x: np.ndarray, minimum_lags: int = 1) -> dict[str, float]:
    design = np.column_stack([np.ones(len(x)), x])
    inverse_xx = np.linalg.pinv(design.T @ design)
    beta = inverse_xx @ design.T @ y
    residuals = y - design @ beta
    lags = max(minimum_lags, int(np.floor(4 * (len(y) / 100) ** (2 / 9))))
    scores = design * residuals[:, None]
    meat = scores.T @ scores
    for lag in range(1, min(lags, len(y) - 1) + 1):
        weight = 1 - lag / (lags + 1)
        cross = scores[lag:].T @ scores[:-lag]
        meat += weight * (cross + cross.T)
    covariance = inverse_xx @ meat @ inverse_xx
    slope_se = float(np.sqrt(max(covariance[1, 1], 0)))
    statistic = float(beta[1] / slope_se) if slope_se > 0 else np.nan
    p_value = float(2 * student_t.sf(abs(statistic), df=max(1, len(y) - 2))) if np.isfinite(statistic) else np.nan
    return {
        "intercept": float(beta[0]), "slope": float(beta[1]),
        "slope_se": slope_se, "t_statistic": statistic,
        "p_value": p_value, "hac_lags": lags,
        "residual_volatility": float(np.std(residuals, ddof=2)),
    }


def _walk_forward(
    y: np.ndarray, x: np.ndarray, horizon: int, minimum_train: int = 60
) -> tuple[float, float, int]:
    predictions, baselines, actuals = [], [], []
    # Purge overlapping labels: at predictor date ``position``, a training
    # target is usable only if its forward-return window has already ended.
    for position in range(minimum_train + horizon - 1, len(y)):
        train_end = position - horizon + 1
        train_x, train_y = x[:train_end], y[:train_end]
        design = np.column_stack([np.ones(train_end), train_x])
        beta = np.linalg.pinv(design.T @ design) @ design.T @ train_y
        predictions.append(float(beta[0] + beta[1] * x[position]))
        baselines.append(float(np.mean(train_y)))
        actuals.append(float(y[position]))
    if not actuals:
        return np.nan, np.nan, 0
    actual = np.asarray(actuals)
    predicted = np.asarray(predictions)
    baseline = np.asarray(baselines)
    denominator = float(np.sum((actual - baseline) ** 2))
    oos_r2 = 1 - float(np.sum((actual - predicted) ** 2)) / denominator if denominator > 0 else np.nan
    directional_accuracy = float(np.mean(np.sign(predicted) == np.sign(actual)))
    return oos_r2, directional_accuracy, len(actual)


def _event_consistency(dates: pd.DatetimeIndex, y: np.ndarray, x: np.ndarray, slope: float) -> tuple[int, float]:
    warm = pd.Series(x >= 0.5, index=dates)
    groups = (warm != warm.shift(fill_value=False)).cumsum()
    event_means = [
        float(np.mean(y[warm.to_numpy() & (groups.to_numpy() == group)]))
        for group in groups[warm].unique()
    ]
    event_means = [value for value in event_means if np.isfinite(value)]
    if not event_means or slope == 0:
        return len(event_means), np.nan
    consistency = float(np.mean(np.sign(event_means) == np.sign(slope)))
    return len(event_means), consistency


def _bh_adjust(p_values: pd.Series) -> pd.Series:
    ordered = p_values.sort_values()
    adjusted = ordered * len(ordered) / np.arange(1, len(ordered) + 1)
    adjusted = adjusted.iloc[::-1].cummin().iloc[::-1].clip(upper=1)
    return adjusted.reindex(p_values.index)


def calculate_predictive_screen(
    prices_df: pd.DataFrame,
    roni_df: pd.DataFrame,
    horizons: tuple[int, ...] = (1, 3, 6),
    min_observations: int = 60,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return one selected horizon per security and every tested stock-horizon row."""
    prices = prices_df.set_index("Date").sort_index().resample("MS").last()
    returns = prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    # A robust, investable-universe market proxy avoids requiring a separate
    # benchmark and works for both US and supplemental international listings.
    market_return = returns.median(axis=1, skipna=True)
    signal = roni_df["oni"].rename("roni")
    latest_signal = float(signal.dropna().iloc[-1])
    records: list[dict[str, object]] = []

    for horizon in horizons:
        asset_forward = (1 + returns).rolling(horizon).apply(np.prod, raw=True).shift(-horizon) - 1
        market_forward = (1 + market_return).rolling(horizon).apply(np.prod, raw=True).shift(-horizon) - 1
        abnormal = asset_forward.sub(market_forward, axis=0)
        aligned = abnormal.join(signal, how="inner")
        for ticker in abnormal.columns:
            pair = aligned[[ticker, "roni"]].dropna()
            if len(pair) < min_observations or pair[ticker].nunique() < 2:
                continue
            y = pair[ticker].to_numpy(dtype=float)
            x = pair["roni"].to_numpy(dtype=float)
            fit = _hac_regression(y, x, minimum_lags=max(1, horizon - 1))
            if not np.isfinite(fit["p_value"]):
                continue
            oos_r2, direction, oos_n = _walk_forward(
                y, x, horizon=horizon, minimum_train=min_observations
            )
            event_count, event_consistency = _event_consistency(pair.index, y, x, fit["slope"])
            expected_return = fit["slope"] * max(0.0, latest_signal)
            effect_to_risk = abs(expected_return) / fit["residual_volatility"] if fit["residual_volatility"] > 0 else 0.0
            validation_weight = np.sqrt(max(0.0, oos_r2)) if np.isfinite(oos_r2) else 0.0
            stability_weight = event_consistency if np.isfinite(event_consistency) else 0.0
            records.append({
                "ticker": ticker, "horizon_months": horizon,
                "observations": len(pair), "correlation": float(pair[ticker].corr(pair["roni"])),
                **fit, "expected_abnormal_return": expected_return,
                "oos_r2": oos_r2, "directional_accuracy": direction,
                "oos_predictions": oos_n, "el_nino_events": event_count,
                "event_sign_consistency": event_consistency,
                "selection_score": effect_to_risk * validation_weight * stability_weight,
            })

    tests = pd.DataFrame(records)
    if tests.empty:
        raise RuntimeError("No securities have enough data for predictive testing")
    tests["q_value"] = _bh_adjust(tests["p_value"])
    tests["significant"] = tests["q_value"] < 0.05
    tests["passes_validation"] = (
        (tests["oos_r2"] > 0)
        & (tests["el_nino_events"] >= 3)
        & (tests["event_sign_consistency"] >= 2 / 3)
    )
    chosen = (
        tests.sort_values(
            ["ticker", "passes_validation", "selection_score", "q_value"],
            ascending=[True, False, False, True],
        )
        .drop_duplicates("ticker", keep="first")
        .copy()
    )
    return chosen, tests
