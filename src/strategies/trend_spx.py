"""Trend-following on SPX with VIX filter.
Phase 1 baseline — must beat buy-and-hold SPX net of slippage
before any ML work begins."""

import numpy as np
import pandas as pd

SMA_WINDOW = 200
VIX_ENTRY_CAP = 25.0
VIX_EXIT_FLOOR = 30.0

def signal(bar, history):
    """Return target weight for SPX. Either 0.0 or 1.0."""
    spx_close = history.get('SPX', pd.DataFrame()).get('close')
    vix_close = history.get('VIX', pd.DataFrame()).get('close')
    
    if spx_close is None or vix_close is None or len(spx_close) < SMA_WINDOW:
        return {'SPX': 0.0}  # not enough history or missing data

    sma = spx_close.rolling(SMA_WINDOW).mean().iloc[-1]
    last_close = spx_close.iloc[-1]
    last_vix = vix_close.iloc[-1]

    # Stateful: if currently long, use exit rule; if flat, use entry rule
    currently_long = bar.get('state', {}).get('spx_trend_long', False)

    if currently_long:
        if last_close < sma or last_vix > VIX_EXIT_FLOOR:
            return {'SPX': 0.0}
        return {'SPX': 1.0}
    else:
        if last_close > sma and last_vix < VIX_ENTRY_CAP:
            return {'SPX': 1.0}
        return {'SPX': 0.0}
