import time
from decimal import Decimal
import os

import pyetrade
# import json
from properties import load_properties

# Try to import tokens from etrade_tokens.py
try:
    from etrade_tokens import tokens
    print("Using tokens from etrade_tokens.py")
except ImportError:
    print("Warning: etrade_tokens.py not found. Please run tokens.py first to generate tokens.")
    print("For now, using hardcoded tokens (these may be expired).")
    # Fallback to hardcoded tokens for backward compatibility
    tokens = {'oauth_token': 'niAK9kR9X8lggdBbkGgNvLz+GljdRtZwdqZsYEqBcpI=', 'oauth_token_secret': 'g/oW/d1Xi5YLGKWF8ly0LRSw3IEIkcytmy2tW0JyPgo='}

"""
from_date = The earliest date to include in the date range, formatted as MMDDYYYY
to_date = The latest date to include in the date range, formatted as MMDDYYYY
"""
# Use current date range (first day of the year to today)
import datetime

# Get current date
today = datetime.datetime.now()
# Get first day of the current year
first_day_of_year = datetime.datetime(today.year, 1, 1)

# Format dates as datetime, not MMDDYYYY
from_date = first_day_of_year
to_date = today

action_map = {
    "BUY_OPEN": "Buy Open",
    "BUY_CLOSE": "Buy Close",
    "SELL_OPEN": "Sell Open",
    "SELL_CLOSE": "Sell Close",
}


