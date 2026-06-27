"""Flat allocation — 100% cash. Used as Phase 0 placeholder
and as a safety fallback if any signal layer fails to load."""

import numpy as np
from config.symbols import UNIVERSE

def allocate(bar, state):
    """Return zero-weight vector. sum(weights) = 0 <= 1. ✅ invariant."""
    return {symbol: 0.0 for symbol in UNIVERSE}
