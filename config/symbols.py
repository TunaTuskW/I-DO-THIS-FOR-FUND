"""
Asset universe definition.
Kept in Phase 0 as infrastructure.
Will be EXTENDED in Phase 2.
"""

UNIVERSE = [
    # Tier 1
    "SPX",       # US equity index
    "NDX",       # US equity index (Nasdaq)
    "RUT",       # US equity index (small cap)
    "VIX",       # Volatility index
    "BTC-PERP",  # Crypto perp
    "ETH-PERP",  # Crypto perp
    
    # Tier 2
    "DAX",       # EU equity index
    "Nikkei",    # JP equity index
    "TY",        # US bond futures (10Y)
    "CL",        # Commodity (WTI oil)
    "GC",        # Commodity (Gold)
    
    # Tier 3
    "UB",        # US bond futures (long duration)
    "EURUSD=X"   # FX (using standard Yahoo ticker format)
]
