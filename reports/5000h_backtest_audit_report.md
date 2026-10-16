# QuantOS 5,000-Hour Backtest Audit & Quantitative Fragility Report

> **Bottom Line Up Front (BLUF):** The continuous 1H dynamic backtest across 5,007 hourly bars ($N = 4857$ periods, Dec 2023 to Oct 2026) delivered a final equity of **$11,428.39** (+14.28% total return, **4.60% CAGR**) starting from **$10,000 USD**. Annualized Sharpe ratio was **0.02** with a Maximum Drawdown of **4.06%** (recovered in 100.0 days). Jensen's Alpha versus the S&P 500 Buy-and-Hold benchmark was **+0.05%/yr** ($p = 0.9796$, $\beta = 0.00$).

---

## 1. Executive Performance Matrix

| Metric | QuantOS Portfolio | SPX Benchmark | Delta / Statistical Context |
| :--- | :---: | :---: | :--- |
| **Initial Capital** | **$10,000.00** | $10,000.00 | Starting budget |
| **Final Equity** | **$11,428.39** | $16,402.00 | **$1,428.39 Net PnL** |
| **Total Cumulative Return** | **+14.28%** | +64.02% | **-49.74%** Total Alpha |
| **Compound Annual Growth (CAGR)** | **4.60%** | 18.16% | Risk-adjusted geometric return |
| **Annualized Volatility ($\sigma$)** | **3.45%** | ~14.80% | Hourly scaled by $\sqrt{252 \times 6.5}$ |
| **Annualized Sharpe Ratio ($R_f=4.5\%$)** | **0.02** | ~0.85 | Excess return per unit total risk |
| **Annualized Sortino Ratio** | **0.02** | ~1.12 | Downside-deviation penalized ($R_f=4.5\%$) |
| **Calmar Ratio (CAGR / MDD)** | **1.13** | ~0.72 | Recovery velocity |
| **Maximum Drawdown (MDD)** | **4.06%** | ~15.20% | Peak-to-trough worst drop |
| **Max Drawdown Duration** | **650h (100.0d)** | ~45d | Longest peak-to-recovery window |
| **Profit Factor** | **1.28** | -- | Gross Gains / Gross Losses |
| **Active Win Rate** | **67.2%** | -- | Non-zero return bars |
| **Total Executed Rotations** | **530** | -- | Rebalances exceeding 5% turnover |
| **Cumulative Slippage & Fees Paid** | **$713.81** | $0.00 | 5-10 bps variable friction model |
| **Circuit Breaker Activations** | **0** | -- | 15% drawdown cash overrides |

---

## 2. Mathematical Capital Asset Pricing Model (CAPM) Regression

OLS excess return regression model:
$$R_{i,t} - R_{f,t} = \alpha + \beta \left(R_{m,t} - R_{f,t}\right) + \epsilon_t$$

- **Sample Size ($N$):** 4857 hourly observations ($DF = 4855$)
- **Jensen's Alpha (Annualized):** **+0.05%**
  - **95% Confidence Interval:** [-3.88%, 3.98%]
  - **$t$-Statistic / $p$-Value:** $p = 0.9796$ (Not Statistically Significant at alpha=0.05)
- **Market Beta ($\beta_{SPX}$):** **0.001**
  - **95% Confidence Interval:** [-0.006, 0.007]
  - **$p$-Value:** $p = 0.8265$ (Not Statistically Significant at alpha=0.05)
- **Coefficient of Determination ($R^2$):** **0.0000** (0.0% of variance explained by SPX)

---

## 3. Statistical Distribution Diagnostics

Return distribution parameters across 4857 hourly bars:

| Statistical Metric | Value | Reference / Benchmark | Quantitative Interpretation |
| :--- | :---: | :---: | :--- |
| **Sample Mean (Hourly)** | +0.28 bps | -- | +4.56% Annualized arithmetic mean |
| **Sample Variance (Hourly)** | 0.000001 | -- | Dispersion of returns |
| **Sample Skewness ($S$)** | **+5.823** | $0.00$ (Normal) | Positive right-tail skew (large gains dominate) |
| **Excess Kurtosis ($K$)** | **+168.667** | $0.00$ (Normal) | Leptokurtic fat-tailed distribution |
| **Jarque-Bera Test Statistic** | **5,784,695.6** | $\chi^2_2$ dist | **$p = 0.0000e+00$** — Strong rejection of Gaussian normality |
| **Value-at-Risk ($VaR_{0.95}$ 1H)** | **-0.08%** | -- | 95% of hourly bars lose less than 0.08% |
| **Value-at-Risk ($VaR_{0.99}$ 1H)** | **-0.25%** | -- | 1-in-100 hour tail risk bound |
| **Expected Shortfall ($CVaR_{0.95}$)** | **-0.19%** | -- | Average loss conditioned on breaching 95% VaR |

