import pytest
from src.allocation.opportunity_gate import gate_signals
from src.allocation.risk_engine import normalize_weights
from config.symbols import UNIVERSE

def test_full_pipeline_invariant():
    """
    Simulates a scenario where ML models output 100% conviction (1.0) 
    for every single asset in the universe.
    
    The raw sum will be 13.0.
    The Opportunity Gate will pass it (13/13 = 1.0 > 0.2).
    The Risk Engine MUST strictly normalize the total sum down to exactly 1.0.
    """
    raw_signals = {asset: 1.0 for asset in UNIVERSE}
    
    # Assert starting state is wildly over-leveraged
    assert sum(raw_signals.values()) > 1.0
    
    # Pass through gate
    gated_signals = gate_signals(raw_signals)
    
    # Normalize
    final_allocation = normalize_weights(gated_signals)
    
    total = sum(final_allocation.values())
    
    assert 0.0 <= total <= 1.0001, f"Invariant violated: sum(weights) = {total}"
    assert abs(total - 1.0) < 1e-5, f"Should be exactly 1.0, got {total}"
    assert final_allocation["SPX"] == 1.0 / len(UNIVERSE)

def test_opportunity_gate_closure():
    """
    Simulates low-conviction scenario (1 out of 13 active).
    The gate should force 100% cash.
    """
    raw_signals = {asset: 0.0 for asset in UNIVERSE}
    raw_signals["SPX"] = 1.0 # 1 / 13 = 0.076 conviction
    
    gated_signals = gate_signals(raw_signals)
    final_allocation = normalize_weights(gated_signals)
    
    total = sum(final_allocation.values())
    assert total == 0.0, f"Gate failed to close, total weight: {total}"
