"""Target definitions for ML training.
Single source of truth to ensure no lookahead bias or asymmetric signal logic."""

import numpy as np
import pandas as pd

def build_target_5d_direction(history: pd.DataFrame) -> pd.Series:
    """
    Returns 1 if the 5-day forward return is strictly positive, 0 otherwise.
    Uses shift(-5) to look into the future during training.
    """
    if 'close' not in history.columns:
        return pd.Series(dtype=int)
        
    fwd_ret = history['close'].pct_change(5).shift(-5)
    return (fwd_ret > 0).astype(int)

def build_target_5d_magnitude(history: pd.DataFrame) -> pd.Series:
    """
    Returns the exact 5-day forward return magnitude for regression models.
    """
    if 'close' not in history.columns:
        return pd.Series(dtype=float)
        
    return history['close'].pct_change(5).shift(-5)
