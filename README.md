# I-DO-THIS-FOR-FUND (v7.0)
*Autonomous Multi-Asset Quantitative Trading Engine*

## Architecture Overview (The v7.0 Rebuild)

In v7.0, the core execution pipeline was completely decoupled and rebuilt from scratch to definitively resolve compounding bugs, time-leakage issues, and leverage invariant violations.

The system now trades a universe of 13 globally uncorrelated assets (Tier 1 Equities/Volatility/Crypto, Tier 2 International/Commodities, and Tier 3 Bonds/FX) via a strict, mathematically verified three-phase pipeline:

### 1. ML Signal Generation (Phase 2)
13 distinct, cryptographically isolated Scikit-Learn `RandomForestClassifier` models are walk-forward trained on custom NaN-safe cross-asset features (including VIX term structure, crypto funding rates, and futures basis).
- **Inference output:** Raw, independent conviction scores (1.0 or 0.0) for every asset.
- **Note:** The raw sum of these signals might equal up to 13.0, representing total systemic conviction.

### 2. The Opportunity Gate (Phase 3)
A strict, binary filter. It calculates the portfolio-level conviction (sum of active signals / universe size).
- If Conviction < 0.20: The gate shuts and forces the portfolio into 100% Cash (Safety Mode).
- If Conviction >= 0.20: The gate opens and passes the raw signals forward.
- **Invariant:** The gate *never* multiplies weights. It is purely a 0 or 1 logical filter.

### 3. The Risk Engine (Phase 3)
A mathematical normalizer that strictly enforces the absolute portfolio leverage limit.
- If the sum of absolute active weights exceeds 1.0, the Risk Engine proportionally scales all allocations down so the exact sum equals `1.0000`.
- This guarantees the paper broker never attempts to buy assets on margin, permanently eradicating the legacy multi-million percent inflation bug.

## Current Calibration
Extended Walk-Forward Backtest (2018 - 2024):
- **Strategy Total Return**: +5,616.20% (CAGR: 91.97%)
- **BnH SPX Return**: +110.27%
- **Max Drawdown**: -16.19%
- **Sharpe Ratio**: 3.37

*For full walk-forward hit-rate details per asset, see `docs/model_calibration.md` and `reports/backtest_extended_results_v7.md`.*

## System Requirements
- Python 3.11+
- See `requirements.txt` (pandas, numpy, yfinance, scikit-learn, joblib, pytest).

## Running the Engine
```bash
# Run real-time inference and rebalance
PYTHONPATH=. python3 src/fetch_market_data.py
```

## Running Tests
```bash
# Mathematically verify the allocation invariant
PYTHONPATH=. pytest tests/test_allocation_invariant.py -v
```
