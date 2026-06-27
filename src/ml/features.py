"""Feature definitions. Single source of truth for training and inference.
NaN-safe pure functions for cross-asset evaluation."""

import numpy as np
import pandas as pd

# ---------------------------------------------------------
# Price & Return Features (Universal)
# ---------------------------------------------------------
def feature_ret_10d(bar, history, symbol):
    """10-day return. High = bullish momentum."""
    df = history.get(symbol, pd.DataFrame())
    if 'close' not in df.columns or len(df) < 10: return 0.0
    return (df['close'].iloc[-1] / df['close'].iloc[-10]) - 1.0

def feature_ret_50d(bar, history, symbol):
    """50-day return. High = bullish medium-term trend."""
    df = history.get(symbol, pd.DataFrame())
    if 'close' not in df.columns or len(df) < 50: return 0.0
    return (df['close'].iloc[-1] / df['close'].iloc[-50]) - 1.0

def feature_ret_200d(bar, history, symbol):
    """200-day return. High = bullish macro trend."""
    df = history.get(symbol, pd.DataFrame())
    if 'close' not in df.columns or len(df) < 200: return 0.0
    return (df['close'].iloc[-1] / df['close'].iloc[-200]) - 1.0

def feature_realized_vol_20d(bar, history, symbol):
    """20-day realized volatility. High = instability/risk-off."""
    df = history.get(symbol, pd.DataFrame())
    if 'close' not in df.columns or len(df) < 20: return 0.0
    rets = df['close'].pct_change().tail(20)
    return rets.std() * np.sqrt(252)

def feature_dist_200_sma(bar, history, symbol):
    """Distance from 200-day SMA. High = overextended bullish."""
    df = history.get(symbol, pd.DataFrame())
    if 'close' not in df.columns or len(df) < 200: return 0.0
    sma200 = df['close'].rolling(200).mean().iloc[-1]
    return (df['close'].iloc[-1] / sma200) - 1.0

def feature_dist_52w_high(bar, history, symbol):
    """Distance from 52-week (252-day) high. Negative = drawdown."""
    df = history.get(symbol, pd.DataFrame())
    if 'close' not in df.columns or len(df) < 252: return 0.0
    high52 = df['close'].tail(252).max()
    return (df['close'].iloc[-1] / high52) - 1.0

# ---------------------------------------------------------
# Volatility Features (Equities/Macro)
# ---------------------------------------------------------
def feature_vix_level(bar, history, symbol):
    """Current VIX level. High = market fear."""
    vix = history.get('VIX', pd.DataFrame())
    if 'close' not in vix.columns or len(vix) < 1: return 0.0
    return vix['close'].iloc[-1]

def feature_vix_term_structure(bar, history, symbol):
    """VIX / VIX3M (Term structure). High (>1.0) = backwardation/panic."""
    vix = history.get('VIX', pd.DataFrame())
    vix3m = history.get('VIX3M', pd.DataFrame()) # Requires VIX3M in data lake
    if 'close' not in vix.columns or 'close' not in vix3m.columns or len(vix) < 1 or len(vix3m) < 1: return 0.0
    return vix['close'].iloc[-1] / vix3m['close'].iloc[-1]

# ---------------------------------------------------------
# Crypto Funding Rate Features
# ---------------------------------------------------------
def feature_funding_rate_current(bar, history, symbol):
    """Current funding rate. High positive = longs paying shorts (overleveraged bullish)."""
    df = history.get(symbol, pd.DataFrame())
    if 'funding_rate' not in df.columns or len(df) < 1: return 0.0
    return df['funding_rate'].iloc[-1]

def feature_funding_rate_7d_avg(bar, history, symbol):
    """7-day average funding rate."""
    df = history.get(symbol, pd.DataFrame())
    if 'funding_rate' not in df.columns or len(df) < 7: return 0.0
    return df['funding_rate'].tail(7).mean()

