
from decimal import Decimal
import datetime
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())
from orders import load_adjustments, apply_corporate_actions, match_trades

def test_len_adjustment_repro():
    print("Testing LEN spin-off adjustment reproduction...")
    
    adj_file = "test_len_adjustments.csv"
    # Ticker,Date,Ratio,StrikeAdj,NewTicker
    # Spin-off on 2025-01-21. Symbol becomes LEN1.
    with open(adj_file, "w") as f:
        f.write("Ticker,Date,Ratio,StrikeAdj,NewTicker\n")
        f.write("LEN,2025-01-21,1,0,LEN1\n")
        
    try:
        adjustments = load_adjustments(adj_file)
        print(f"Loaded adjustments: {adjustments}")
        
        # 1. Pre-spin-off leg (Sell Open LEN)
        opens = [{
            "symbol": "LEN Feb 21 '25 $130 Put",
            "date": "12/15/2024", # Before spin-off
            "epoch": int(datetime.datetime(2024, 12, 15).timestamp() * 1000),
            "action": "Sell Open",
            "quantity": 1,
            "price": Decimal("5.00"),
            "total_in": 500,
            "total_out": 0,
            "order_id": "5001"
        }]
        
        # 2. Post-spin-off leg (Synthetic or actual close LEN1)
        closes = [{
            "symbol": "LEN1 Feb 21 '25 $130 Put",
            "date": "02/21/2025", # After spin-off
            "epoch": int(datetime.datetime(2025, 2, 21).timestamp() * 1000),
            "action": "Buy Close",
            "quantity": 1,
            "price": Decimal("0.00"),
            "total_in": 0,
            "total_out": 0,
            "order_id": "SYNTH-LEN1-20250221-Buy Close-1"
        }]
        
        print(f"Original Open Symbol: '{opens[0]['symbol']}'")
        
        apply_corporate_actions(opens=opens, closes=closes, adjustments=adjustments)
        
        print(f"Adjusted Open Symbol: '{opens[0]['symbol']}'")
        print(f"Adjusted Open Qty: {opens[0]['quantity']}")
        print(f"Adjusted Close Symbol: '{closes[0]['symbol']}'")
        
        # 3. Test matching
        matched = match_trades(opens, closes)
        print(f"Matched result count: {len(matched)}")
        
        is_matched = any(m['open'] and m['close'] for m in matched)
        print(f"Matched: {is_matched}")
        
        assert is_matched
        assert opens[0]['symbol'] == "LEN1 Feb 21 '25 $130 Put"
        assert opens[0]['quantity'] == 1
        
        print("SUCCESS: LEN spin-off adjustment handled correctly.")
        
    finally:
        if os.path.exists(adj_file):
            os.remove(adj_file)

if __name__ == "__main__":
    test_len_adjustment_repro()
