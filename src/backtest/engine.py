"""Phase 1 Backtest Engine Rewrite.
Enforces allocation invariants before any compounding logic."""

import argparse
import importlib
import numpy as np
import pandas as pd
import yfinance as yf
import datetime
import os
from config.symbols import UNIVERSE

def enforce_invariant(weights: dict) -> dict:
    """Ensure 0 <= sum(weights) <= 1. ✅ invariant."""
    w = {k: max(0.0, v) for k, v in weights.items()}
    total = sum(w.values())
    if total > 1.0:
        return {k: v / total for k, v in w.items()}
    return w

def run_backtest(strategy_name: str, start_date: str, end_date: str):
    is_ml_pipeline = (strategy_name == "ml_pipeline")
    strat_mod = importlib.import_module(f"src.strategies.{strategy_name}") if not is_ml_pipeline else None
    if is_ml_pipeline:
        from src.signals.ml_signal import signal as ml_signal
        from src.allocation.opportunity_gate import gate_signals
        from src.allocation.risk_engine import normalize_weights
    
    print(f"Fetching data from {start_date} to {end_date}...")
    
    ticker_map = {
        "SPX": "^GSPC", "NDX": "^NDX", "RUT": "^RUT", "VIX": "^VIX", "VIX3M": "^VIX3M",
        "BTC-PERP": "BTC-USD", "ETH-PERP": "ETH-USD", "DAX": "^GDAXI", "Nikkei": "^N225",
        "TY": "ZN=F", "CL": "CL=F", "GC": "GC=F", "UB": "ZB=F", "EURUSD=X": "EURUSD=X"
    }
    fetch_list = list(set([ticker_map.get(a, a) for a in UNIVERSE] + ["^GSPC", "^VIX", "^VIX3M", "BTC-USD"])) if is_ml_pipeline else ["^GSPC", "^VIX"]
    raw = yf.download(fetch_list, start=start_date, end=end_date, group_by="ticker", progress=False)
    
    history_dict = {}
    if is_ml_pipeline:
        for asset in UNIVERSE + ["VIX3M"]:
            mapped = ticker_map.get(asset, asset)
            if mapped in raw.columns.levels[0]:
                df = pd.DataFrame({"close": raw[mapped]["Close"]}).dropna()
                if "PERP" in asset:
                    df["funding_rate"] = 0.0001
                history_dict[asset] = df
            else:
                history_dict[asset] = pd.DataFrame()
    else:
        history_dict["SPX"] = pd.DataFrame({"close": raw["^GSPC"]["Close"]}).dropna()
        history_dict["VIX"] = pd.DataFrame({"close": raw["^VIX"]["Close"]}).dropna()
    
    dates = history_dict["SPX"].index
    
    # Align all assets to SPX calendar to prevent holiday KeyErrors
    for asset in list(history_dict.keys()):
        if not history_dict[asset].empty and asset != "SPX":
            history_dict[asset] = history_dict[asset].reindex(dates, method='ffill')
            
    equity = 1.0
    equity_curve = []
    
    state = {}
    current_weights = {a: 0.0 for a in (UNIVERSE if is_ml_pipeline else ["SPX"])}
    trades = 0
    total_slippage = 0.0
    
    start_idx = 200
    
    for i in range(start_idx, len(dates)):
        current_date = dates[i]
        
        sub_hist = {}
        for k, v in history_dict.items():
            if not v.empty:
                sub_hist[k] = v.loc[:current_date]
                
        bar = {"timestamp": current_date.isoformat(), "state": state}
        
        if is_ml_pipeline:
            raw_sigs = ml_signal(bar, sub_hist)
            gated = gate_signals(raw_sigs)
            target_weights = normalize_weights(gated)
        else:
            target_weights = strat_mod.signal(bar, sub_hist)
            target_weights = enforce_invariant(target_weights)
        
        daily_slip = 0.0
        for asset, tw in target_weights.items():
            cw = current_weights.get(asset, 0.0)
            diff = tw - cw
            if abs(diff) > 0.001:
                daily_slip += abs(diff) * 0.0005
                trades += 1
                
        if daily_slip > 0:
            total_slippage += daily_slip
            equity -= daily_slip * equity
            
        if i < len(dates) - 1:
            next_date = dates[i+1]
            daily_port_ret = 0.0
            for asset, w in target_weights.items():
                if w > 0 and asset in history_dict and not history_dict[asset].empty:
                    if next_date in history_dict[asset].index:
                        ret = (history_dict[asset]["close"].loc[next_date] / history_dict[asset]["close"].loc[current_date]) - 1
                        daily_port_ret += w * ret
            equity *= (1 + daily_port_ret)
            
        current_weights = target_weights
        
        if not is_ml_pipeline:
            if target_weights.get("SPX", 0.0) > 0.5:
                state['spx_trend_long'] = True
            else:
                state['spx_trend_long'] = False
            
        equity_curve.append(equity)
        
    final_eq = equity_curve[-1] if equity_curve else 1.0
    bnh_ret = (history_dict["SPX"]["close"].iloc[-1] / history_dict["SPX"]["close"].iloc[start_idx]) - 1
    
    print("-" * 30)
    print(f"Strategy Total Return: {(final_eq - 1) * 100:.2f}%")
    print(f"BnH SPX Total Return:  {bnh_ret * 100:.2f}%")
    
    years = (dates[-1] - dates[start_idx]).days / 365.25 if (dates[-1] - dates[start_idx]).days > 0 else 1
    cagr = (final_eq ** (1/years) - 1) * 100 if final_eq > 0 else 0.0
    print(f"Strategy CAGR:         {cagr:.2f}%")
    
    eq_series = pd.Series(equity_curve)
    drawdown = (eq_series / eq_series.cummax() - 1).min() * 100 if not eq_series.empty else 0.0
    print(f"Max Drawdown:          {drawdown:.2f}%")
    
    if len(eq_series) > 1:
        daily_rets = eq_series.pct_change().dropna()
        sharpe = (daily_rets.mean() / daily_rets.std()) * np.sqrt(252) if daily_rets.std() > 0 else 0
    else:
        sharpe = 0.0
    print(f"Sharpe Ratio:          {sharpe:.2f}")
    
    print(f"Number of trades:      {trades}")
    print(f"Avg slip cost/trade:   {total_slippage/trades*100 if trades > 0 else 0:.4f}%")
    print("-" * 30)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", type=str, required=True)
    parser.add_argument("--start", type=str, required=True)
    parser.add_argument("--end", type=str, required=True)
    args = parser.parse_args()
    
    run_backtest(args.strategy, args.start, args.end)
