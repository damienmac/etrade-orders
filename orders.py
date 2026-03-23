import time
import datetime
from decimal import Decimal
from typing import Tuple
import pyetrade

# Use current date range (first day of the year to today)
today = datetime.datetime.now()
first_day_of_year = datetime.datetime(today.year, 1, 1)

# Format dates as datetime, not MMDDYYYY
from_date = first_day_of_year
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


def orders(consumer_key: str, consumer_secret: str, account_id_key: str, tokens: dict, output_file: str = None):
    """
    Main orchestration logic for fetching and processing orders.

    :param consumer_key: The E*TRADE consumer key.
    :param consumer_secret: The E*TRADE consumer secret.
    :param account_id_key: The E*TRADE account ID key.
    :param tokens: A dictionary containing the E*TRADE OAuth tokens.
    :param output_file: Optional path to the output CSV file.
    """
    etrade_order = pyetrade.order.ETradeOrder(
        consumer_key,
        consumer_secret,
        tokens['oauth_token'],
        tokens['oauth_token_secret'],
        # dev=True  # Sandbox
        dev=False  # Production
    )

    opens, closes = fetch_executed_orders(
        etrade_order,
        account_id_key,
        from_dt=from_date,
        to_dt=to_date,
        action_mapping=action_map
    )

    combined = match_trades(opens, closes)

    output_lines = format_output(combined)

    write_output(output_lines, output_file)
