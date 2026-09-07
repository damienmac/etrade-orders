
from decimal import Decimal
import datetime
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())
from orders import load_adjustments, apply_corporate_actions, match_trades

def test_biti_multi_adjustments():
    print("Testing BITI multi-adjustment scenario...")
    
    adj_file = "test_biti_adjustments.csv"
    with open(adj_file, "w") as f:
        f.write("Ticker,Date,Ratio,StrikeAdj,NewTicker\n")
        f.write("BITI,2024-11-07,0.2,0,BITI1\n")
        f.write("BITI,2026-07-01,1,1.45,None\n")
        
    try:
        adjustments = load_adjustments(adj_file)
        print(f"Loaded adjustments: {adjustments}")
        
        # 1. Pre-split leg (Oct 2024)
        # Should be converted to BITI1 AND adjusted for July 2026 distribution
        leg1 = {
            "symbol": "BITI Dec 20 '24 $8 Call",
            "date": "10/15/2024",
            "epoch": int(datetime.datetime(2024, 10, 15).timestamp() * 1000),
            "action": "Sell Open",
            "quantity": 1,
            "price": Decimal("1.00"),
            "total_in": 100,
            "total_out": 0,
            "order_id": "BITI-PRE-SPLIT"
        }
        
        # 2. Post-split standard BITI (Jan 2026)
        # Should be adjusted for July 2026 distribution
        leg2 = {
            "symbol": "BITI Jan 16 '26 $10 Put",
            "date": "01/15/2026",
            "epoch": int(datetime.datetime(2026, 1, 15).timestamp() * 1000),
            "action": "Buy Open",
            "quantity": 1,
            "price": Decimal("2.00"),
            "total_in": 0,
            "total_out": -200,
            "order_id": "BITI-POST-SPLIT-STD"
        }
        
        # 3. Post-split BITI1 fresh order (July 2026)
        # Should have multiplier corrected (100 -> 20)
        leg3 = {
            "symbol": "BITI1 Dec 20 '24 $8 Call",
            "date": "07/15/2026",
            "epoch": int(datetime.datetime(2026, 7, 15).timestamp() * 1000),
            "action": "Buy Close",
            "quantity": 1,
            "price": Decimal("0.00"),
            "total_in": 0,
            "total_out": 0, # Worthless, but let's test a non-zero one too
            "order_id": "BITI1-FRESH"
        }
        
        leg4 = {
            "symbol": "BITI1 Jan 16 '26 $8 Call",
            "date": "07/20/2026",
            "epoch": int(datetime.datetime(2026, 7, 20).timestamp() * 1000),
            "action": "Sell Close",
            "quantity": 1,
            "price": Decimal("1.00"),
            "total_in": 100, # Raw from E*TRADE
            "total_out": 0,
            "order_id": "BITI1-FRESH-CORRECT-ME"
        }
        
        # 4. History BITI1 order (Already corrected)
        # Should NOT be corrected again
        leg5 = {
            "symbol": "BITI1 Jan 16 '26 $8 Call",
            "date": "07/20/2026",
            "epoch": int(datetime.datetime(2026, 7, 20).timestamp() * 1000),
            "action": "Sell Close",
            "quantity": 1,
            "price": Decimal("1.00"),
            "total_in": 20, # Already corrected in history!
            "total_out": 0,
            "order_id": "BITI1-HISTORY-NO-DOUBLE-CORRECT"
        }

        legs = [leg1, leg2, leg3, leg4, leg5]
        apply_corporate_actions(opens=legs, adjustments=adjustments)
        
        print(f"Leg 1 Symbol (Expected BITI1 ... $6.55): '{leg1['symbol']}'")
        # 8 - 1.45 = 6.55. Normalized = 6.55
        assert "BITI1" in leg1['symbol']
        assert "$6.55" in leg1['symbol']
        
        print(f"Leg 2 Symbol (Expected BITI ... $8.55): '{leg2['symbol']}'")
        # 10 - 1.45 = 8.55
        assert "BITI " in leg2['symbol']
        assert "$8.55" in leg2['symbol']
        
        print(f"Leg 4 Total In (Expected 20): {leg4['total_in']}")
        assert leg4['total_in'] == 20
        
        print(f"Leg 5 Total In (Expected 20, no double correct): {leg5['total_in']}")
        assert leg5['total_in'] == 20
        
        print("SUCCESS: BITI multi-adjustment scenario passed.")
        
    finally:
        if os.path.exists(adj_file):
            os.remove(adj_file)

if __name__ == "__main__":
    test_biti_multi_adjustments()
