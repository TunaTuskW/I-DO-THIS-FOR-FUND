"""Risk Engine.
Strictly normalizes raw signals to guarantee the allocation invariant:
sum(abs(weights)) <= 1.0."""

from src.observability.logger import get_logger

logger = get_logger("risk_engine")

def normalize_weights(raw_signals: dict) -> dict:
    """
    Normalizes weights if their absolute sum exceeds 1.0.
    Ensures no leverage is applied.
    """
    total = sum(abs(v) for v in raw_signals.values())
    
    if total > 1.0:
        logger.info(f"Risk Engine normalizing weights. Original sum: {total:.2f}. Scaling down to 1.0.")
        return {k: v / total for k, v in raw_signals.items()}
        
    return raw_signals
