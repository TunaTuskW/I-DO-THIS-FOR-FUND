"""Machine Learning Signal generation.
Loops through universe, constructs features, loads models, outputs raw signals."""

import os
import joblib
import pandas as pd
from config.symbols import UNIVERSE
from src.ml.features import build_feature_vector
from src.observability.logger import get_logger

logger = get_logger("ml_signal")

# In-memory cache to prevent reloading pickle files on every bar
_MODEL_CACHE = {}

def get_model(asset: str, timeframe: str = "1d"):
    cache_key = f"{asset}_{timeframe}"
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]
        
    model_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'models', f"{cache_key}.pkl")
    if os.path.exists(model_path):
        model = joblib.load(model_path)
        _MODEL_CACHE[cache_key] = model
        return model
    return None

def signal(bar, history):
    """
    Generate raw conviction signals for all assets.
    Returns: dict of {symbol: conviction (1.0 or 0.0)}
    Note: Output might sum > 1.0. Must be passed to an Allocator.
    """
    raw_signals = {}
    
    for asset in UNIVERSE:
        model = get_model(asset)
        if model is None:
            raw_signals[asset] = 0.0
            continue
            
        try:
            vec_dict = build_feature_vector(bar, history, asset)
            # Must map to DataFrame to match scikit-learn training input shape/names
            vec_df = pd.DataFrame([vec_dict]).fillna(0.0)
            
            # Predict
            pred = model.predict(vec_df)[0]
            raw_signals[asset] = float(pred)
            
        except Exception as e:
            logger.warning(f"Inference failed for {asset}: {e}")
            raw_signals[asset] = 0.0
            
    return raw_signals
