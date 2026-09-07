
from decimal import Decimal
import datetime
import os
from orders import match_trades, apply_corporate_actions, load_adjustments

def test_tecl_adjustment_fix():
    print("Testing TECL adjustment fix...")
    
    # Case: TECL 12/10/2025 adjustment of $8.03759
    # $60.00 strike becomes $51.96
    
    # Create temporary adjustments.csv
    with open("adjustments.csv", "w") as f:
        f.write("Ticker,Date,Ratio,StrikeAdj\n")
        f.write("TECL,2025-12-10,1,8.03759\n")
        
    try:
        adjustments = load_adjustments("adjustments.csv")
        print(f"Loaded adjustments: {adjustments}")
        
        opens = [{
            "symbol": "TECL Jan 16 '26 $60 Put",
            "date": "11/01/2025",
            "epoch": int(datetime.datetime(2025, 11, 1).timestamp() * 1000),
            "action": "Sell Open",
            "quantity": 1,
            "price": Decimal("5.00"),
            "total_in": 500,
            "total_out": 0,
            "order_id": "1001"
        }]
        
        closes = [{
            "symbol": "TECL Jan 16 '26 $51.96 Put",
            "date": "01/16/2026",
            "epoch": int(datetime.datetime(2026, 1, 16).timestamp() * 1000),
            "action": "Buy Close",
            "quantity": 1,
            "price": Decimal("0.00"),
            "total_in": 0,
            "total_out": 0,
            "order_id": "1002"
        }]
        
        # Apply adjustment logic
        apply_corporate_actions(opens=opens, closes=closes, adjustments=adjustments)
        
        print(f"Adjusted Open Symbol: {opens[0]['symbol']}")
        
        # Now match_trades should pair them
        matched = match_trades(opens, closes)
        
        is_matched = any(m['open'] and m['close'] for m in matched)
        print(f"Matched with adjustment: {is_matched}")
        
        assert is_matched
        assert opens[0]['symbol'] == "TECL Jan 16 '26 $51.96 Put"
        print("SUCCESS: TECL adjustment handled correctly.")

    finally:
        if os.path.exists("adjustments.csv"):
            os.remove("adjustments.csv")

if __name__ == "__main__":
    test_tecl_adjustment_fix()