def feature_funding_rate_zscore_30d(bar, history, symbol):
    """30-day z-score of funding rate. High > 2 = contrarian short signal."""
    df = history.get(symbol, pd.DataFrame())
    if 'funding_rate' not in df.columns or len(df) < 30: return 0.0
    window = df['funding_rate'].tail(30)
    if window.std() == 0: return 0.0
    return (window.iloc[-1] - window.mean()) / window.std()

def feature_funding_cost_cumulative_30d(bar, history, symbol):
    """Cumulative funding cost over 30d (long's pain)."""
    df = history.get(symbol, pd.DataFrame())
    if 'funding_rate' not in df.columns or len(df) < 30: return 0.0
    return df['funding_rate'].tail(30).sum()

# ---------------------------------------------------------
# Futures Basis / Cost-of-Carry Features
# ---------------------------------------------------------
def feature_futures_basis(bar, history, symbol):
    """Futures-spot basis (futures price / spot price - 1)."""
    df = history.get(symbol, pd.DataFrame())
    if 'basis' not in df.columns or len(df) < 1: return 0.0
    return df['basis'].iloc[-1]

def feature_implied_carry(bar, history, symbol):
    """Implied carry (Yield - Risk Free Rate)."""
    df = history.get(symbol, pd.DataFrame())
    if 'implied_carry' not in df.columns or len(df) < 1: return 0.0
    return df['implied_carry'].iloc[-1]

# ---------------------------------------------------------
# Cross-Asset Correlation Features
# ---------------------------------------------------------
def feature_spx_vix_corr_30d(bar, history, symbol):
    """SPX-VIX 30-day correlation. Positive = broken correlation regime."""
    spx = history.get('SPX', pd.DataFrame())
    vix = history.get('VIX', pd.DataFrame())
    if 'close' not in spx.columns or 'close' not in vix.columns or len(spx) < 30 or len(vix) < 30: return 0.0
    spx_ret = spx['close'].pct_change().tail(30)
    vix_ret = vix['close'].pct_change().tail(30)
    return spx_ret.corr(vix_ret)

def feature_btc_spx_corr_30d(bar, history, symbol):
    """BTC-SPX 30-day correlation. High = risk-on macro coupling."""
    btc = history.get('BTC-PERP', pd.DataFrame())
    spx = history.get('SPX', pd.DataFrame())
    if 'close' not in btc.columns or 'close' not in spx.columns or len(btc) < 30 or len(spx) < 30: return 0.0
    btc_ret = btc['close'].pct_change().tail(30)
    spx_ret = spx['close'].pct_change().tail(30)
    return btc_ret.corr(spx_ret)

# Helper function to generate full vector
def build_feature_vector(bar, history, symbol):
    return {
        "ret_10d": feature_ret_10d(bar, history, symbol),
        "ret_50d": feature_ret_50d(bar, history, symbol),
        "ret_200d": feature_ret_200d(bar, history, symbol),
        "realized_vol_20d": feature_realized_vol_20d(bar, history, symbol),
        "dist_200_sma": feature_dist_200_sma(bar, history, symbol),
        "dist_52w_high": feature_dist_52w_high(bar, history, symbol),
        "vix_level": feature_vix_level(bar, history, symbol),
        "vix_term_structure": feature_vix_term_structure(bar, history, symbol),
        "funding_rate_current": feature_funding_rate_current(bar, history, symbol),
        "funding_rate_7d_avg": feature_funding_rate_7d_avg(bar, history, symbol),
        "funding_rate_zscore_30d": feature_funding_rate_zscore_30d(bar, history, symbol),
        "funding_cost_cumulative_30d": feature_funding_cost_cumulative_30d(bar, history, symbol),
        "futures_basis": feature_futures_basis(bar, history, symbol),
        "implied_carry": feature_implied_carry(bar, history, symbol),
        "spx_vix_corr_30d": feature_spx_vix_corr_30d(bar, history, symbol),
        "btc_spx_corr_30d": feature_btc_spx_corr_30d(bar, history, symbol)
    }
