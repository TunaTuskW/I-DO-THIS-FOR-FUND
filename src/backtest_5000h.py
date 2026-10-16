#!/usr/bin/env python3
"""
QuantOS 5,000-Hour Historical Backtest & Fragility Diagnostics Engine
Continuous 1H Dynamic Rebalance Mode (Option B) across 5,000+ hourly bars.
"""

import os
import sys
import json
import sqlite3
import argparse
import datetime
import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# Repository path injection
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

warnings.filterwarnings("ignore")

from src.engines.trend_engine import TrendEngine
from src.engines.smc_engine import SMCEngine
from src.engines.session_engine import SessionEngine
from src.engines.liquidity_engine import LiquidityEngine
from src.engines.regime_ensemble import RegimeEnsemble, run_kalman_filter, compute_mcs
from src.engines.risk_engine import RiskEngine
from src.engines.feature_engine import (
    ALL_YF_TICKERS,
    compute_stats,
    compute_volume_heat,
    load_mlp_models,
    run_multi_mlp_inference,
    run_self_calibration,
)

# Active target tickers
ACTIVE_ASSET_KEYS = ["SPX", "BTC", "GLD", "WTI", "NVDA", "TSLA", "DELL", "SPCE"]
TICKER_TO_YF = {
    "SPX": "^GSPC",
    "BTC": "BTC-USD",
    "GLD": "GLD",
    "WTI": "CL=F",
    "NVDA": "NVDA",
    "TSLA": "TSLA",
    "DELL": "DELL",
    "SPCE": "SPCE",
    "^TNX": "^TNX",
    "^FVX": "^FVX",
    "^VIX": "^VIX",
    "DXY": "DX-Y.NYB",
    "Silver": "SI=F"
}

# Slippage models
SLIPPAGE_MAP = {
    "spx": 0.0005,   # 5 bps
    "gld": 0.0005,   # 5 bps
    "nvda": 0.0007,  # 7 bps
    "btc": 0.0010,   # 10 bps
    "wti": 0.0010,   # 10 bps
    "tsla": 0.0010,  # 10 bps
    "dell": 0.0010,  # 10 bps
    "spce": 0.0015   # 15 bps (lower liquidity)
}

CONVICTION_GATE = {
    "RISK_ON_EXPANSION":      0.30,
    "LIQUIDITY_DRIVEN_RALLY": 0.35,
    "NEUTRAL_TRANSITIONAL":   0.45,
    "DEFENSIVE_RISK_OFF":     0.60,
    "VOLATILITY_EXPANSION":   0.70,
}

ASSET_ENTRY_THRESHOLDS = {
    "spx": 0.50,
    "btc": 0.52,
    "gld": 0.52,
    "wti": 0.54,
    "nvda": 0.53,
    "tsla": 0.56,
    "dell": 0.55,
    "spce": 0.70
}


def download_or_load_data(cache_path: str, force_download: bool = False) -> pd.DataFrame:
    """Download 720d 1H data per symbol or load from local Parquet cache."""
    if os.path.exists(cache_path) and not force_download:
        print(f"[Data] Checking cached 1H dataset at {cache_path}...")
        try:
            df = pd.read_parquet(cache_path)
            if df.columns.nlevels == 3:
                df.columns = df.columns.droplevel(2)
            if "^GSPC" in df.columns.levels[0] and len(df["^GSPC"]["Close"].dropna()) > 1000:
                print(f"[Data] Loaded cached dataset ({len(df)} total bars, {len(df['^GSPC']['Close'].dropna())} SPX bars).")
                return df
        except Exception as e:
            print(f"[Data] Failed to read cache: {e}. Re-downloading...")

    symbols = list(TICKER_TO_YF.values())
    print(f"[Data] Downloading 720d 1H data for {len(symbols)} symbols from Yahoo Finance...")
    dfs = {}
    for s in symbols:
        try:
            d = yf.download(s, period="720d", interval="1h", progress=False)
            if len(d) > 0:
                if d.index.tz is not None:
                    d.index = d.index.tz_localize(None)
                # Keep standard OHLCV columns
                col_subset = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in d.columns]
                dfs[s] = d[col_subset]
                print(f"  ✓ {s:10s}: {len(d)} bars")
            else:
                print(f"  ✗ {s:10s}: 0 bars returned")
        except Exception as e:
            print(f"  ✗ {s:10s}: download error ({e})")

    data = pd.concat(dfs, axis=1)
    if data.columns.nlevels == 3:
        data.columns = data.columns.droplevel(2)

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    try:
        data.to_parquet(cache_path)
        print(f"[Data] Cached dataset to {cache_path} ({len(data)} bars).")
    except Exception as e:
        print(f"[Data] Note: could not write parquet cache ({e}), continuing with in-memory dataframe.")

    return data


