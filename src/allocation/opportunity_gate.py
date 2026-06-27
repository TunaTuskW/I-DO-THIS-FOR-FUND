"""Opportunity Gate.
Evaluates portfolio-level conviction. Acts strictly as a GATE (0 or 1).
Never multiplies weights."""

from config.symbols import UNIVERSE
from src.observability.logger import get_logger

logger = get_logger("opportunity_gate")

def gate_signals(raw_signals: dict) -> dict:
    """
    Evaluates sum of active signals.
    If conviction < 0.2, return all zeros (go to cash).
    Otherwise, pass raw signals through unchanged to the Risk Engine.
    """
    active_count = sum(1 for v in raw_signals.values() if v > 0.0)
    total_assets = len(UNIVERSE)
    
    conviction_score = active_count / total_assets if total_assets > 0 else 0.0
    
    if conviction_score < 0.2:
        logger.info(f"Opportunity Gate CLOSED (Conviction: {conviction_score:.2f} < 0.2). Forcing 100% cash.")
        return {k: 0.0 for k in raw_signals.keys()}
        
    logger.info(f"Opportunity Gate OPEN (Conviction: {conviction_score:.2f}). Passing signals.")
    return raw_signals
