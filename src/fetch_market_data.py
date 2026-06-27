import argparse
import os
import datetime
import pandas as pd
import yfinance as yf

from src.observability.logger import get_logger
from src.observability.event_bus import EventBus
from src.data_lake.lake_manager import LakeManager
from src.adapters.paper_broker import PaperBroker
from config.symbols import UNIVERSE
from src.signals.ml_signal import signal
from src.allocation.opportunity_gate import gate_signals
from src.allocation.risk_engine import normalize_weights

logger = get_logger("conductor")

class Conductor:
    def __init__(self, interval="1d", use_1h_context=False):
        self.interval = interval
        logger.info("Initializing Phase 3 Live Conductor (ML + Gate + Risk Engine)")
        self.lake_manager = LakeManager()
        self.event_bus = EventBus()
        self.event_bus.set_interceptor(self.lake_manager.log_event)
        self.paper_broker = PaperBroker(os.path.join(os.path.dirname(__file__), "..", "data"))

    def run(self):
        logger.info("Fetching recent history for ML inference...")
        
        # We need roughly ~300 days of history to compute 200 SMA and 252-day highs
        ticker_map = {
            "SPX": "^GSPC", "NDX": "^NDX", "RUT": "^RUT", "VIX": "^VIX", "VIX3M": "^VIX3M",
            "BTC-PERP": "BTC-USD", "ETH-PERP": "ETH-USD", "DAX": "^GDAXI", "Nikkei": "^N225",
            "TY": "ZN=F", "CL": "CL=F", "GC": "GC=F", "UB": "ZB=F", "EURUSD=X": "EURUSD=X"
        }
        
        fetch_list = list(set([ticker_map.get(a, a) for a in UNIVERSE] + ["^GSPC", "^VIX", "^VIX3M", "BTC-USD"]))
        raw = yf.download(fetch_list, period="2y", interval="1d", group_by="ticker", progress=False)
        
        history = {}
        current_prices = {}
        for asset in UNIVERSE + ["VIX3M"]:
            mapped = ticker_map.get(asset, asset)
            if mapped in raw.columns.levels[0]:
                df = pd.DataFrame({"close": raw[mapped]["Close"]}).dropna()
                if "PERP" in asset:
                    df["funding_rate"] = 0.0001 # Mock live funding rate
                history[asset] = df
                if not df.empty:
                    current_prices[asset] = float(df["close"].iloc[-1])
            else:
                history[asset] = pd.DataFrame()
                current_prices[asset] = 100.0 # Fallback
                
        bar = {"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "state": {}}
        
        # Step 1: ML Signal Generation
        raw_signals = signal(bar, history)
        logger.info(f"Raw ML Signals generated: {raw_signals}")
        
        # Step 2: Opportunity Gate
        gated_signals = gate_signals(raw_signals)
        
        # Step 3: Risk Engine (Normalization)
        target_allocation = normalize_weights(gated_signals)
        total_weight = sum(target_allocation.values())
        
        # Strict Invariant Check
        assert 0.0 <= total_weight <= 1.0001, f"Allocation invariant violated! Total Weight: {total_weight}"
        
        logger.info(f"Final Normalized Allocation: {target_allocation}")
        logger.info(f"Sum of Weights: {total_weight:.4f}")
        
        # Step 4: Execute via PaperBroker
        # Mock VIX Z-score for slippage scaling
        vix_zscore = 0.0 
        self.paper_broker.execute_rebalance(target_allocation, current_prices, vix_zscore=vix_zscore)
        
        logger.info("Pipeline execution completed successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=str, default="1d", choices=["1d", "1wk", "1h", "4h"])
    parser.add_argument("--use-1h-context", action="store_true")
    args = parser.parse_args()
    
    conductor = Conductor(interval=args.interval, use_1h_context=args.use_1h_context)
    conductor.run()