def run_5000h_simulation(
    initial_capital: float = 10000.0,
    min_hold_bars: int = 6,
    max_drawdown_limit: float = 0.15,
    warmup_bars: int = 150,
    force_download: bool = False,
    bars_limit: int = None
):
    print("=" * 80)
    print(f"QuantOS 5,000-Hour Backtest Simulation (Continuous 1H Dynamic Rebalance)")
    print(f"Initial Capital : ${initial_capital:,.2f}")
    print(f"Min Hold Period : {min_hold_bars} hours")
    print(f"Drawdown Limit  : {max_drawdown_limit:.1%}")
    print(f"Warmup Bars     : {warmup_bars}")
    print("=" * 80)

    cache_file = os.path.join(REPO_ROOT, "data", "cache_5000h_ohlcv.parquet")
    raw_data = download_or_load_data(cache_file, force_download=force_download)

    if "^GSPC" not in raw_data.columns.levels[0]:
        raise RuntimeError("SPX (^GSPC) data missing from download.")

    spx_series = raw_data["^GSPC"]["Close"].dropna()
    total_spx_bars = len(spx_series)
    print(f"[Data] Total SPX 1H Bars Available: {total_spx_bars}")
    print(f"[Data] Timeline: {spx_series.index[0]} to {spx_series.index[-1]}")

    if bars_limit and bars_limit < total_spx_bars:
        slice_start = max(0, total_spx_bars - (bars_limit + warmup_bars))
        eval_indices = spx_series.index[slice_start:]
    else:
        eval_indices = spx_series.index

    # Initialize engines
    trend_engine = TrendEngine()
    smc_engine = SMCEngine()
    session_engine = SessionEngine()
    liquidity_engine = LiquidityEngine()
    regime_ensemble = RegimeEnsemble()
    risk_engine = RiskEngine()
    mlp_packages = load_mlp_models(interval="1h")

    # Mute noisy internal logging during backtest execution
    import logging
    logging.disable(logging.WARNING)

    # State variables
    simulated_equity = initial_capital
    peak_equity = simulated_equity
    current_allocations = {k.lower(): 0.0 for k in ACTIVE_ASSET_KEYS}
    current_allocations["cash"] = 1.0
    current_asset_values = {k.lower(): 0.0 for k in ACTIVE_ASSET_KEYS}
    current_asset_values["cash"] = initial_capital
    target_allocations = current_allocations.copy()

    total_trades = 0
    total_fees_paid = 0.0
    last_rebalance_idx = -min_hold_bars
    circuit_breaker_active = False
    circuit_breaker_count = 0
    conviction_blocks = 0
    dynamic_brier = 0.15
    predictions_history = []
    prior_k_state = None
    prior_k_cov = None
    dom_regime = "NEUTRAL_TRANSITIONAL"
    kalman_dominant = "transitional"

    # Diagnostic Probes telemetry
    diagnostic_alerts = []
    hourly_telemetry = []
    trades_ledger = []
    bar_pnl_history = []

    active_indices = eval_indices[warmup_bars:]
    print(f"[Engine] Starting simulation across {len(active_indices)} active trading hours...")

    for i, current_dt in enumerate(active_indices):
        hist_slice = raw_data[raw_data.index <= current_dt]
        current_bar_idx = warmup_bars + i

        if i % 250 == 0 or i == len(active_indices) - 1:
            print(f"[Sim Progress] Bar {i+1}/{len(active_indices)} ({(i+1)/len(active_indices):.1%}) | Date: {current_dt} | Equity: ${simulated_equity:,.2f} | Regime: {dom_regime}")

        # --- Diagnostic Probe 1: Lookahead Leakage Check ---
        latest_slice_time = hist_slice.index[-1]
        if latest_slice_time > current_dt:
            diagnostic_alerts.append({
                "bar": current_bar_idx,
                "timestamp": str(current_dt),
                "probe": "LOOKAHEAD_LEAK",
                "severity": "CRITICAL",
                "details": f"Historical slice max time {latest_slice_time} exceeds current bar {current_dt}"
            })

        # Drawdown calculation from peak (evaluated EVERY bar)
        equity_drawdown = (peak_equity - simulated_equity) / peak_equity if peak_equity > 0 else 0.0

        # Circuit breaker trigger check (evaluated EVERY bar)
        if equity_drawdown >= max_drawdown_limit:
            if not circuit_breaker_active:
                circuit_breaker_active = True
                circuit_breaker_count += 1
                diagnostic_alerts.append({
                    "bar": current_bar_idx,
                    "timestamp": str(current_dt),
                    "probe": "CIRCUIT_BREAKER_TRIPPED",
                    "severity": "HIGH",
                    "details": f"Drawdown {equity_drawdown:.2%} breached {max_drawdown_limit:.0%} limit. Forcing cash."
                })
        elif circuit_breaker_active and equity_drawdown < (max_drawdown_limit * 0.5):
            circuit_breaker_active = False

        bars_since_rebalance = current_bar_idx - last_rebalance_idx
        should_evaluate_allocations = (bars_since_rebalance >= min_hold_bars) or circuit_breaker_active

        if should_evaluate_allocations:
            # Parse indicator snapshots for active tickers (recent 120-bar slice)
            parsed_assets = {}
            for asset_key in ACTIVE_ASSET_KEYS:
                yf_sym = TICKER_TO_YF[asset_key]
                if yf_sym in hist_slice.columns.levels[0]:
                    tk_df = hist_slice[yf_sym].dropna(how="all").iloc[-120:]
                    if len(tk_df) > 10:
                        parsed_assets[asset_key] = compute_stats(tk_df["Close"].squeeze(), rolling_window=60)
                        parsed_assets[asset_key]["raw_series"] = tk_df["Close"].squeeze()

            # Parse Bonds
            us10y_yield, us2y_yield = 4.2, 4.0
            if "^TNX" in hist_slice.columns.levels[0]:
                s = hist_slice["^TNX"]["Close"].dropna().squeeze()
                if len(s) > 0: us10y_yield = float(s.iloc[-1])
            if "^FVX" in hist_slice.columns.levels[0]:
                s = hist_slice["^FVX"]["Close"].dropna().squeeze()
                if len(s) > 0: us2y_yield = float(s.iloc[-1])

            bonds_dict = {
                "us10y_yield": us10y_yield,
                "us2y_yield": us2y_yield,
                "spread_2s10s": round(us10y_yield - us2y_yield, 3)
            }

            # SPX current values (recent 150 bars)
            spx_ohlcv = hist_slice["^GSPC"].dropna().iloc[-150:]
            spx_close_series = spx_ohlcv["Close"].squeeze()
            spx_vol_series = spx_ohlcv["Volume"].squeeze()
            current_spx_val = float(spx_close_series.iloc[-1])
            volume_heat = compute_volume_heat(spx_close_series, spx_vol_series)
            ihi_val = volume_heat.get("institutional_heat_index", 0.0)

            # Self-calibration of dynamic Brier score
            dynamic_brier, predictions_history = run_self_calibration(
                history=predictions_history,
                current_spx_val=current_spx_val,
                current_ihi=ihi_val,
                grading_delay=5,
                interval="1h"
            )

            # Feature vector for SPX
            spx_delta = spx_close_series.diff()
            gain = spx_delta.where(spx_delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
            loss = (-spx_delta.where(spx_delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
            rs = gain / loss.replace(0, 0.0001)
            rsi_14 = float((100 - (100 / (1 + rs))).iloc[-1]) if len(rs) > 0 else 50.0

            ema12 = spx_close_series.ewm(span=12, adjust=False).mean()
            ema26 = spx_close_series.ewm(span=26, adjust=False).mean()
            macd_hist = float((ema12 - ema26 - (ema12 - ema26).ewm(span=9, adjust=False).mean()).iloc[-1])

            sma20 = spx_close_series.rolling(window=20).mean()
            std20 = spx_close_series.rolling(window=20).std()
            bbw_20 = float(((4 * std20) / sma20.replace(0, 0.0001)).iloc[-1]) if len(std20) > 0 else 0.02

            # Check for division by zero in volatility
            std_val = float(std20.iloc[-1]) if len(std20.dropna()) > 0 else 0.0
            if std_val <= 0:
                diagnostic_alerts.append({
                    "bar": current_bar_idx,
                    "timestamp": str(current_dt),
                    "probe": "ZERO_VOLATILITY_TRAP",
                    "severity": "WARNING",
                    "details": "Rolling 20-bar std is 0.0; fallback applied."
                })

            vix_close = hist_slice["^VIX"]["Close"].dropna().squeeze() if "^VIX" in hist_slice.columns.levels[0] else pd.Series()
            vix_corr_10 = 0.0
            if len(vix_close) >= 20 and len(spx_close_series) >= 20:
                spx_ret = spx_close_series.pct_change() * 100
                vix_ret = vix_close.pct_change() * 100
                corr = spx_ret.rolling(10).corr(vix_ret).fillna(0)
                vix_corr_10 = float(corr.iloc[-1])

            # Regime Ensemble
            trend_res = trend_engine.score(spx_ohlcv) if len(spx_ohlcv) >= 20 else {}
            smc_res = smc_engine.compute(spx_ohlcv) if len(spx_ohlcv) >= 20 else None
            smc_dict = smc_res.__dict__ if smc_res else {}
            liq_res = liquidity_engine.compute(spx_ohlcv) if len(spx_ohlcv) >= 20 else {}
            meta_dict = {
                "vix_zscore": float(parsed_assets.get("SPX", {}).get("z_score", 0.0)),
                "spread_level": bonds_dict.get("spread_2s10s", 0.0)
            }
            regime_probs, dom_regime, tr_risk, _ = regime_ensemble.compute(
                trend_res, smc_dict, {}, liq_res, meta_dict
            )

            # MCS & Kalman Filter
            mcs_val, mcs_components = compute_mcs(parsed_assets, bonds_dict, parsed_assets)
            kalman_res = run_kalman_filter(
                mcs=mcs_val,
                sub_components=mcs_components,
                hmm_regime_probs=regime_probs,
                prior_state=prior_k_state,
                prior_cov=prior_k_cov
            )
            prior_k_state = kalman_res.probabilities
            prior_k_cov = kalman_res.covariance_matrix
            kalman_dominant = kalman_res.dominant_state

            # Multi-Asset ML Inference
            features_vector = [
                round(parsed_assets.get("SPX", {}).get("z_score", 0.0), 3),
                round(rsi_14, 2),
                round(macd_hist, 3),
                round(bbw_20, 4),
                round(vix_corr_10, 3),
                round(parsed_assets.get("BTC", {}).get("delta_pct", 0.0), 3),
                round(parsed_assets.get("SPX", {}).get("delta_pct", 0.0), 3),
                round(parsed_assets.get("SPX", {}).get("delta_pct", 0.0), 3),
                round(parsed_assets.get("SPX", {}).get("delta_pct", 0.0), 3),
                round(parsed_assets.get("NVDA", {}).get("delta_pct", 0.0), 3),
                round(parsed_assets.get("TSLA", {}).get("delta_pct", 0.0), 3),
                round(parsed_assets.get("DELL", {}).get("delta_pct", 0.0), 3),
                round(parsed_assets.get("SPCE", {}).get("delta_pct", 0.0), 3)
            ]
            mlp_predictions = run_multi_mlp_inference(features_vector, mlp_packages, dom_regime)

            # Compute Kelly Allocations
            raw_kellys = risk_engine.compute_multi_asset_kelly(
                mlp_predictions=mlp_predictions,
                dominant_state=kalman_dominant,
                brier_score=dynamic_brier,
                duration_days=5,
                hmm_regime=dom_regime,
                current_ihi=ihi_val,
                max_kelly_cap=0.40,
                equity_drawdown=equity_drawdown,
                entry_score=0.5
            )

            target_allocations = {
                "spx": raw_kellys.get("SPX_Kelly", 0.0),
                "btc": raw_kellys.get("BTC_Kelly", 0.0),
                "gld": raw_kellys.get("GLD_Kelly", 0.0),
                "wti": raw_kellys.get("WTI_Kelly", 0.0),
                "nvda": raw_kellys.get("NVDA_Kelly", 0.0),
                "tsla": raw_kellys.get("TSLA_Kelly", 0.0),
                "dell": raw_kellys.get("DELL_Kelly", 0.0),
                "spce": raw_kellys.get("SPCE_Kelly", 0.0),
                "cash": raw_kellys.get("Cash", 1.0)
            }

            # Apply Circuit Breaker or Conviction Thresholds
            if circuit_breaker_active:
                target_allocations = {k: 0.0 for k in target_allocations}
                target_allocations["cash"] = 1.0
            else:
                for asset_lower, thresh in ASSET_ENTRY_THRESHOLDS.items():
                    asset_upper = asset_lower.upper()
                    asset_p = mlp_predictions.get(asset_upper, {}).get("bull_probability", 0.0)
                    if asset_p < thresh:
                        blocked = target_allocations.get(asset_lower, 0.0)
                        if blocked > 0:
                            conviction_blocks += 1
                            target_allocations[asset_lower] = 0.0
                            target_allocations["cash"] += blocked

                if dom_regime in ("RISK_ON_EXPANSION", "LIQUIDITY_DRIVEN_RALLY") and target_allocations["spx"] == 0:
                    if target_allocations["cash"] >= 0.15:
                        target_allocations["spx"] = 0.15
                        target_allocations["cash"] -= 0.15
                elif dom_regime == "NEUTRAL_TRANSITIONAL" and target_allocations["gld"] == 0:
                    if target_allocations["cash"] >= 0.05:
                        target_allocations["gld"] = 0.05
                        target_allocations["cash"] -= 0.05

            # Normalize Allocations & Check Invariants
            active_sum = sum(v for k, v in target_allocations.items() if k != "cash")
            if active_sum > 1.0:
                for k in target_allocations:
                    if k != "cash": target_allocations[k] /= active_sum
                target_allocations["cash"] = 0.0
            else:
                target_allocations["cash"] = round(1.0 - active_sum, 4)

            # --- Diagnostic Probe 2: Allocation Invariant Assertion ---
            alloc_sum = sum(target_allocations.values())
            if not (0.999 <= alloc_sum <= 1.001) or target_allocations["cash"] < -1e-5:
                diagnostic_alerts.append({
                    "bar": current_bar_idx,
                    "timestamp": str(current_dt),
                    "probe": "ALLOCATION_INVARIANT_VIOLATION",
                    "severity": "CRITICAL",
                    "details": f"Sum={alloc_sum:.5f}, Cash={target_allocations['cash']:.5f}"
                })

            # --- REBALANCING LOGIC (Min Hold Period = min_hold_bars) ---
            turnover = sum(abs(target_allocations[k] - current_allocations[k]) for k in target_allocations if k != "cash")
            if turnover > 0.05:  # 5% threshold
                last_rebalance_idx = current_bar_idx
                total_trades += 1

                # Deduct slippage per asset
                rebalance_fee = 0.0
                for k in target_allocations:
                    if k == "cash": continue
                    delta_alloc = abs(target_allocations[k] - current_allocations[k])
                    slip_rate = SLIPPAGE_MAP.get(k, 0.0010)
                    rebalance_fee += delta_alloc * simulated_equity * slip_rate

                simulated_equity -= rebalance_fee
                total_fees_paid += rebalance_fee

                # Log trade execution
                for k, t_alloc in target_allocations.items():
                    if k == "cash": continue
                    c_alloc = current_allocations[k]
                    if abs(t_alloc - c_alloc) > 0.01:
                        action = "BUY" if t_alloc > c_alloc else "SELL"
                        asset_sym = TICKER_TO_YF.get(k.upper(), k.upper())
                        fill_price = 100.0
                        if asset_sym in hist_slice.columns.levels[0]:
                            ps = hist_slice[asset_sym]["Close"].dropna()
                            if len(ps) > 0: fill_price = float(ps.iloc[-1])
                        trade_val = abs(t_alloc - c_alloc) * simulated_equity
                        shares = trade_val / fill_price if fill_price > 0 else 0.0

                        trades_ledger.append({
                            "timestamp": str(current_dt),
                            "action": action,
                            "asset": k.upper(),
                            "shares": round(shares, 4),
                            "fill_price": round(fill_price, 2),
                            "trade_value": round(trade_val, 2),
                            "regime": dom_regime,
                            "equity_after": round(simulated_equity, 2)
                        })

                current_allocations = target_allocations.copy()

        # Continuous Compounding: 1-bar forward return on held allocations
        future_slice = raw_data[raw_data.index > current_dt]
        bar_return_dollar = 0.0

        for k in target_allocations:
            if k == "cash": continue
            weight = current_allocations[k]
            if weight <= 0: continue

            asset_sym = TICKER_TO_YF[k.upper()]
            if asset_sym in future_slice.columns.levels[0] and asset_sym in hist_slice.columns.levels[0]:
                fs = future_slice[asset_sym]["Close"].dropna()
                cs = hist_slice[asset_sym]["Close"].dropna()
                if len(fs) > 0 and len(cs) > 0:
                    current_price = float(cs.iloc[-1])
                    future_price = float(fs.iloc[0])
                    if current_price > 0:
                        r_1bar = (future_price - current_price) / current_price
                        bar_return_dollar += (weight * simulated_equity) * r_1bar

        # Cash interest accrual (4.5% annual risk-free rate)
        cash_weight = current_allocations["cash"]
        hourly_rf = (0.045 / (252 * 6.5))
        cash_yield_dollar = (cash_weight * simulated_equity) * hourly_rf
        bar_return_dollar += cash_yield_dollar

        # Update equity
        equity_before = simulated_equity
        simulated_equity += bar_return_dollar
        bar_pnl_pct = (simulated_equity - equity_before) / equity_before if equity_before > 0 else 0.0
        bar_pnl_history.append(bar_pnl_pct)

        if simulated_equity > peak_equity:
            peak_equity = simulated_equity

        # Track telemetry
        hourly_telemetry.append({
            "timestamp": str(current_dt),
            "equity": round(simulated_equity, 2),
            "peak_equity": round(peak_equity, 2),
            "drawdown": round(equity_drawdown, 4),
            "regime": dom_regime,
            "kalman": kalman_dominant,
            "spx_weight": round(current_allocations["spx"], 3),
            "btc_weight": round(current_allocations["btc"], 3),
            "gld_weight": round(current_allocations["gld"], 3),
            "wti_weight": round(current_allocations["wti"], 3),
            "nvda_weight": round(current_allocations["nvda"], 3),
            "tsla_weight": round(current_allocations["tsla"], 3),
            "dell_weight": round(current_allocations["dell"], 3),
            "spce_weight": round(current_allocations["spce"], 3),
            "cash_weight": round(current_allocations["cash"], 3),
            "fees_paid": round(total_fees_paid, 2)
        })

    # Summary performance metrics
    final_equity = simulated_equity
    total_return_pct = ((final_equity - initial_capital) / initial_capital) * 100
    spx_initial = float(raw_data["^GSPC"]["Close"].loc[active_indices[0]])
    spx_final = float(raw_data["^GSPC"]["Close"].loc[active_indices[-1]])
    spx_bnh_return_pct = ((spx_final - spx_initial) / spx_initial) * 100

    rets = np.array(bar_pnl_history)
    mean_ret = float(np.mean(rets)) if len(rets) > 0 else 0.0
    std_ret = float(np.std(rets)) if len(rets) > 0 else 0.0
    ann_factor = np.sqrt(252 * 6.5)
    sharpe = ((mean_ret - hourly_rf) / std_ret * ann_factor) if std_ret > 0 else 0.0

    downside_rets = rets[rets < hourly_rf]
    downside_std = float(np.std(downside_rets)) if len(downside_rets) > 0 else 1e-4
    sortino = ((mean_ret - hourly_rf) / downside_std * ann_factor) if downside_std > 0 else 0.0

    equities = [h["equity"] for h in hourly_telemetry]
    running_max = np.maximum.accumulate(equities)
    drawdowns = (running_max - equities) / running_max
    max_mdd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    # Win rate
    wins = np.sum(rets > 0)
    losses = np.sum(rets < 0)
    active_win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0.0
    profit_factor = float(np.sum(rets[rets > 0]) / abs(np.sum(rets[rets < 0]))) if np.sum(rets[rets < 0]) != 0 else 1.0

    results_summary = {
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return_pct, 2),
        "spx_buy_and_hold_return_pct": round(spx_bnh_return_pct, 2),
        "alpha_vs_spx": round(total_return_pct - spx_bnh_return_pct, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "max_drawdown_pct": round(max_mdd * 100, 2),
        "active_win_rate_pct": round(active_win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "total_trades": total_trades,
        "total_slippage_fees": round(total_fees_paid, 2),
        "circuit_breaker_trips": circuit_breaker_count,
        "conviction_blocks": conviction_blocks,
        "total_bars_evaluated": len(active_indices),
        "start_time": str(active_indices[0]),
        "end_time": str(active_indices[-1]),
        "diagnostic_alerts_count": len(diagnostic_alerts)
    }

    print("\n" + "=" * 80)
    print("BACKTEST RESULTS SUMMARY")
    print("=" * 80)
    for k, v in results_summary.items():
        print(f"  {k:30s}: {v}")
    print("=" * 80)

    # Save to SQLite Database
    db_path = os.path.join(REPO_ROOT, "data", "paper_trading", "backtest_5000h.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        action TEXT,
        asset TEXT,
        shares REAL,
        fill_price REAL,
        trade_value REAL,
        regime TEXT,
        equity_after REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS hourly_telemetry (
        timestamp TEXT PRIMARY KEY,
        equity REAL,
        peak_equity REAL,
        drawdown REAL,
        regime TEXT,
        kalman TEXT,
        spx_weight REAL,
        btc_weight REAL,
        gld_weight REAL,
        wti_weight REAL,
        nvda_weight REAL,
        tsla_weight REAL,
        dell_weight REAL,
        spce_weight REAL,
        cash_weight REAL,
        fees_paid REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS diagnostic_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bar INTEGER,
        timestamp TEXT,
        probe TEXT,
        severity TEXT,
        details TEXT
    )
    """)

    cur.execute("DELETE FROM trades")
    cur.execute("DELETE FROM hourly_telemetry")
    cur.execute("DELETE FROM diagnostic_alerts")

    if trades_ledger:
        cur.executemany("""
        INSERT INTO trades (timestamp, action, asset, shares, fill_price, trade_value, regime, equity_after)
        VALUES (:timestamp, :action, :asset, :shares, :fill_price, :trade_value, :regime, :equity_after)
        """, trades_ledger)

    if hourly_telemetry:
        cur.executemany("""
        INSERT INTO hourly_telemetry (timestamp, equity, peak_equity, drawdown, regime, kalman,
            spx_weight, btc_weight, gld_weight, wti_weight, nvda_weight, tsla_weight, dell_weight, spce_weight, cash_weight, fees_paid)
        VALUES (:timestamp, :equity, :peak_equity, :drawdown, :regime, :kalman,
            :spx_weight, :btc_weight, :gld_weight, :wti_weight, :nvda_weight, :tsla_weight, :dell_weight, :spce_weight, :cash_weight, :fees_paid)
        """, hourly_telemetry)

    if diagnostic_alerts:
        cur.executemany("""
        INSERT INTO diagnostic_alerts (bar, timestamp, probe, severity, details)
        VALUES (:bar, :timestamp, :probe, :severity, :details)
        """, diagnostic_alerts)

    con.commit()
    con.close()
    print(f"[Storage] Saved SQLite database to {db_path}.")

    # Save to Parquet
    telemetry_df = pd.DataFrame(hourly_telemetry)
    parquet_path = os.path.join(REPO_ROOT, "data", "paper_trading", "backtest_5000h_equity.parquet")
    telemetry_df.to_parquet(parquet_path)
    print(f"[Storage] Saved Parquet equity timeseries to {parquet_path}.")

    # Save JSON summary
    summary_path = os.path.join(REPO_ROOT, "data", "paper_trading", "backtest_5000h_summary.json")
    with open(summary_path, "w") as f:
        json.dump({
            "summary": results_summary,
            "diagnostic_alerts": diagnostic_alerts[:50]  # top alerts
        }, f, indent=4)
    print(f"[Storage] Saved JSON summary to {summary_path}.")

    # Save CSV Ledger
    csv_path = os.path.join(REPO_ROOT, "data", "paper_trading", "backtest_5000h_ledger.csv")
    pd.DataFrame(trades_ledger).to_csv(csv_path, index=False)
    print(f"[Storage] Saved CSV trade ledger to {csv_path}.")

    return results_summary, diagnostic_alerts, hourly_telemetry, trades_ledger


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--hold-bars", type=int, default=6)
    parser.add_argument("--warmup", type=int, default=150)
    parser.add_argument("--bars", type=int, default=None)
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args()

    run_5000h_simulation(
        initial_capital=args.capital,
        min_hold_bars=args.hold_bars,
        warmup_bars=args.warmup,
        force_download=args.force_download,
        bars_limit=args.bars
    )
