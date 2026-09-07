
from decimal import Decimal
import datetime
import os
import sys

# Add current directory to path so we can import orders
sys.path.append(os.getcwd())
from orders import load_adjustments, apply_corporate_actions, match_trades

def test_fractional_and_negative_ratios():
    print("Testing fractional and negative ratios...")
    
    adj_file = "test_adjustments.csv"
    with open(adj_file, "w") as f:
        f.write("Ticker,Date,Ratio,StrikeAdj\n")
        f.write("XYZ,2026-05-15,3:2,0\n")
        f.write("NEG,2026-06-01,-1,0\n")
        
    try:
        adjustments = load_adjustments(adj_file)
        print(f"Loaded adjustments: {adjustments}")
        
        # Test 3:2 split for XYZ
        xyz_adj = next(a for a in adjustments if a['ticker'] == 'XYZ')
        assert xyz_adj['ratio'] == Decimal("1.5")
        print("SUCCESS: 3:2 parsed as 1.5")
        
        # Test -1 ratio for NEG (if user really wanted it)
        neg_adj = next(a for a in adjustments if a['ticker'] == 'NEG')
        assert neg_adj['ratio'] == Decimal("-1")
        print("SUCCESS: -1 parsed as -1")
        
        # Verify application logic for XYZ
        opens = [{
            "symbol": "XYZ Jun 18 '26 $150 Call",
            "date": "05/01/2026",
            "epoch": int(datetime.datetime(2026, 5, 1).timestamp() * 1000),
            "action": "Buy Open",
            "quantity": 100,
            "price": Decimal("10.00"),
            "total_in": 0,
            "total_out": 1000,
            "order_id": "3001"
        }]
        
        apply_corporate_actions(opens=opens, adjustments=adjustments)
        
        print(f"Adjusted XYZ Quantity: {opens[0]['quantity']}")
        print(f"Adjusted XYZ Price: {opens[0]['price']}")
        print(f"Adjusted XYZ Symbol: {opens[0]['symbol']}")
        
        assert opens[0]['quantity'] == 150
        assert opens[0]['price'] == Decimal("10.00") / Decimal("1.5")
        assert "$100" in opens[0]['symbol'] # 150 / 1.5 = 100
        
        print("SUCCESS: Fractional split applied correctly.")
        
    finally:
        if os.path.exists(adj_file):
            os.remove(adj_file)

if __name__ == "__main__":
    test_fractional_and_negative_ratios()