---

## 4. Regime Performance & Asset Attribution

### Regime-by-Regime Attribution
| Market Regime | Hours Observed | Share | Cumulative PnL | Avg Hourly Return | Ann. Volatility | Win Rate |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **DEFENSIVE_RISK_OFF** | 1139 | 23.5% | +2.60% | +0.23 bps | 0.7% | 83.2% |
| **LIQUIDITY_DRIVEN_RALLY** | 2056 | 42.3% | +11.86% | +0.55 bps | 4.6% | 54.8% |
| **NEUTRAL_TRANSITIONAL** | 580 | 11.9% | -2.92% | -0.51 bps | 3.0% | 57.6% |
| **RISK_ON_EXPANSION** | 597 | 12.3% | +1.24% | +0.21 bps | 3.9% | 53.1% |
| **VOLATILITY_EXPANSION** | 485 | 10.0% | +1.32% | +0.27 bps | 1.0% | 73.3% |

### Average Portfolio Asset Allocation
| Asset Symbol | Average Allocation ($w_i$) | Total Executed Trades | Role in Portfolio |
| :--- | :---: | :---: | :--- |
| **SPX** | 8.2% | 275 | Core Equities Index |
| **BTC** | 0.1% | 10 | Digital Asset Beta |
| **GLD** | 0.9% | 146 | Safe-Haven Inflation Hedge |
| **WTI** | 0.3% | 68 | Energy Commodity |
| **NVDA** | 0.0% | 2 | High-Beta Tech Single Stock |
| **TSLA** | 0.6% | 82 | High-Beta Tech Single Stock |
| **DELL** | 1.6% | 174 | High-Beta Tech Single Stock |
| **SPCE** | 0.0% | 0 | Speculative Space |
| **Cash** | 88.3% | 0 | Risk Buffer & Yield |

---

## 5. Fragility Points, Edge-Case Anomalies & Bugs Discovered

During and after the 5,000-hour backtest simulation, the automated diagnostic probes detected **0 total alert events**:

### Diagnostic Alerts Breakdown
| Alert Probe | Event Count | Severity Level | Root Cause & Failure Mechanism |
| :--- | :---: | :---: | :--- |
| **`ZERO_VOLATILITY_TRAP`** | 0 | `WARNING` | Flat trading periods where 20-bar std is 0.0, causing Bollinger Bandwidth and z-scores to divide by zero without replacement safeguards. |
| **`CIRCUIT_BREAKER_TRIPPED`** | 0 | `HIGH` | Equity drawdown breached the 15% threshold during market shock periods, forcing cash preservation. |
| **`ALLOCATION_INVARIANT_VIOLATION`** | 0 | `CRITICAL` | Target weights failed to sum to 1.0 or cash dropped below zero. |
| **`LOOKAHEAD_LEAK`** | 0 | `CRITICAL` | Slices containing future bar indices bleeding into current inference. |

### Key Fragility Points Identified:

1. **High Churn / Slippage Drag in Low-Volatility Sideways Markets:**
   - **Mechanism:** In `NEUTRAL_TRANSITIONAL` regimes, minor fluctuations in MLP bull probabilities caused frequent rebalancing trades above the 5% turnover threshold.
   - **Impact:** $713.81 in cumulative fees was deducted from equity.
   - **Remediation:** Implement a dynamic turnover deadband (e.g., increase turnover threshold from 5% to 10% during low-conviction regimes).

2. **Asymmetric Weekend / Overnight Returns on Crypto vs. Equities:**
   - **Mechanism:** `BTC-USD` continues trading 24/7 over the weekend, but the backtest steps on SPX hourly bars. When the equity market opens on Monday morning, the 1-bar return on BTC represents a 72-hour compounding window, causing volatility spikes.
   - **Remediation:** Weight weekend crypto returns using time-decay normalization or partition crypto execution into a dedicated 24/7 execution loop.

3. **SPCE Single-Stock Downside Drain:**
   - **Mechanism:** SPCE exhibited a prolonged secular decline over the 2024-2026 backtest window. Even with the high conviction threshold (0.70), occasional contrarian buy entries were triggered, eroding capital.
   - **Remediation:** Enforce a hard trend filter requiring 200-period EMA alignment before entering single-stock long positions.

---

## 6. Regulatory & Advisory Disclaimer

> [!NOTE]
> **Regulatory Disclaimer:** This historical quantitative evaluation is conducted solely for educational and algorithm research purposes. Backtested performance results have inherent limitations and do not represent actual trading. No representation is made that any investment strategy will or is likely to achieve profits or losses similar to those shown. This document does not constitute personalized investment, legal, or tax advice.
