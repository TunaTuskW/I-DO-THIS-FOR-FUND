# I-DO-THIS-FOR-FUND Asset Universe

This document details the strictly enforced trading universe for Phase 2 multi-asset ML training and Phase 3 strategy allocation.

## Tier 1 (Core Universe)
These assets represent the core foundational edge and must successfully calibrate their models before the system can be deployed.

| Symbol | Asset Class | History Start | Liquidity | Data Source | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SPX** | US equity index | 1990-01-01 | Tier 1 | Yahoo (`^GSPC`) | Baseline |
| **NDX** | US equity index (Nasdaq) | 1990-01-01 | Tier 1 | Yahoo (`^NDX`) | High vol tech |
| **RUT** | US equity index (small cap) | 1990-01-01 | Tier 1 | Yahoo (`^RUT`) | Cycle sensitivity |
| **VIX** | Volatility index | 1990-01-01 | Tier 1 | Yahoo (`^VIX`) | Hedge/regime indicator |
| **BTC-PERP** | Crypto perp | 2018-01-01 | Tier 1 | Yahoo/Binance | Funding-rate alpha source |
| **ETH-PERP** | Crypto perp | 2018-01-01 | Tier 1 | Yahoo/Binance | Funding-rate alpha source |

## Tier 2 (Diversification)
International and commodity exposures added for decorrelation. Models are deployed if calibration passes.

| Symbol | Asset Class | History Start | Liquidity | Data Source | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **DAX** | EU equity index | 1990-01-01 | Tier 2 | Yahoo (`^GDAXI`) | Int. diversification |
| **Nikkei** | JP equity index | 1990-01-01 | Tier 2 | Yahoo (`^N225`) | Int. diversification |
| **TY** | US bond futures (10Y) | 2000-01-01 | Tier 2 | Yahoo (`ZN=F`) | Rates exposure |
| **CL** | Commodity (WTI) | 2000-01-01 | Tier 2 | Yahoo (`CL=F`) | Inflation hedge |
| **GC** | Commodity (Gold) | 2000-01-01 | Tier 2 | Yahoo (`GC=F`) | Risk-off hedge |

## Tier 3 (Exotic/Extremes)
Included for extreme macro regime detection.

| Symbol | Asset Class | History Start | Liquidity | Data Source | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **UB** | US bond futures (Long) | 2005-01-01 | Tier 3 | Yahoo (`ZB=F`) | Rates extreme |
| **EUR/USD** | FX | 2000-01-01 | Tier 3 | Yahoo (`EURUSD=X`) | USD regime |
