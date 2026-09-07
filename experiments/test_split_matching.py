
from decimal import Decimal
import datetime
import os
from orders import match_trades, add_expired_worthless_orders, apply_corporate_actions, load_adjustments

def test_vug_split_repro():
    print("Testing VUG split reproduction and fix with CSV...")
    
    # Create a temporary adjustments.csv
    with open("adjustments.csv", "w") as f:
        f.write("Ticker,Date,Ratio,StrikeAdj\n")
        f.write("VUG,2026-04-21,6,0\n")
    
    try:
        adjustments = load_adjustments("adjustments.csv")
        print(f"Loaded adjustments: {adjustments}")
        
        # Pre-split opening order (1 contract at $295)
        opens = [{
            "symbol": "VUG Jun 18 '26 $295 Put",
            "date": "01/10/2026",
            "epoch": int(datetime.datetime(2026, 1, 10).timestamp() * 1000),
            "action": "Sell Open",
            "quantity": 1,
            "price": Decimal("6.00"),
            "total_in": 600,
            "total_out": 0,
            "order_id": "18056"
        }]
        
        # Post-split closing order (6 contracts at $49.17)
        closes = [{
            "symbol": "VUG Jun 18 '26 $49.17 Put",
            "date": "05/15/2026",
            "epoch": int(datetime.datetime(2026, 5, 15).timestamp() * 1000),
            "action": "Buy Close",
            "quantity": 6,
            "price": Decimal("1.00"),
            "total_in": 0,
            "total_out": -600,
            "order_id": "20000"
        }]
        
        # Apply adjustment logic
        apply_corporate_actions(opens=opens, closes=closes, adjustments=adjustments)
        
        print(f"\nAdjusted Open Symbol: {opens[0]['symbol']}")
        print(f"Adjusted Open Quantity: {opens[0]['quantity']}")
        
        # Now match_trades should pair them
        matched = match_trades(opens, closes)
        
        print(f"\nMatched count with split logic: {len(matched)}")
        for i, m in enumerate(matched):
            print(f"Match {i}: Symbol={m['symbol']}, Open={bool(m['open'])}, Close={bool(m['close'])}")
            if m['open'] and m['close']:
                o = m['open']
                c = m['close']
                print(f"  Matched Quantity: {o['quantity']}")
                print(f"  P/L: {Decimal(str(o['total_in'])) + Decimal(str(o['total_out'])) + Decimal(str(c['total_in'])) + Decimal(str(c['total_out']))}")

        is_matched = any(m['open'] and m['close'] for m in matched)
        if is_matched:
            print("\nSUCCESS: Trades matched correctly after split logic.")
        else:
            print("\nFAILURE: Trades still failed to match.")
    finally:
        if os.path.exists("adjustments.csv"):
            os.remove("adjustments.csv")

if __name__ == "__main__":
    test_vug_split_repro()
