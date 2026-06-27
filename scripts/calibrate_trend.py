import pandas as pd
import yfinance as yf
import numpy as np

def calibrate():
    tickers = ["^GSPC", "^VIX"]
    raw = yf.download(tickers, start="2010-01-01", end="2024-12-31", group_by="ticker", progress=False)
    
    spx = raw["^GSPC"]["Close"].dropna()
    vix = raw["^VIX"]["Close"].dropna()
    
    df = pd.DataFrame({"spx": spx, "vix": vix}).dropna()
    df["sma200"] = df["spx"].rolling(200).mean()
    df["fwd_ret"] = df["spx"].pct_change().shift(-1)
    df = df.dropna()
    
    long_mask = (df["spx"] > df["sma200"]) & (df["vix"] < 25.0)
    flat_mask = (df["spx"] < df["sma200"]) | (df["vix"] > 30.0)
    
    # Calculate stateful positions
    state = False
    positions = []
    for idx, row in df.iterrows():
        if state:
            if row["spx"] < row["sma200"] or row["vix"] > 30.0:
                state = False
        else:
            if row["spx"] > row["sma200"] and row["vix"] < 25.0:
                state = True
        positions.append(1 if state else 0)
        
    df["pos"] = positions
    
    long_bars = df[df["pos"] == 1]
    flat_bars = df[df["pos"] == 0]
    
    long_hit = (long_bars["fwd_ret"] > 0).mean()
    flat_hit = (flat_bars["fwd_ret"] > 0).mean()
    
    print(f"Long Bars: {len(long_bars)} | Hit Rate: {long_hit:.2%} | Avg Ret: {long_bars['fwd_ret'].mean():.4%}")
    print(f"Flat Bars: {len(flat_bars)} | Hit Rate: {flat_hit:.2%} | Avg Ret: {flat_bars['fwd_ret'].mean():.4%}")
    
if __name__ == "__main__":
    calibrate()