def orders():
    # For storing output
    output_lines = []

    try:
        # Get properties from the file
        properties = load_properties()
        if not properties:
            print("Error: Failed to load properties. Please check your etrade.properties file.")
            return

        consumer_key = properties.get('consumer_key')
        consumer_secret = properties.get('consumer_secret')
        output_file = properties.get('output_file')

        if not consumer_key or not consumer_secret:
            print("Error: Missing API credentials. Please check your etrade.properties file.")
            return

        # Setting up the object used for Accounts activity
        # Arg dev determines the environment Sandbox (dev=True)
        # or Live/Production (dev=False)
        etrade_accounts = pyetrade.ETradeAccounts(
            consumer_key,
            consumer_secret,
            tokens['oauth_token'],
            tokens['oauth_token_secret'],
            # dev=True  # Sandbox
            dev=False  # Production
        )
    except Exception as e:
        print(f"Error initializing E*TRADE API: {e}")
        return

    try:
        accounts_list = etrade_accounts.list_accounts(resp_format='json')
        # print(json.dumps(accounts_list, indent=4))

        accounts = accounts_list\
            .get("AccountListResponse", {})\
            .get("Accounts", {})\
            .get("Account", [])

        if not accounts:
            print("Error: No accounts found or unexpected API response format.")
            return

        # Get account ID from properties
        account_id = properties.get('account_id')
        if not account_id:
            print("Error: No account_id specified in etrade.properties file.")
            return

        # Find the account with the specified ID
        matching_accounts = [a for a in accounts if a.get("accountId") == account_id]
        if not matching_accounts:
            print(f"Error: Account with ID {account_id} not found. Available accounts:")
            for a in accounts:
                print(f"  - {a.get('accountId')}: {a.get('accountName')}")
            return

        account = matching_accounts[0]
        account_id_key = account.get("accountIdKey", "")
        if not account_id_key:
            print(f"Error: Could not retrieve accountIdKey for account {account_id}.")
            return
    except Exception as e:
        print(f"Error retrieving account information: {e}")
        return

    etrade_order = pyetrade.order.ETradeOrder(
        consumer_key,
        consumer_secret,
        tokens['oauth_token'],
        tokens['oauth_token_secret'],
        # dev=True  # Sandbox
        dev=False  # Production
    )

    opens = []
    closes = []
    done = False
    marker = 0
    while not done:
        order_response = (etrade_order.list_orders(account_id_key,
                                                  marker=marker,
                                                  count=100,
                                                  from_date=from_date,
                                                  to_date=to_date)
                          .get("OrdersResponse", {}))
        marker = order_response.get("marker")
        done = not bool(marker)
        for order in order_response.get("Order", []):
            for detail in order.get("OrderDetail", []):
                status = detail.get("status", "!NO STATUS")
                if status != "EXECUTED":
                    continue
                executed_time = detail.get("executedTime", "!NO EXECUTED TIME")
                # Convert to local time
                local_time = time.localtime(executed_time / 1_000)
                # Format the local time
                formatted_time = time.strftime("%m/%d/%Y", local_time)

                instruments = detail.get("Instrument", [])
                for instrument in instruments:
                    symbol = instrument.get("symbolDescription", "!NO SYMBOL")
                    action = instrument.get("orderAction", "!NO ACTION")
                    action = action_map.get(action, "!NO ACTION")
                    quantity = int(instrument.get("filledQuantity", "!NO QUANTITY"))
                    price = Decimal(str(instrument.get("averageExecutionPrice", "0.00")))
                    if "Buy" in action:
                        total_in = 0
                        total_out = (price * 100) * quantity * -1
                    else:
                        total_in = (price * 100) * quantity
                        total_out = 0
                    # print(f"{symbol},  {formatted_time}, {action},  {quantity},  {price}")
                    row = {
                        "symbol": symbol,
                        "date": formatted_time,
                        "epoch": executed_time,
                        "action": action,
                        "quantity": quantity,
                        "price": price,
                        "total_in": total_in,
                        "total_out": total_out,
                    }
                    if "Close" in action:
                        closes.append(row)
                        # print(f"CLOSES <-- {row}")
                    else:
                        opens.append(row)
                        # print(f"OPENS <-- {row}")

    # I want the oldest first
    closes.reverse()
    opens.reverse()

    combined = []
    for closing in closes:
        matched = False
        for opening in opens:
            if closing['symbol'] == opening['symbol']:
                match = {
                    "symbol": closing['symbol'],  # for sorting
                    "epoch": closing['epoch'],  # for sorting
                    "open": opening,
                    "close": closing
                }
                combined.append(match)
                # print(f"COMBINED1 <-- {match}")
                matched = True
                opens.remove(opening)
                break
        if not matched:
            match = {
                "symbol": closing['symbol'],
                "epoch": closing['epoch'],
                "open": None,
                "close": closing
            }
            combined.append(match)
            # print(f"COMBINED2 <-- {match}")

    # see what's left in opens that had no closes
    for opening in opens:
        match = {
            "symbol": opening['symbol'],
            "epoch": opening['epoch'],
            "open": opening,
            "close": None
        }
        combined.append(match)
        # print(f"COMBINED3 <-- {match}")

    puts = []
    for row in sorted(combined, key=lambda x: (x['symbol'], x['epoch'])):
        o = row['open']
        c = row['close']

        # trying to do puts, mostly short puts, in a separate block.
        if (o and 'Put' in o.get('symbol')) or (c and 'Put' in c.get('symbol')):
            puts.append(row)
        else:
            if o and c:
                output_lines.append(f"{o.get('symbol')},{o.get('date')},{o.get('action')},{o.get('quantity')},{o.get('price')},,{o.get('total_out')},{o.get('total_in')},,{c.get('date')},{c.get('action')},{c.get('quantity')},{c.get('price')},,{c.get('total_in')},{c.get('total_out')}")
            elif o and not c:
                output_lines.append(f"{o.get('symbol')},{o.get('date')},{o.get('action')},{o.get('quantity')},{o.get('price')},,{o.get('total_out')},{o.get('total_in')},,,,,,")
            elif not o and c:
                output_lines.append(f"{c.get('symbol')},,,,,,,,,{c.get('date')},{c.get('action')},{c.get('quantity')},{c.get('price')},,{c.get('total_in')},{c.get('total_out')}")
            else:
                assert False, f"Empty row? {row}"

    for row in sorted(puts, key=lambda x: (x['symbol'], x['epoch'])):
        o = row['open']
        c = row['close']
        if o and c:
            output_lines.append(f"{o.get('symbol')},{o.get('date')},{o.get('action')},{o.get('quantity')},{o.get('price')},,{o.get('total_out')},{o.get('total_in')},,{c.get('date')},{c.get('action')},{c.get('quantity')},{c.get('price')},,{c.get('total_in')},{c.get('total_out')}")
        elif o and not c:
            output_lines.append(f"{o.get('symbol')},{o.get('date')},{o.get('action')},{o.get('quantity')},{o.get('price')},,{o.get('total_out')},{o.get('total_in')},,,,,,")
        elif not o and c:
            output_lines.append(f"{c.get('symbol')},,,,,,,,,{c.get('date')},{c.get('action')},{c.get('quantity')},{c.get('price')},,{c.get('total_in')},{c.get('total_out')}")
        else:
            assert False, f"Empty row? {row}"

    # Add CSV header
    header = "Symbol,Open Date,Open Action,Open Quantity,Open Price,,Open Total Out,Open Total In,,Close Date,Close Action,Close Quantity,Close Price,,Close Total In,Close Total Out"
    output_lines.insert(0, header)

    # Output results
    if output_file:
        try:
            with open(output_file, 'w') as f:
                for line in output_lines:
                    f.write(line + '\n')
            print(f"Output saved to {output_file}")
        except Exception as e:
            print(f"Error writing to output file: {e}")
            # Fall back to console output
            for line in output_lines:
                print(line)
    else:
        # Print to console
        for line in output_lines:
            print(line)


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    orders()
