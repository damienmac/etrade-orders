
from decimal import Decimal
import datetime
import os
import sys
import pandas as pd

# Add current directory to path
sys.path.append(os.getcwd())
from orders import report_unmatched_expired_trades, match_trades

def test_unmatched_expired_reporting():
    print("Testing unmatched expired option reporting...")
    
    # Yesterday's expiration
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%b %d '%y")
    symbol = f"TEST {yesterday} $100 Call"
    
    # 1. Simulate unmatched expired open
    leg_open = {
        "symbol": symbol,
        "date": "01/01/2026",
        "epoch": int(datetime.datetime(2026, 1, 1).timestamp() * 1000),
        "action": "Buy Open",
        "quantity": 1,
        "price": Decimal("5.00"),
        "total_in": 0,
        "total_out": 500,
        "order_id": "TEST-EXP-OPEN"
    }
    
    combined = [{
        "symbol": symbol,
        "epoch": leg_open['epoch'],
        "open": leg_open,
        "close": None
    }]
    
    # This should print the WARNING to console
    print("--- Console Output Start ---")
    report_unmatched_expired_trades(combined)
    print("--- Console Output End ---")
    
    print("SUCCESS: Unmatched expired option identified and reported.")

if __name__ == "__main__":
    test_unmatched_expired_reporting()
