
from decimal import Decimal
import datetime
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())
from orders import load_adjustments, apply_corporate_actions, match_trades

def test_tlry_adjustment_repro():
    print("Testing TLRY reverse split reproduction...")
    
    adj_file = "test_adjustments.csv"
    # Ticker,Date,Ratio,StrikeAdj,NewTicker
    # 1:10 reverse split. Strike stays same. Symbol becomes TLRY1.
    with open(adj_file, "w") as f:
        f.write("Ticker,Date,Ratio,StrikeAdj,NewTicker\n")
        f.write("TLRY,2025-12-02,0.1,0,TLRY1\n")
        
    try:
        # 1. Test parsing
        # Note: Need to update load_adjustments to support 5th column first!
        # For now, let's see what happens if we just run it.
        adjustments = load_adjustments(adj_file)
        print(f"Loaded adjustments: {adjustments}")
        
        # 2. Test application to pre-split leg
        opens = [{
            "symbol": "TLRY Jan 16 '26 $2 Call",
            "date": "11/01/2025", # Before split
            "epoch": int(datetime.datetime(2025, 11, 1).timestamp() * 1000),
            "action": "Sell Open",
            "quantity": 1,
            "price": Decimal("0.50"),
            "total_in": 50, # 0.50 * 100 * 1
            "total_out": 0,
            "order_id": "4001"
        }]
        
        # Post-split leg (e.g. actual close or synthetic)
        # We'll use a price of $1.00 to verify the multiplier correction
        closes = [{
            "symbol": "TLRY1 Jan 16 '26 $2 Call",
            "date": "01/16/2026", # After split
            "epoch": int(datetime.datetime(2026, 1, 16).timestamp() * 1000),
            "action": "Buy Close",
            "quantity": 1,
            "price": Decimal("1.00"),
            "total_in": 0,
            "total_out": -100, # 1.00 * 100 * 1 (Incorrectly calculated by fetch_executed_orders)
            "order_id": "4002"
        }]
        
        apply_corporate_actions(opens=opens, closes=closes, adjustments=adjustments)
        
        print(f"Adjusted Open Symbol: '{opens[0]['symbol']}'")
        print(f"Adjusted Open Qty: {opens[0]['quantity']}")
        # I want to see what happened inside, but I can't easily.
        # I'll just trust the symbol output for now.
        print(f"Adjusted Close Symbol: '{closes[0]['symbol']}'")
        print(f"Adjusted Close total_out: {closes[0]['total_out']}")
        
        # 3. Test matching
        matched = match_trades(opens, closes)
        print(f"Matched result count: {len(matched)}")
        for m in matched:
            print(f"  Match: open={m['open']['symbol'] if m['open'] else 'None'}, close={m['close']['symbol'] if m['close'] else 'None'}")
        
        is_matched = any(m['open'] and m['close'] for m in matched)
        print(f"Matched: {is_matched}")
        
        assert is_matched
        assert opens[0]['symbol'] == "TLRY1 Jan 16 '26 $2 Call"
        assert opens[0]['quantity'] == 1 # Stays 1 for non-standard
        assert closes[0]['total_out'] == -10 # 100 * 0.1 = 10
        print("SUCCESS: TLRY non-standard adjustment handled correctly.")
        
    finally:
        if os.path.exists(adj_file):
            os.remove(adj_file)

if __name__ == "__main__":
    test_tlry_adjustment_repro()
