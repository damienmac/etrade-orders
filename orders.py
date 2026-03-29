import time
import datetime
from decimal import Decimal
from typing import Tuple
import pyetrade
import pandas as pd

# Use current date range (two years ago to today)
today = datetime.datetime.now()
two_years_ago = today - datetime.timedelta(days=365*2)

# Format dates as datetime, not MMDDYYYY
from_date = two_years_ago
to_date = today

action_map = {
    "BUY_OPEN": "Buy Open",
    "BUY_CLOSE": "Buy Close",
    "SELL_OPEN": "Sell Open",
    "SELL_CLOSE": "Sell Close",
    "BUY": "Buy",
    "SELL": "Sell",
}

def fetch_executed_orders(etrade_order: pyetrade.order.ETradeOrder,
                          account_id_key: str,
                          from_dt: datetime.datetime,
                          to_dt: datetime.datetime,
                          action_mapping: dict) -> Tuple[list, list]:
    """
    Fetches EXECUTED orders from E*TRADE and separates them into opens and closes.

    :param etrade_order: The ETradeOrder API object.
    :param account_id_key: The account identifier key.
    :param from_dt: The earliest date to include in the date range.
    :param to_dt: The latest date to include in the date range.
    :param action_mapping: A dictionary mapping API actions to display actions.
    :return: A tuple containing (opens, closes) lists.
    """
    opens = []
    closes = []
    done = False
    marker = 0
    while not done:
        order_response = (etrade_order.list_orders(account_id_key,
                                                  marker=marker,
                                                  count=100,
                                                  from_date=from_dt,
                                                  to_date=to_dt)
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
                    action = action_mapping.get(action, "!NO ACTION")
                    quantity = int(instrument.get("filledQuantity", "!NO QUANTITY"))
                    price = Decimal(str(instrument.get("averageExecutionPrice", "0.00")))
                    if "Buy Open" == action:
                        total_in = 0
                        total_out = (price * 100) * quantity * -1
                    elif "Buy" == action:
                        total_in = 0
                        total_out = price * quantity * -1
                    elif "Sell" == action:
                        total_in = price * quantity
                        total_out = 0
                    else:  # Sell Close
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
                    if "Close" in action or "Sell" == action:
                        closes.append(row)
                        # print(f"CLOSES <-- {row}")
                    else:
                        opens.append(row)
                        # print(f"OPENS <-- {row}")
    return opens, closes


def parse_expiration_date(symbol: str) -> datetime.datetime:
    """Parses expiration date from a human-readable option symbol description."""
    try:
        if ' Call' not in symbol and ' Put' not in symbol:
            return None
        parts = symbol.split(' ')
        # Symbol example: "AAPL Apr 17 '25 $200 Call"
        # parts: ["AAPL", "Apr", "17", "'25", "$200", "Call"]
        if len(parts) < 4:
            return None
        # We assume the month and day are at indices 1 and 2, and year at index 3
        month_str = parts[1]
        day_str = parts[2]
        year_str = parts[3].strip("'")
        date_str = f"{month_str} {day_str} {year_str}"
        return datetime.datetime.strptime(date_str, "%b %d %y")
    except (ValueError, IndexError):
        return None


def add_expired_worthless_orders(opens: list, closes: list):
    """Adds synthetic closing orders for options that expired worthless."""
    now = datetime.datetime.now()
    
    # Track how many closes we already have for each symbol
    existing_closes_count = {}
    for c in closes:
        symbol = c['symbol']
        existing_closes_count[symbol] = existing_closes_count.get(symbol, 0) + 1
        
    # We want to add synthetic closes for any open that doesn't have a matching close
    # and has expired.
    
    # First, let's count the opens
    opens_count = {}
    for o in opens:
        symbol = o['symbol']
        opens_count[symbol] = opens_count.get(symbol, 0) + 1
        
    # Now, for each symbol, if opens > closes and it's an expired option, 
    # add (opens - closes) synthetic closes.
    for symbol, count in opens_count.items():
        exp_date = parse_expiration_date(symbol)
        if exp_date and exp_date < now:
            num_closes = existing_closes_count.get(symbol, 0)
            if count > num_closes:
                # Get list of opens for this symbol to iterate through
                matching_opens = [o for o in opens if o['symbol'] == symbol]
                
                # Check how many we need to create
                needed = count - num_closes
                # For simplicity, we can just pick the last ones (presumably the most recent)
                # or just any. Since we want to pair them, we should probably use the quantities
                # of the unmatched opens.
                
                # We'll create one synthetic close for each unmatched open
                # But wait, which ones are unmatched? 
                # Match_trades will find any.
                # Let's just create 'needed' synthetic closes using the quantities of some opens.
                for i in range(needed):
                    o_to_use = matching_opens[i]
                    action = o_to_use.get('action', '')
                    if action == "Buy Open":
                        close_action = "Sell Close"
                    elif action == "Sell Open":
                        close_action = "Buy Close"
                    else:
                        continue
                    
                    # E*Trade timestamps are in milliseconds.
                    epoch = int(exp_date.timestamp() * 1000)
                    
                    synthetic_close = {
                        "symbol": symbol,
                        "date": exp_date.strftime("%m/%d/%Y"),
                        "epoch": epoch,
                        "action": close_action,
                        "quantity": o_to_use.get('quantity'),
                        "price": Decimal("0.00"),
                        "total_in": 0,
                        "total_out": 0,
                        "is_expired": True,
                    }
                    closes.append(synthetic_close)


def match_trades(opens: list, closes: list) -> list:
    """
    Matches opening and closing trades by symbol.

    :param opens: List of opening trades.
    :param closes: List of closing trades.
    :return: A list of matched trade dictionaries.
    """
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
    return combined


def format_output(combined: list) -> list:
    """
    Formats the matched trades into CSV lines, separating puts into their own section.

    :param combined: List of matched trade dictionaries.
    :return: A list of formatted CSV strings.
    """
    output_lines = []
    
    # Add CSV header
    header = "Symbol,Open Date,Open Action,Open Quantity,Open Price,,Open Total Out,Open Total In,,Close Date,Close Action,Close Quantity,Close Price,,Close Total In,Close Total Out"
    output_lines.append(header)

    puts = []
    others = []
    
    for row in sorted(combined, key=lambda x: (x['symbol'], x['epoch'])):
        o = row['open']
        c = row['close']
        if (o and 'Put' in o.get('symbol')) or (c and 'Put' in c.get('symbol')):
            puts.append(row)
        else:
            others.append(row)

    def format_row(row):
        o = row['open']
        c = row['close']
        if o and c:
            return f"{o.get('symbol')},{o.get('date')},{o.get('action')},{o.get('quantity')},{o.get('price')},,{o.get('total_out')},{o.get('total_in')},,{c.get('date')},{c.get('action')},{c.get('quantity')},{c.get('price')},,{c.get('total_in')},{c.get('total_out')}"
        elif o and not c:
            return f"{o.get('symbol')},{o.get('date')},{o.get('action')},{o.get('quantity')},{o.get('price')},,{o.get('total_out')},{o.get('total_in')},,,,,,"
        elif not o and c:
            return f"{c.get('symbol')},,,,,,,,,{c.get('date')},{c.get('action')},{c.get('quantity')},{c.get('price')},,{c.get('total_in')},{c.get('total_out')}"
        else:
            assert False, f"Empty row? {row}"

    for row in others:
        output_lines.append(format_row(row))
        
    for row in puts:
        output_lines.append(format_row(row))
        
    return output_lines


def write_output(output_lines: list, output_file: str = None):
    """
    Writes the output lines to a file or the console.

    :param output_lines: List of formatted CSV strings.
    :param output_file: The path to the output file (optional).
    """
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


def write_excel_output(combined: list, output_file: str):
    """
    Writes the matched trades to an Excel file with data divided across multiple sheets.

    :param combined: List of matched trade dictionaries.
    :param output_file: The path to the output Excel file.
    """
    if not output_file:
        print("No output file specified for Excel output.")
        return

    # If the output file is still .csv, change it to .xlsx
    if output_file.lower().endswith('.csv'):
        output_file = output_file[:-4] + '.xlsx'

    rows = []
    for entry in sorted(combined, key=lambda x: (x['symbol'], x['epoch'])):
        o = entry['open']
        c = entry['close']
        
        # Determine if it's a "sold put"
        # A sold put is typically an opening transaction with "Sell Open" action and "Put" in symbol
        is_sold_put = False
        if o and 'Put' in o.get('symbol', '') and 'Sell Open' == o.get('action'):
            is_sold_put = True
        elif c and 'Put' in c.get('symbol', '') and not o:
            # If we only have a close, we might not know for sure if it was a sold put 
            # unless we look at the action. But the user defined "sold puts" as a category.
            # Usually SELL_OPEN is the indicator for sold puts.
            # For now, let's stick to the opening action if available.
            pass

        # Determine closing year
        close_year = None
        if c:
            # executed_time is in milliseconds
            close_time = datetime.datetime.fromtimestamp(c['epoch'] / 1000)
            close_year = close_time.year
        
        row_data = {
            "Symbol": (o or c).get('symbol'),
            "Open Date": o.get('date') if o else None,
            "Open Action": o.get('action') if o else None,
            "Open Quantity": o.get('quantity') if o else None,
            "Open Price": float(o.get('price')) if o else None,
            "Open Total Out": float(o.get('total_out')) if o else None,
            "Open Total In": float(o.get('total_in')) if o else None,
            "Close Date": c.get('date') if c else None,
            "Close Action": c.get('action') if c else None,
            "Close Quantity": c.get('quantity') if c else None,
            "Close Price": float(c.get('price')) if c else None,
            "Close Total In": float(c.get('total_in')) if c else None,
            "Close Total Out": float(c.get('total_out')) if c else None,
            "EXPIRED": "EXPIRED" if c and c.get('is_expired') else "",
            "_is_sold_put": is_sold_put,
            "_close_year": close_year
        }
        rows.append(row_data)

    df = pd.DataFrame(rows)
    
    this_year = datetime.datetime.now().year
    year_minus_1 = this_year - 1
    year_minus_2 = this_year - 2

    # Partitioning logic
    # sheet1: not sold puts, closed in year_minus_2
    sheet1 = df[(~df['_is_sold_put']) & (df['_close_year'] == year_minus_2)]
    
    # sheet2: sold puts, closed in year_minus_2
    sheet2 = df[(df['_is_sold_put']) & (df['_close_year'] == year_minus_2)]
    
    # sheet3: not sold puts, closed in year_minus_1
    sheet3 = df[(~df['_is_sold_put']) & (df['_close_year'] == year_minus_1)]
    
    # sheet4: sold puts, closed in year_minus_1
    sheet4 = df[(df['_is_sold_put']) & (df['_close_year'] == year_minus_1)]
    
    # sheet5: not sold puts, closed this year OR not closed
    sheet5 = df[(~df['_is_sold_put']) & ((df['_close_year'] == this_year) | (df['_close_year'].isna()))]
    
    # sheet6: sold puts, closed this year OR not closed
    sheet6 = df[(df['_is_sold_put']) & ((df['_close_year'] == this_year) | (df['_close_year'].isna()))]

    # Remove helper columns before writing
    cols_to_drop = ['_is_sold_put', '_close_year']
    
    # Dashboard calculations
    def calculate_summary(df_partition, name):
        # P/L = (Open Total In + Open Total Out) + (Close Total In + Close Total Out)
        # Note: Open Total Out is negative for buys, Close Total In is positive for sells, etc.
        # Summing them all up gives the net P/L.
        pl = (df_partition['Open Total Out'].fillna(0) + 
              df_partition['Open Total In'].fillna(0) + 
              df_partition['Close Total In'].fillna(0) + 
              df_partition['Close Total Out'].fillna(0)).sum()
        
        count = len(df_partition)
        
        # Win rate: only for closed trades (where Close Date is not null)
        closed_trades = df_partition[df_partition['Close Date'].notna()]
        if len(closed_trades) > 0:
            trade_pls = (closed_trades['Open Total Out'].fillna(0) + 
                         closed_trades['Open Total In'].fillna(0) + 
                         closed_trades['Close Total In'].fillna(0) + 
                         closed_trades['Close Total Out'].fillna(0))
            wins = (trade_pls > 0).sum()
            win_rate = f"{(wins / len(closed_trades)) * 100:.2f}%"
        else:
            win_rate = "N/A"
            
        return {
            "Category": name,
            "Total Trades": count,
            "Closed Trades": len(closed_trades),
            "Total P/L": round(pl, 2),
            "Win Rate (Closed)": win_rate
        }

    summary_data = [
        calculate_summary(sheet1, f"Trades {year_minus_2}"),
        calculate_summary(sheet2, f"Short Puts {year_minus_2}"),
        calculate_summary(sheet3, f"Trades {year_minus_1}"),
        calculate_summary(sheet4, f"Short Puts {year_minus_1}"),
        calculate_summary(sheet5, "Trades Current or Open"),
        calculate_summary(sheet6, "Short Puts Current or Open"),
    ]
    dashboard_df = pd.DataFrame(summary_data)

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        dashboard_df.to_excel(writer, sheet_name='Dashboard', index=False)
        sheet1.drop(columns=cols_to_drop).to_excel(writer, sheet_name=f'Trades {year_minus_2}', index=False)
        sheet2.drop(columns=cols_to_drop).to_excel(writer, sheet_name=f'Short Puts {year_minus_2}', index=False)
        sheet3.drop(columns=cols_to_drop).to_excel(writer, sheet_name=f'Trades {year_minus_1}', index=False)
        sheet4.drop(columns=cols_to_drop).to_excel(writer, sheet_name=f'Short Puts {year_minus_1}', index=False)
        sheet5.drop(columns=cols_to_drop).to_excel(writer, sheet_name='Trades Current or Open', index=False)
        sheet6.drop(columns=cols_to_drop).to_excel(writer, sheet_name='Short Puts Current or Open', index=False)

    print(f"Excel output saved to {output_file}")


def orders(consumer_key: str, consumer_secret: str, account_id_key: str, tokens: dict, output_file: str = None):
    """
    Main orchestration logic for fetching and processing orders.

    :param consumer_key: The E*TRADE consumer key.
    :param consumer_secret: The E*TRADE consumer secret.
    :param account_id_key: The E*TRADE account ID key.
    :param tokens: A dictionary containing the E*TRADE OAuth tokens.
    :param output_file: Optional path to the output file.
    """
    etrade_order = pyetrade.order.ETradeOrder(
        consumer_key,
        consumer_secret,
        tokens['oauth_token'],
        tokens['oauth_token_secret'],
        # dev=True  # Sandbox
        dev=False  # Production
    )

    try:
        opens, closes = fetch_executed_orders(
            etrade_order,
            account_id_key,
            from_dt=from_date,
            to_dt=to_date,
            action_mapping=action_map
        )
    except Exception as e:
        if "401" in str(e):
            print("\nError: E*TRADE API authentication failed (401 Unauthorized) while fetching orders.")
            print("Your OAuth tokens have likely expired. Please run 'python tokens.py' to generate new tokens.")
        else:
            print(f"Error fetching orders from E*TRADE: {e}")
        return

    add_expired_worthless_orders(opens, closes)

    combined = match_trades(opens, closes)

    write_excel_output(combined, output_file)
