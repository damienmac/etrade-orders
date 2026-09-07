import time
import datetime
import os
import re
import logging
import copy
from collections import defaultdict, deque
from decimal import Decimal
from typing import Tuple
import pyetrade
import pandas as pd


logger = logging.getLogger(__name__)

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
            order_id = order.get("orderId", "!NO ORDER ID")
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
                    if action in {"Buy Open", "Buy Close"}:
                        total_in = 0
                        total_out = (price * 100) * quantity * -1
                    elif action == "Buy":
                        total_in = 0
                        total_out = price * quantity * -1
                    elif action in {"Sell Open", "Sell Close"}:
                        total_in = (price * 100) * quantity
                        total_out = 0
                    elif action == "Sell":
                        total_in = price * quantity
                        total_out = 0
                    else:
                        total_in = 0
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
                        "order_id": order_id,
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


def parse_option_details(symbol: str) -> dict:
    """Parses key details from a human-readable option symbol description."""
    if not symbol:
        return None

    match = re.match(
        r"^(?P<ticker>[A-Z][A-Z0-9\.\-]*)\s+[A-Za-z]{3}\s+\d{1,2}\s+'?\d{2}\s+\$(?P<strike>\d+(?:\.\d+)?)\s+(?P<option_type>Call|Put)\b",
        symbol
    )
    if not match:
        return None

    try:
        strike = Decimal(match.group("strike"))
    except Exception:
        return None

    return {
        "ticker": match.group("ticker"),
        "strike": strike,
        "option_type": match.group("option_type")
    }


def parse_mmddyyyy(date_str: str):
    if not date_str:
        return None
    try:
        if isinstance(date_str, datetime.datetime):
            return date_str.date()
        if isinstance(date_str, datetime.date):
            return date_str
        value = str(date_str).strip()
        if ' ' in value:
            value = value.split(' ')[0]

        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(value, fmt).date()
            except Exception:
                pass

        return datetime.date.fromisoformat(value)
    except Exception:
        return None


def get_leg_date(leg: dict):
    if not leg:
        return None

    parsed_date = parse_mmddyyyy(leg.get("date"))
    if parsed_date:
        return parsed_date

    epoch = leg.get("epoch")
    if epoch is None:
        return None

    try:
        epoch_int = int(epoch)
        if epoch_int > 10 ** 11:
            epoch_int = epoch_int / 1000
        return datetime.datetime.fromtimestamp(epoch_int).date()
    except Exception:
        return None


def close_on_or_after_option_expiration(option_symbol: str, close_leg: dict) -> bool:
    expiration_dt = parse_expiration_date(option_symbol)
    close_date = get_leg_date(close_leg)
    if not expiration_dt or not close_date:
        return False
    return close_date >= expiration_dt.date()


def leg_sort_value_ms(leg: dict) -> int:
    if not leg:
        return -1
    epoch = leg.get("epoch")
    if epoch is not None:
        try:
            return int(epoch)
        except Exception:
            pass

    parsed_date = parse_mmddyyyy(leg.get("date"))
    if parsed_date:
        return int(datetime.datetime(parsed_date.year, parsed_date.month, parsed_date.day).timestamp() * 1000)
    return -1


def leg_distance_ms(first_leg: dict, second_leg: dict) -> int:
    first_ms = leg_sort_value_ms(first_leg)
    second_ms = leg_sort_value_ms(second_leg)
    if first_ms < 0 or second_ms < 0:
        return 10 ** 18
    return abs(first_ms - second_ms)


def ticker_hint_matches(stock_symbol: str, ticker: str) -> bool:
    if not stock_symbol or not ticker:
        return False

    stock_symbol_upper = stock_symbol.upper()
    ticker_upper = ticker.upper()
    if f"({ticker_upper})" in stock_symbol_upper:
        return True

    tokens = re.findall(r"[A-Z]+", stock_symbol_upper)
    return ticker_upper in tokens


def link_short_put_assignments(combined: list) -> dict:
    """
    Links short-put assignment candidates to related stock buy/sell legs.

    Returns a mapping by combined-entry index:
    {
        put_entry_idx: {
            "status": "ASSIGNED_LINKED"|"ASSIGNED_AMBIGUOUS"|"ASSIGNED_UNRESOLVED",
            "buy_entry_idx": int|None,
            "sell_legs": [close_leg, ...]
        }
    }
    """
    assignment_links = {}
    used_buy_entry_indices = set()
    used_close_only_sell_entry_indices = set()

    stock_buy_entries = []
    close_only_stock_sell_entries = []

    for idx, entry in enumerate(combined):
        symbol = entry.get("symbol", "")
        if " Put" in symbol or " Call" in symbol:
            continue

        opening = entry.get("open")
        closing = entry.get("close")

        if opening and opening.get("action") == "Buy":
            stock_buy_entries.append((idx, entry))

        if (not opening) and closing and closing.get("action") == "Sell":
            close_only_stock_sell_entries.append((idx, entry))

    seven_days_ms = 7 * 24 * 60 * 60 * 1000
    six_hours_ms = 6 * 60 * 60 * 1000
    one_day_ms = 24 * 60 * 60 * 1000
    three_days_ms = 3 * one_day_ms

    for put_idx, put_entry in enumerate(combined):
        opening = put_entry.get("open")
        closing = put_entry.get("close")

        if not opening or not closing:
            continue
        if opening.get("action") != "Sell Open":
            continue
        if " Put" not in opening.get("symbol", ""):
            continue
        if closing.get("action") != "Buy Close":
            continue
        if closing.get("is_expired"):
            continue

        close_price = closing.get("price")
        if close_price is None:
            continue

        try:
            close_price_decimal = Decimal(str(close_price))
        except Exception:
            continue

        if close_price_decimal != Decimal("0.00"):
            continue

        likely_expired_close = close_on_or_after_option_expiration(opening.get("symbol", ""), closing)

        option_details = parse_option_details(opening.get("symbol", ""))
        expected_share_qty = int(opening.get("quantity", 0)) * 100

        if not option_details or expected_share_qty <= 0:
            if likely_expired_close:
                continue
            assignment_links[put_idx] = {
                "status": "ASSIGNED_UNRESOLVED",
                "buy_entry_idx": None,
                "sell_legs": []
            }
            continue

        strike = option_details["strike"]
        ticker = option_details["ticker"]

        candidates = []
        for buy_idx, buy_entry in stock_buy_entries:
            if buy_idx in used_buy_entry_indices:
                continue

            buy_open = buy_entry.get("open")
            if not buy_open:
                continue

            if int(buy_open.get("quantity", 0)) != expected_share_qty:
                continue

            buy_price = buy_open.get("price")
            if buy_price is None or abs(Decimal(str(buy_price)) - strike) > Decimal("0.01"):
                continue

            distance_ms = leg_distance_ms(closing, buy_open)
            if distance_ms > seven_days_ms:
                continue

            score = 0
            if distance_ms <= six_hours_ms:
                score += 4
            elif distance_ms <= one_day_ms:
                score += 3
            elif distance_ms <= three_days_ms:
                score += 2
            else:
                score += 1

            if ticker_hint_matches(buy_open.get("symbol", buy_entry.get("symbol", "")), ticker):
                score += 2

            candidates.append((score, distance_ms, buy_idx))

        if not candidates:
            if likely_expired_close:
                continue
            assignment_links[put_idx] = {
                "status": "ASSIGNED_UNRESOLVED",
                "buy_entry_idx": None,
                "sell_legs": []
            }
            continue

        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        best = candidates[0]

        if len(candidates) > 1 and candidates[1][0] == best[0] and candidates[1][1] == best[1]:
            assignment_links[put_idx] = {
                "status": "ASSIGNED_AMBIGUOUS",
                "buy_entry_idx": None,
                "sell_legs": []
            }
            continue

        linked_buy_idx = best[2]
        linked_buy_entry = combined[linked_buy_idx]
        used_buy_entry_indices.add(linked_buy_idx)

        linked_sell_legs = []
        linked_buy_close = linked_buy_entry.get("close")
        matched_sell_qty = 0

        if linked_buy_close and linked_buy_close.get("action") == "Sell":
            linked_sell_legs.append(linked_buy_close)
            matched_sell_qty += int(linked_buy_close.get("quantity", 0) or 0)

        remaining_qty = expected_share_qty - matched_sell_qty
        if remaining_qty > 0:
            buy_symbol = linked_buy_entry.get("symbol")
            buy_open_ms = leg_sort_value_ms(linked_buy_entry.get("open"))

            additional_candidates = []
            for sell_idx, sell_entry in close_only_stock_sell_entries:
                if sell_idx in used_close_only_sell_entry_indices:
                    continue
                if sell_entry.get("symbol") != buy_symbol:
                    continue

                close_leg = sell_entry.get("close")
                if not close_leg or close_leg.get("action") != "Sell":
                    continue

                close_ms = leg_sort_value_ms(close_leg)
                if buy_open_ms >= 0 and close_ms >= 0 and close_ms < buy_open_ms:
                    continue

                additional_candidates.append((close_ms, sell_idx, close_leg))

            additional_candidates.sort(key=lambda item: (item[0], item[1]))
            for _, sell_idx, close_leg in additional_candidates:
                linked_sell_legs.append(close_leg)
                used_close_only_sell_entry_indices.add(sell_idx)
                remaining_qty -= int(close_leg.get("quantity", 0) or 0)
                if remaining_qty <= 0:
                    break

        assignment_links[put_idx] = {
            "status": "ASSIGNED_LINKED",
            "buy_entry_idx": linked_buy_idx,
            "sell_legs": linked_sell_legs
        }

    return assignment_links


def report_unmatched_expired_trades(combined_trades: list):
    """Reports unmatched expired options to the console to help user identify missing adjustments."""
    now = datetime.datetime.now()
    found_any = False
    
    for trade in combined_trades:
        o = trade.get('open')
        c = trade.get('close')
        symbol = trade.get('symbol')
        
        # Only interested in unmatched opens
        if o and not c:
            exp_date = parse_expiration_date(symbol)
            if exp_date and exp_date < now:
                if not found_any:
                    msg = "\nWARNING: UNMATCHED EXPIRED OPTIONS FOUND\n" \
                          "These options have passed their expiration date but have no matching closing order.\n" \
                          "This often indicates a missing corporate action in adjustments.csv (e.g., stock split or symbol change)."
                    print(msg)
                    logger.warning(msg)
                    found_any = True
                
                line = f"  - {symbol} (Qty: {o.get('quantity')}, Open Date: {o.get('date')}, Order ID: {o.get('order_id')})"
                print(line)
                logger.warning(line)
    
    if found_any:
        footer = "Please check your E*TRADE history and update adjustments.csv if a corporate action occurred.\n"
        print(footer)
        logger.warning(footer)


def match_trades(opens: list, closes: list) -> list:
    """
    Matches opening and closing trades by symbol using FIFO logic with quantity splitting.

    :param opens: List of opening trades.
    :param closes: List of closing trades.
    :return: A list of matched trade dictionaries.
    """
    # Group by symbol
    opens_by_symbol = defaultdict(deque)
    closes_by_symbol = defaultdict(deque)

    # Sort by epoch ascending (oldest first)
    # Use a default epoch of 0 if missing (common in some test scenarios)
    sorted_opens = sorted(opens, key=lambda x: x.get('epoch', 0))
    sorted_closes = sorted(closes, key=lambda x: x.get('epoch', 0))

    for o in sorted_opens:
        opens_by_symbol[o['symbol']].append(copy.deepcopy(o))
    for c in sorted_closes:
        closes_by_symbol[c['symbol']].append(copy.deepcopy(c))

    combined = []
    
    # Get all unique symbols
    symbols = sorted(list(set(list(opens_by_symbol.keys()) + list(closes_by_symbol.keys()))))

    for symbol in symbols:
        q_opens = opens_by_symbol[symbol]
        q_closes = closes_by_symbol[symbol]

        while q_opens and q_closes:
            o = q_opens.popleft()
            c = q_closes.popleft()

            o_qty_dec = Decimal(str(o['quantity']))
            c_qty_dec = Decimal(str(c['quantity']))
            match_qty = min(o_qty_dec, c_qty_dec)

            # Create matched row
            matched_o = copy.deepcopy(o)
            matched_c = copy.deepcopy(c)
            
            # Prorate totals
            ratio_o = match_qty / o_qty_dec
            matched_o['quantity'] = float(match_qty) if isinstance(o['quantity'], float) else int(match_qty)
            matched_o['total_out'] = Decimal(str(o['total_out'])) * ratio_o
            matched_o['total_in'] = Decimal(str(o['total_in'])) * ratio_o
            
            ratio_c = match_qty / c_qty_dec
            matched_c['quantity'] = float(match_qty) if isinstance(c['quantity'], float) else int(match_qty)
            matched_c['total_in'] = Decimal(str(c['total_in'])) * ratio_c
            matched_c['total_out'] = Decimal(str(c['total_out'])) * ratio_c

            combined.append({
                "symbol": symbol,
                "epoch": c.get('epoch', 0), 
                "open": matched_o,
                "close": matched_c
            })

            # Put remainders back
            if o_qty_dec > match_qty:
                o['quantity'] = float(o_qty_dec - match_qty) if isinstance(o['quantity'], float) else int(o_qty_dec - match_qty)
                o['total_out'] = Decimal(str(o['total_out'])) * (1 - ratio_o)
                o['total_in'] = Decimal(str(o['total_in'])) * (1 - ratio_o)
                q_opens.appendleft(o)
            
            if c_qty_dec > match_qty:
                c['quantity'] = float(c_qty_dec - match_qty) if isinstance(c['quantity'], float) else int(c_qty_dec - match_qty)
                c['total_in'] = Decimal(str(c['total_in'])) * (1 - ratio_c)
                c['total_out'] = Decimal(str(c['total_out'])) * (1 - ratio_c)
                q_closes.appendleft(c)

        # Remaining opens
        while q_opens:
            o = q_opens.popleft()
            combined.append({
                "symbol": symbol,
                "epoch": o.get('epoch', 0),
                "open": o,
                "close": None
            })

        # Remaining closes
        while q_closes:
            c = q_closes.popleft()
            combined.append({
                "symbol": symbol,
                "epoch": c.get('epoch', 0),
                "open": None,
                "close": c
            })

    return combined


def load_adjustments(file_path='adjustments.csv'):
    """
    Loads stock splits and strike adjustments from a CSV file.
    Format: Ticker,Date,Ratio,StrikeAdj,NewTicker
    """
    adjustments = []
    # Fallback to splits.csv for backward compatibility
    if not os.path.exists(file_path) and os.path.exists('splits.csv'):
        file_path = 'splits.csv'
        
    if not os.path.exists(file_path):
        return adjustments
        
    try:
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or line.lower().startswith('ticker,date'):
                    continue
                parts = line.split(',')
                if len(parts) >= 3:
                    ticker = parts[0].strip()
                    date_str = parts[1].strip()
                    
                    # Handle fractional ratios like 3:2
                    ratio_str = parts[2].strip()
                    if ratio_str and ':' in ratio_str:
                        ratio_parts = ratio_str.split(':')
                        if len(ratio_parts) == 2:
                            ratio = Decimal(ratio_parts[0].strip()) / Decimal(ratio_parts[1].strip())
                        else:
                            ratio = Decimal(ratio_str)
                    else:
                        ratio = Decimal(ratio_str) if ratio_str else Decimal("1.0")

                    strike_adj = Decimal(parts[3].strip()) if len(parts) >= 4 and parts[3].strip() else Decimal("0.0")
                    new_ticker = parts[4].strip() if len(parts) >= 5 and parts[4].strip() else None
                    adj_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                    adjustments.append({
                        'ticker': ticker, 
                        'date': adj_date, 
                        'ratio': ratio,
                        'strike_adj': strike_adj,
                        'new_ticker': new_ticker
                    })
    except Exception as e:
        logger.error(f"Error loading adjustments from {file_path}: {e}")
    return adjustments


def apply_corporate_actions(opens: list = None, closes: list = None, trades: list = None, adjustments: list = None):
    """
    Adjusts quantities, prices, and symbols for stock splits and other corporate actions.
    """
    if not adjustments:
        return

    # Sort adjustments chronologically to ensure multiple adjustments are applied in order
    sorted_adjs = sorted(adjustments, key=lambda x: x['date'])

    def process_leg(leg):
        if not leg:
            return
        
        leg_date = get_leg_date(leg)
        if not leg_date:
            return
            
        for adj in sorted_adjs:
            adj_date = adj['date']
            # Ensure we are comparing dates to dates
            if hasattr(adj_date, 'date'):
                adj_date = adj_date.date()
            if hasattr(leg_date, 'date'):
                val_date = leg_date.date()
            else:
                val_date = leg_date

            symbol = leg.get('symbol', '')
            ticker = adj['ticker']
            
            # Find all tickers that might refer to this underlying (standard and non-standard)
            target_tickers = {ticker}
            if adj.get('new_ticker') and adj['new_ticker'].lower() != 'none':
                target_tickers.add(adj['new_ticker'])
            # Also catch any other new_tickers defined for this ticker in other adjustments
            for a in adjustments:
                if a['ticker'] == ticker and a.get('new_ticker') and a['new_ticker'].lower() != 'none':
                    target_tickers.add(a['new_ticker'])

            # Match if the current symbol starts with any of the target tickers
            matches_underlying = any(symbol.startswith(t + " ") for t in target_tickers)
            
            # Safety: If this is a symbol-changing adjustment and the leg already has the NEW ticker,
            # and the trade is before the adjustment, we assume it was already processed.
            is_adj_new_ticker = adj.get('new_ticker') and adj['new_ticker'].lower() != 'none'
            if is_adj_new_ticker and symbol.startswith(adj['new_ticker'] + " ") and val_date < adj_date:
                continue

            # Handle post-split non-standard options multiplier correction
            # (only for fresh orders where we assume E*TRADE used 100 multiplier)
            if is_adj_new_ticker and symbol.startswith(adj['new_ticker'] + " "):
                if val_date >= adj_date:
                     target_multiplier = 100 * adj['ratio']
                     if target_multiplier != 100:
                         # Multiplier safety: Only apply if it looks like the raw 100-multiplier calculation
                         # This prevents double-correcting trades loaded from history.
                         price = Decimal(str(leg.get('price', '0')))
                         qty = Decimal(str(leg.get('quantity', '0')))
                         raw_val = abs(price * 100 * qty)
                         
                         total_in = abs(Decimal(str(leg.get('total_in', '0'))))
                         total_out = abs(Decimal(str(leg.get('total_out', '0'))))
                         
                         if (total_in > 0 and abs(total_in - raw_val) < 0.001) or \
                            (total_out > 0 and abs(total_out - raw_val) < 0.001):
                             leg['total_in'] = (Decimal(str(leg['total_in'])) / 100) * target_multiplier
                             leg['total_out'] = (Decimal(str(leg['total_out'])) / 100) * target_multiplier

            if val_date < adj_date:
                # Option match
                if matches_underlying and " '" in symbol:
                    opt = parse_option_details(symbol)
                    # Match if the option ticker matches any of our target tickers
                    if opt and opt['ticker'] in target_tickers:
                        # Non-standard adjustment: Symbol change (like TLRY1)
                        is_non_standard = is_adj_new_ticker

                        # Adjust quantity (ratio)
                        if adj['ratio'] != 1 and not is_non_standard:
                            leg['quantity'] = int(Decimal(str(leg['quantity'])) * adj['ratio'])
                            # Adjust price (ratio)
                            leg['price'] = Decimal(str(leg['price'])) / adj['ratio']
                        
                        # Adjust strike (ratio and absolute)
                        new_strike = opt['strike']
                        if adj['ratio'] != 1 and not is_non_standard:
                            new_strike = new_strike / adj['ratio']
                        if adj['strike_adj'] != 0:
                            new_strike = new_strike - adj['strike_adj']
                            
                        new_strike = round(new_strike, 2)
                        strike_str = "{:f}".format(new_strike.normalize())
                        
                        # Rebuild symbol
                        new_symbol = re.sub(r"\$\d+(?:\.\d+)?", f"${strike_str}", symbol)
                        if is_non_standard:
                            # Replace the ticker in the symbol if it hasn't been replaced yet
                            if adj['ticker'] + " " in new_symbol and adj['new_ticker'] + " " not in new_symbol:
                                new_symbol = new_symbol.replace(adj['ticker'] + " ", adj['new_ticker'] + " ", 1)
                        leg['symbol'] = new_symbol
                
                # Stock match
                elif symbol == ticker or symbol.startswith(ticker + " ("):
                    if adj['ratio'] != 1:
                        leg['quantity'] = int(Decimal(str(leg['quantity'])) * adj['ratio'])
                        leg['price'] = Decimal(str(leg['price'])) / adj['ratio']

    if opens:
        for leg in opens:
            process_leg(leg)
    if closes:
        for leg in closes:
            process_leg(leg)
    if trades:
        for t in trades:
            process_leg(t.get('open'))
            process_leg(t.get('close'))
            if t.get('open'):
                t['symbol'] = t['open']['symbol']
            elif t.get('close'):
                t['symbol'] = t['close']['symbol']


def sort_for_output(df_to_sort: pd.DataFrame) -> pd.DataFrame:
    """
    Sorts a DataFrame of trades for output, ensuring related legs (like assignments) stay together.
    """
    if df_to_sort.empty:
        return df_to_sort

    sorted_df = df_to_sort.copy()
    
    # Pre-calculate essential sort components
    sort_close = pd.to_datetime(sorted_df["Close Date"], errors='coerce')
    sort_open = pd.to_datetime(sorted_df["Open Date"], errors='coerce')
    sort_symbol = sorted_df["Symbol"].fillna("").astype(str)
    
    # 1. Effective Close Date logic
    # For regular trades, we sort by Close Date.
    # For assigned stock trades, we use the Open Date (assignment date) to group with the option.
    eff_close = sort_close.copy()
    if "Strategy Event" in sorted_df.columns:
        is_assn_stock = sorted_df["Strategy Event"].isin(["ASSIGNMENT TRADE", "ASSIGNMENT BUY", "ASSIGNMENT SELL"])
        # Use .loc to avoid SettingWithCopy warning
        eff_close[is_assn_stock] = sort_open[is_assn_stock]
    
    # Fill N/A with max timestamp for open trades
    sort_close_order = eff_close.fillna(pd.Timestamp.max)

    # 2. Mixed Symbol logic (Open legs should follow or precede closed legs of the same symbol)
    # This keeps multiple legs of a single symbol trade together even if some are open.
    symbol_has_close = sort_close.notna().groupby(sort_symbol).transform('any')
    symbol_has_open_only = sort_close.isna().groupby(sort_symbol).transform('any')
    mixed_symbol = symbol_has_close & symbol_has_open_only
    
    # For mixed symbols, use the earliest close date of that symbol for the open legs too
    symbol_min_close = sort_close.groupby(sort_symbol).transform('min')
    sort_close_order = sort_close_order.where(~(mixed_symbol & sort_close.isna()), symbol_min_close)
    sort_open_only_first = (mixed_symbol & sort_close.isna()).astype(int)

    # 3. Strategy Link ID grouping
    # This specifically handles keeping assignments together.
    strat_id = pd.Series("", index=sorted_df.index)
    if "Strategy Link ID" in sorted_df.columns:
        strat_id = sorted_df["Strategy Link ID"].fillna("").astype(str)
        
    # 4. Intra-group priority (Option should come before resulting stock)
    event_priority = pd.Series(1, index=sorted_df.index)
    if "Strategy Event" in sorted_df.columns:
        # Option assignment row priority 0 (first)
        event_priority[sorted_df["Strategy Event"] == "SHORT PUT"] = 0

    sorted_df["_sort_close"] = sort_close_order
    sorted_df["_sort_strat"] = strat_id
    sorted_df["_sort_symbol"] = sort_symbol
    sorted_df["_sort_open_only_first"] = sort_open_only_first
    sorted_df["_sort_priority"] = event_priority
    sorted_df["_sort_open"] = sort_open

    sorted_df = sorted_df.sort_values(
        by=["_sort_close", "_sort_strat", "_sort_priority", "_sort_symbol", "_sort_open_only_first", "_sort_open"],
        ascending=[True, True, True, True, False, True],
        na_position='last'
    )
    
    helper_cols = ["_sort_close", "_sort_strat", "_sort_priority", "_sort_symbol", "_sort_open_only_first", "_sort_open"]
    return sorted_df.drop(columns=[c for c in helper_cols if c in sorted_df.columns])


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


def load_previous_output(output_file: str) -> list:
    """
    Loads previous trades from an Excel or CSV file to enable 'bringing forward' historical data.
    """
    if not output_file:
        return []

    original_output_file = output_file
    
    # If the output file is still .csv, we'll check it, but also check for Excel files
    if output_file.lower().endswith('.csv'):
        xlsx_file = output_file[:-4] + '.xlsx'
    else:
        xlsx_file = output_file

    directory = os.path.dirname(xlsx_file) or '.'
    base_name = os.path.basename(xlsx_file)
    # Remove extension and date pattern if exists to find the prefix
    # We look for files starting with 'orders_output'
    prefix = base_name.split('.')[0]
    if '_' in prefix:
        prefix = prefix.split('_')[0]

    # Find the most recent Excel file if it doesn't exist exactly as named (e.g. dated files)
    if not os.path.exists(xlsx_file):
        extensions = ['.xlsx', '.xlsm']
        files = [f for f in os.listdir(directory) if f.startswith(prefix) and any(f.endswith(ext) for ext in extensions) and not f.startswith('~$')]
        if files:
            # Sort by modification time to get the latest
            files.sort(key=lambda x: os.path.getmtime(os.path.join(directory, x)), reverse=True)
            xlsx_file = os.path.join(directory, files[0])
            print(f"Loading previous trades from: {xlsx_file}")
        else:
            xlsx_file = None
    else:
        print(f"Loading previous trades from exact file: {xlsx_file}")

    all_history = []
    loaded_from_excel = False

    def normalize_column_name(col_name: str) -> str:
        return re.sub(r'\s+', ' ', str(col_name)).strip()

    def parse_quantity(qty_value):
        if pd.isna(qty_value):
            return None
        try:
            qty = int(float(str(qty_value).replace(',', '').strip()))
            return qty if qty > 0 else None
        except (TypeError, ValueError):
            return None

    if xlsx_file and os.path.exists(xlsx_file):
        try:
            xls = pd.ExcelFile(xlsx_file)
            loaded_from_excel = True
            for sheet_name in xls.sheet_names:
                if sheet_name == 'Dashboard':
                    continue
                
                df = pd.read_excel(xls, sheet_name=sheet_name)
                # Filter out completely empty rows
                df = df.dropna(how='all')
                if df.empty:
                    continue

                # Normalize whitespace so headers like "Open\nQuantity" map to "Open Quantity"
                df.rename(columns={col: normalize_column_name(col) for col in df.columns}, inplace=True)

                # Standardize columns (some might be missing in older versions)
                required_cols = [
                    'Symbol', 'Open Date', 'Open Action', 'Open Quantity', 'Open Price', 
                    'Open Total Out', 'Open Total In', 'Close Date', 'Close Action', 
                    'Close Quantity', 'Close Price', 'Close Total In', 'Close Total Out'
                ]
                
                # Check for legacy column names in single-sheet formats
                if 'Symbol' not in df.columns:
                    # Try to find a column that looks like Symbol
                    for col in df.columns:
                        if 'symbol' in str(col).lower():
                            df.rename(columns={col: 'Symbol'}, inplace=True)
                            break
                
                if 'Symbol' not in df.columns:
                    continue

                for col in required_cols:
                    if col not in df.columns:
                        df[col] = None
                
                # Map back to internal 'combined' structure
                for _, row in df.iterrows():
                    # Skip if symbol is missing (likely an empty or header row)
                    if pd.isna(row['Symbol']):
                        continue

                    # Skip synthetic assignment rows from previously generated short-put tabs.
                    # They are reporting-only duplicates of stock legs and should not be reloaded
                    # as historical source trades.
                    strategy_event = str(row.get('Strategy Event')).strip().upper() if pd.notna(row.get('Strategy Event')) else ''
                    if strategy_event in {'ASSIGNMENT BUY', 'ASSIGNMENT SELL'}:
                        continue

                    # Reconstruct 'open' part
                    opening = None
                    open_qty = parse_quantity(row['Open Quantity'])
                    if pd.notna(row['Open Date']) and open_qty is not None:
                        opening = {
                            "symbol": str(row['Symbol']),
                            "date": str(row['Open Date']),
                            "action": str(row['Open Action']),
                            "quantity": open_qty,
                            "price": Decimal(str(row['Open Price'])) if pd.notna(row['Open Price']) else None,
                            "total_in": Decimal(str(row['Open Total In'])) if pd.notna(row['Open Total In']) else 0,
                            "total_out": Decimal(str(row['Open Total Out'])) if pd.notna(row['Open Total Out']) else 0,
                            "order_id": row.get('Open Order ID') if pd.notna(row.get('Open Order ID')) else None,
                        }
                        # Try to reconstruct epoch from date
                        parsed_open_date = parse_mmddyyyy(row['Open Date'])
                        if parsed_open_date:
                            opening["epoch"] = int(datetime.datetime(parsed_open_date.year, parsed_open_date.month, parsed_open_date.day).timestamp() * 1000)
                        else:
                            opening["epoch"] = None
                    
                    # Reconstruct 'close' part
                    closing = None
                    close_qty = parse_quantity(row['Close Quantity'])
                    if pd.notna(row['Close Date']) and close_qty is not None:
                        closing = {
                            "symbol": str(row['Symbol']),
                            "date": str(row['Close Date']),
                            "action": str(row['Close Action']),
                            "quantity": close_qty,
                            "price": Decimal(str(row['Close Price'])) if pd.notna(row['Close Price']) else None,
                            "total_in": Decimal(str(row['Close Total In'])) if pd.notna(row['Close Total In']) else 0,
                            "total_out": Decimal(str(row['Close Total Out'])) if pd.notna(row['Close Total Out']) else 0,
                            "is_expired": row.get('EXPIRED') == "EXPIRED",
                            "order_id": row.get('Close Order ID') if pd.notna(row.get('Close Order ID')) else None,
                        }
                        # Try to reconstruct epoch from date
                        parsed_close_date = parse_mmddyyyy(row['Close Date'])
                        if parsed_close_date:
                            closing["epoch"] = int(datetime.datetime(parsed_close_date.year, parsed_close_date.month, parsed_close_date.day).timestamp() * 1000)
                        else:
                            closing["epoch"] = None

                    trade = {
                        "symbol": str(row['Symbol']),
                        "epoch": closing.get("epoch") if (closing and closing.get("epoch") is not None) else (opening.get("epoch") if (opening and opening.get("epoch") is not None) else 0),
                        "open": opening,
                        "close": closing
                    }
                    if opening or closing:
                        all_history.append(trade)
        except Exception as e:
            print(f"Warning: Could not load previous Excel output file: {e}")

    # Merge legacy CSV only when no Excel history was loaded.
    # If we already loaded a dated Excel baseline, always merging CSV can
    # reintroduce stale open-only rows and corrupt close-link carry-forward.
    if (not loaded_from_excel) and os.path.exists('orders_output.csv'):
        try:
            print(f"Merging legacy trades from CSV: orders_output.csv")
            df = pd.read_csv('orders_output.csv')
            # Filter out completely empty rows
            df = df.dropna(how='all')
            df.rename(columns={col: normalize_column_name(col) for col in df.columns}, inplace=True)
            
            # Map back to internal 'combined' structure
            for _, row in df.iterrows():
                # Skip if symbol is missing
                if pd.isna(row['Symbol']):
                    continue

                strategy_event = str(row.get('Strategy Event')).strip().upper() if pd.notna(row.get('Strategy Event')) else ''
                if strategy_event in {'ASSIGNMENT BUY', 'ASSIGNMENT SELL'}:
                    continue

                # Reconstruct 'open' part
                opening = None
                open_qty = parse_quantity(row['Open Quantity'])
                if pd.notna(row['Open Date']) and open_qty is not None:
                    opening = {
                        "symbol": str(row['Symbol']),
                        "date": str(row['Open Date']),
                        "action": str(row['Open Action']),
                        "quantity": open_qty,
                        "price": Decimal(str(row['Open Price'])) if pd.notna(row['Open Price']) else None,
                        "total_in": Decimal(str(row['Open Total In'])) if pd.notna(row['Open Total In']) else 0,
                        "total_out": Decimal(str(row['Open Total Out'])) if pd.notna(row['Open Total Out']) else 0,
                    }
                    parsed_open_date = parse_mmddyyyy(row['Open Date'])
                    if parsed_open_date:
                        opening["epoch"] = int(datetime.datetime(parsed_open_date.year, parsed_open_date.month, parsed_open_date.day).timestamp() * 1000)
                    else:
                        opening["epoch"] = None
                
                # Reconstruct 'close' part
                closing = None
                close_qty = parse_quantity(row['Close Quantity'])
                if pd.notna(row['Close Date']) and close_qty is not None:
                    closing = {
                        "symbol": str(row['Symbol']),
                        "date": str(row['Close Date']),
                        "action": str(row['Close Action']),
                        "quantity": close_qty,
                        "price": Decimal(str(row['Close Price'])) if pd.notna(row['Close Price']) else None,
                        "total_in": Decimal(str(row['Close Total In'])) if pd.notna(row['Close Total In']) else 0,
                        "total_out": Decimal(str(row['Close Total Out'])) if pd.notna(row['Close Total Out']) else 0,
                    }
                    parsed_close_date = parse_mmddyyyy(row['Close Date'])
                    if parsed_close_date:
                        closing["epoch"] = int(datetime.datetime(parsed_close_date.year, parsed_close_date.month, parsed_close_date.day).timestamp() * 1000)
                    else:
                        closing["epoch"] = None

                trade = {
                    "symbol": str(row['Symbol']),
                    "epoch": closing.get("epoch") if (closing and closing.get("epoch") is not None) else (opening.get("epoch") if (opening and opening.get("epoch") is not None) else 0),
                    "open": opening,
                    "close": closing
                }
                if opening or closing:
                    all_history.append(trade)
        except Exception as e:
            print(f"Warning: Could not load legacy CSV file: {e}")

    return all_history


def merge_and_deduplicate(old_trades: list, new_trades: list) -> list:
    """
    Merges old and new trades using a hybrid ID and fingerprint approach.
    """
    def normalize_date_for_key(date_value):
        parsed_date = parse_mmddyyyy(date_value)
        if parsed_date:
            return parsed_date.isoformat()

        raw = str(date_value).strip() if date_value is not None else ""
        if ' ' in raw:
            raw = raw.split(' ')[0]
        return raw

    def normalize_price_for_key(price_value):
        if price_value is None:
            return ""
        try:
            price = Decimal(str(price_value))
            return str(price.normalize())
        except Exception:
            return str(price_value)

    def normalize_order_id_for_key(order_id_value):
        if order_id_value is None:
            return None
        raw = str(order_id_value).strip()
        if raw == "":
            return None

        # Normalize numerically-equivalent broker IDs loaded from mixed sources
        # (e.g. 18166, 18166.0, "18166", "18166.0").
        try:
            dec = Decimal(raw)
            if dec == dec.to_integral_value():
                return str(int(dec))
            return str(dec.normalize())
        except Exception:
            return raw

    def get_fingerprint(trade_leg):
        if not trade_leg:
            return None
        symbol = str(trade_leg.get('symbol', '')).strip()
        date_key = normalize_date_for_key(trade_leg.get('date'))
        action = str(trade_leg.get('action', '')).strip()
        quantity = int(trade_leg.get('quantity', 0) or 0)
        price_key = normalize_price_for_key(trade_leg.get('price'))
        # Fingerprint: Symbol|Date|Action|Quantity|Price
        return f"{symbol}|{date_key}|{action}|{quantity}|{price_key}"

    def get_order_leg_key(trade_leg):
        if not trade_leg:
            return None
        order_id = normalize_order_id_for_key(trade_leg.get('order_id'))
        if order_id is None:
            return None

        symbol = str(trade_leg.get('symbol', '')).strip()
        action = str(trade_leg.get('action', '')).strip()
        price_key = normalize_price_for_key(trade_leg.get('price'))
        date_key = normalize_date_for_key(trade_leg.get('date'))
        # Exclude quantity from the order leg key. This allows deduplication to correctly
        # handle split vs. unsplit legs of the same broker order (e.g., after switching to FIFO).
        return f"{order_id}|{symbol}|{action}|{price_key}|{date_key}"

    # We want to keep track of legs (opens and closes) independently to ensure full deduplication
    seen_order_leg_keys = set()
    seen_fingerprints = set()
    
    unique_trades = []
    
    # Process new trades first as they are "fresher" and have Order IDs
    for trade in new_trades + old_trades:
        o = trade['open']
        c = trade['close']
        
        # Determine if this trade is "new" to our list
        # A trade is considered seen if BOTH its legs (if they exist) have been seen
        legs_seen = 0
        legs_count = 0
        
        if o:
            legs_count += 1
            o_id_key = get_order_leg_key(o)
            o_fp = get_fingerprint(o)
            if (o_id_key and o_id_key in seen_order_leg_keys) or ((not o_id_key) and (o_fp in seen_fingerprints)):
                legs_seen += 1

        if c:
            legs_count += 1
            c_id_key = get_order_leg_key(c)
            c_fp = get_fingerprint(c)
            if (c_id_key and c_id_key in seen_order_leg_keys) or ((not c_id_key) and (c_fp in seen_fingerprints)):
                legs_seen += 1
                
        if legs_seen < legs_count:
            # At least one leg is new, so we add this trade
            unique_trades.append(trade)
            
            # Mark legs as seen
            if o:
                o_id_key = get_order_leg_key(o)
                o_fp = get_fingerprint(o)
                if o_id_key:
                    seen_order_leg_keys.add(o_id_key)
                if o_fp:
                    # Track fingerprints for all accepted legs (including those with
                    # order IDs) so legacy rows without order IDs can still dedupe
                    # against the same already-seen broker leg.
                    seen_fingerprints.add(o_fp)
            if c:
                c_id_key = get_order_leg_key(c)
                c_fp = get_fingerprint(c)
                if c_id_key:
                    seen_order_leg_keys.add(c_id_key)
                if c_fp:
                    seen_fingerprints.add(c_fp)
                
    # Reconcile stale/duplicate rows for expired option contracts.
    # 1) Keep legitimate unmatched opens, but drop open-only rows that duplicate
    #    an open leg already represented by a closed row for the same expired symbol.
    # 2) If the same open leg appears with both a real close and a synthetic close,
    #    keep the real-close row and drop the synthetic duplicate row.
    # Re-match orphans that might have become matchable after split normalization
    # (e.g. one leg was already renamed by broker in history, the other was not)
    matched = [t for t in unique_trades if t.get('open') and t.get('close')]
    orphan_opens = [t.get('open') for t in unique_trades if t.get('open') and not t.get('close')]
    orphan_closes = [t.get('close') for t in unique_trades if not t.get('open') and t.get('close')]
    
    if orphan_opens and orphan_closes:
        rematched = match_trades(orphan_opens, orphan_closes)
        unique_trades = matched + rematched

    expired_symbols_with_closed_open_keys = {}
    expired_symbols_open_keys_with_real_close = {}
    expired_prior_year_symbols_closed_open_signatures = {}
    current_year = datetime.date.today().year

    def get_open_signature(trade_leg):
        if not trade_leg:
            return None
        symbol = str(trade_leg.get('symbol', '')).strip()
        date_key = normalize_date_for_key(trade_leg.get('date'))
        action = str(trade_leg.get('action', '')).strip()
        quantity = int(trade_leg.get('quantity', 0) or 0)
        return f"{symbol}|{date_key}|{action}|{quantity}"

    for trade in unique_trades:
        close_leg = trade.get('close')
        open_leg = trade.get('open')
        if not close_leg or not open_leg:
            continue
        symbol = str((trade.get('symbol') or close_leg.get('symbol') or open_leg.get('symbol') or '')).strip()
        expiration_dt = parse_expiration_date(symbol)
        if not expiration_dt or expiration_dt.date() >= datetime.date.today():
            continue

        open_key = get_fingerprint(open_leg)
        if open_key:
            expired_symbols_with_closed_open_keys.setdefault(symbol, set()).add(open_key)
            close_order_id = str(close_leg.get('order_id') or '')
            if not close_order_id.startswith('SYNTH-'):
                expired_symbols_open_keys_with_real_close.setdefault(symbol, set()).add(open_key)
        if expiration_dt.year < current_year:
            open_signature = get_open_signature(open_leg)
            if open_signature:
                expired_prior_year_symbols_closed_open_signatures.setdefault(symbol, set()).add(open_signature)

    if not expired_symbols_with_closed_open_keys:
        return unique_trades

    reconciled_trades = []
    for trade in unique_trades:
        open_leg = trade.get('open')
        close_leg = trade.get('close')
        if open_leg and not close_leg:
            symbol = str((trade.get('symbol') or open_leg.get('symbol') or '')).strip()
            open_signatures = expired_prior_year_symbols_closed_open_signatures.get(symbol)
            if open_signatures:
                open_signature = get_open_signature(open_leg)
                if open_signature in open_signatures:
                    continue
            closed_open_keys = expired_symbols_with_closed_open_keys.get(symbol)
            if closed_open_keys:
                open_key = get_fingerprint(open_leg)
                if open_key in closed_open_keys:
                    continue

        if open_leg and close_leg:
            symbol = str((trade.get('symbol') or close_leg.get('symbol') or open_leg.get('symbol') or '')).strip()
            real_close_open_keys = expired_symbols_open_keys_with_real_close.get(symbol)
            if real_close_open_keys:
                open_key = get_fingerprint(open_leg)
                close_order_id = str(close_leg.get('order_id') or '')
                if open_key in real_close_open_keys and close_order_id.startswith('SYNTH-'):
                    continue
        reconciled_trades.append(trade)

    return reconciled_trades


def write_excel_output(combined: list, output_file: str, tax_props: dict = None):
    """
    Writes the matched trades to an Excel file with data divided across multiple sheets.

    :param combined: List of matched trade dictionaries.
    :param output_file: The path to the output Excel file.
    """
    if not output_file:
        print("No output file specified for Excel output.")
        return

    # If the output file is still .csv, change it to .xlsx and add current date
    if output_file.lower().endswith('.csv'):
        output_file = output_file[:-4]
    elif output_file.lower().endswith('.xlsx'):
        output_file = output_file[:-5]
    
    # Add today's date to filename
    datestr = datetime.datetime.now().strftime("%Y-%m-%d")
    output_file = f"{output_file}_{datestr}.xlsx"

    rows = []
    validation_rows = []
    this_year = datetime.datetime.now().year
    assignment_links = link_short_put_assignments(combined)
    assignment_linked_buy_indices = {
        info.get("buy_entry_idx")
        for info in assignment_links.values()
        if info.get("status") == "ASSIGNED_LINKED" and info.get("buy_entry_idx") is not None
    }

    def assignment_leg_key(leg: dict):
        if not leg:
            return None
        symbol = str(leg.get('symbol', '')).strip()
        action = str(leg.get('action', '')).strip()
        quantity = int(leg.get('quantity', 0) or 0)
        date_value = parse_mmddyyyy(leg.get('date'))
        date_key = date_value.isoformat() if date_value else str(leg.get('date') or '').split(' ')[0]
        try:
            price_key = str(Decimal(str(leg.get('price'))).normalize()) if leg.get('price') is not None else ""
        except Exception:
            price_key = str(leg.get('price'))
        order_id_key = str(leg.get('order_id') or '')
        return f"{symbol}|{action}|{quantity}|{price_key}|{date_key}|{order_id_key}"

    assignment_linked_sell_keys = {
        assignment_leg_key(sell_leg)
        for info in assignment_links.values()
        if info.get("status") == "ASSIGNED_LINKED"
        for sell_leg in info.get("sell_legs", [])
        if assignment_leg_key(sell_leg)
    }

    entries_with_indices = list(enumerate(combined))

    def parse_to_datetime(date_str):
        if not date_str:
            return None
        try:
            # Handle potential mixed formats or objects
            if isinstance(date_str, (datetime.datetime, datetime.date)):
                return datetime.datetime(date_str.year, date_str.month, date_str.day)
            return datetime.datetime.strptime(date_str, "%m/%d/%Y")
        except Exception:
            return date_str

    def determine_close_year(close_leg):
        if not close_leg:
            return None

        close_epoch = close_leg.get('epoch')
        if close_epoch is not None:
            try:
                close_time = datetime.datetime.fromtimestamp(int(close_epoch) / 1000)
                if close_time.year > 1980:
                    return close_time.year
            except Exception:
                pass

        parsed_date = parse_mmddyyyy(close_leg.get('date'))
        if parsed_date and parsed_date.year > 1980:
            return parsed_date.year
        return None

    def build_row_data(symbol, opening, closing, is_sold_put, close_year, strategy_link_id=None, strategy_event=None, assignment_status=None):
        def safe_float(value):
            if value is None:
                return None
            try:
                return float(value)
            except Exception:
                return None

        def safe_decimal(value):
            if value is None:
                return None
            try:
                return Decimal(str(value))
            except Exception:
                return None

        open_date = parse_to_datetime(opening.get('date')) if opening else None
        expiration_dt = parse_expiration_date(symbol)
        expiration_date = expiration_dt.date() if expiration_dt else None

        open_total_out = safe_float(opening.get('total_out')) if opening else None
        open_total_in = safe_float(opening.get('total_in')) if opening else None
        close_total_in = safe_float(closing.get('total_in')) if closing else None
        close_total_out = safe_float(closing.get('total_out')) if closing else None

        net = None
        cost_to_exercise = None
        days_to_expiration = None
        annualized_roi_percent = None
        covered_call_annualized_roi_percent = None
        long_shares_annualized_roi_percent = None
        long_options_annualized_roi_percent = None
        long_options_roi_percent = None

        close_date = parse_to_datetime(closing.get('date')) if closing else None

        def annualized_from_holding_period(net_value, capital_base, start_dt, end_dt):
            if net_value is None or capital_base is None or not start_dt or not end_dt:
                return None
            try:
                days_held = (end_dt.date() - start_dt.date()).days
            except Exception:
                return None
            if days_held <= 0 or capital_base == 0:
                return None
            return (net_value / capital_base / days_held) * 365 * 100

        if is_sold_put and opening:
            net = sum(v if v is not None else 0.0 for v in [open_total_in, open_total_out, close_total_in, close_total_out])

            option_details = parse_option_details(symbol)
            open_quantity = safe_decimal(opening.get('quantity'))
            if option_details and open_quantity is not None:
                try:
                    cost_to_exercise = float(option_details["strike"] * Decimal("100") * open_quantity)
                except Exception:
                    cost_to_exercise = None

            if open_date and expiration_date:
                try:
                    days_to_expiration = (expiration_date - open_date.date()).days
                except Exception:
                    days_to_expiration = None

            if (
                cost_to_exercise is not None
                and cost_to_exercise != 0
                and days_to_expiration is not None
                and days_to_expiration > 0
            ):
                annualized_roi_percent = (net / cost_to_exercise / days_to_expiration) * 365 * 100

        open_action = opening.get('action') if opening else None
        close_action = closing.get('action') if closing else None
        option_details = parse_option_details(symbol)

        if opening and closing and net is None:
            net = sum(v if v is not None else 0.0 for v in [open_total_in, open_total_out, close_total_in, close_total_out])

        open_capital_base = None
        if open_total_in is not None or open_total_out is not None:
            open_capital_base = abs(open_total_in or 0.0) + abs(open_total_out or 0.0)

        is_option_symbol = option_details is not None
        is_share_symbol = not is_option_symbol

        is_covered_call_like = (
            is_option_symbol
            and option_details.get("option_type") == "Call"
            and open_action == "Sell Open"
            and close_action == "Buy Close"
        )
        if is_covered_call_like:
            open_quantity = safe_decimal(opening.get('quantity'))
            covered_call_capital_base = None
            if option_details and open_quantity is not None:
                try:
                    covered_call_capital_base = float(option_details["strike"] * Decimal("100") * open_quantity)
                except Exception:
                    covered_call_capital_base = None
            covered_call_annualized_roi_percent = annualized_from_holding_period(
                net,
                covered_call_capital_base,
                open_date,
                close_date
            )

        is_long_shares_trade = (
            is_share_symbol
            and open_action == "Buy"
            and close_action == "Sell"
        )
        if is_long_shares_trade:
            long_shares_annualized_roi_percent = annualized_from_holding_period(
                net,
                open_capital_base,
                open_date,
                close_date
            )

        is_long_options_trade = (
            is_option_symbol
            and open_action == "Buy Open"
            and close_action == "Sell Close"
            and option_details.get("option_type") in {"Call", "Put"}
        )
        if is_long_options_trade:
            if net is not None and open_capital_base not in (None, 0):
                try:
                    long_options_roi_percent = (net / open_capital_base) * 100
                except Exception:
                    long_options_roi_percent = None
            long_options_annualized_roi_percent = annualized_from_holding_period(
                net,
                open_capital_base,
                open_date,
                close_date
            )

        close_price = None
        if closing and closing.get('price') is not None:
            try:
                close_price = Decimal(str(closing.get('price')))
            except Exception:
                close_price = None

        real_zero_close_after_expiration = (
            closing
            and close_price == Decimal("0")
            and close_on_or_after_option_expiration(symbol, closing)
        )

        return {
            "Symbol": symbol,
            "Open Date": open_date,
            "Expiration Date": expiration_date,
            "Open Action": opening.get('action') if opening else None,
            "Open\nQuantity": opening.get('quantity') if opening else None,
            "Open Price": float(opening.get('price')) if opening and opening.get('price') is not None else None,
            "Open Total Out": open_total_out,
            "Open Total In": open_total_in,
            "Close Date": close_date,
            "Close Action": closing.get('action') if closing else None,
            "Close\nQuantity": closing.get('quantity') if closing else None,
            "Close Price": float(closing.get('price')) if closing and closing.get('price') is not None else None,
            "Close Total In": close_total_in,
            "Close Total Out": close_total_out,
            "Net": net,
            "Cost To Exercise": cost_to_exercise,
            "Days to Expiration": days_to_expiration,
            "Annualized ROI %": annualized_roi_percent,
            "Covered Call Annualized ROI %": covered_call_annualized_roi_percent,
            "Long Shares Annualized ROI %": long_shares_annualized_roi_percent,
            "Long Options ROI %": long_options_roi_percent,
            "Long Options Annualized ROI %": long_options_annualized_roi_percent,
            "EXPIRED": "EXPIRED" if (closing and closing.get('is_expired')) or real_zero_close_after_expiration else "",
            "Open Order ID": opening.get('order_id') if opening else None,
            "Close Order ID": closing.get('order_id') if closing else None,
            "Strategy Link ID": strategy_link_id,
            "Strategy Event": strategy_event,
            "Assignment Status": assignment_status,
            "Leg Status": "",
            "_is_sold_put": is_sold_put,
            "_close_year": close_year
        }

    def append_leg_status(current_value, flag):
        if not flag:
            return current_value or ""
        if not current_value:
            return flag
        parts = [p.strip() for p in str(current_value).split("|") if p.strip()]
        if flag in parts:
            return "|".join(parts)
        parts.append(flag)
        return "|".join(parts)

    def annotate_leg_status(df_all: pd.DataFrame):
        if df_all.empty:
            return df_all

        df = df_all.copy()
        if "Leg Status" not in df.columns:
            df["Leg Status"] = ""
        else:
            df["Leg Status"] = df["Leg Status"].fillna("")

        open_only_mask = df["Open Action"].notna() & df["Close Action"].isna()
        close_only_mask = df["Open Action"].isna() & df["Close Action"].notna()

        df.loc[open_only_mask, "Leg Status"] = df.loc[open_only_mask, "Leg Status"].apply(
            lambda x: append_leg_status(x, "OPEN_WITHOUT_CLOSE")
        )
        df.loc[close_only_mask, "Leg Status"] = df.loc[close_only_mask, "Leg Status"].apply(
            lambda x: append_leg_status(x, "CLOSE_WITHOUT_OPEN")
        )

        option_mask = df["Symbol"].astype(str).str.contains(" Call| Put", na=False)
        option_df = df[option_mask]

        if option_df.empty:
            return df

        for symbol, group in option_df.groupby("Symbol", dropna=False):
            long_open_qty = group[group["Open Action"] == "Buy Open"]["Open\nQuantity"].fillna(0).sum()
            long_close_qty = group[group["Close Action"] == "Sell Close"]["Close\nQuantity"].fillna(0).sum()
            short_open_qty = group[group["Open Action"] == "Sell Open"]["Open\nQuantity"].fillna(0).sum()
            short_close_qty = group[group["Close Action"] == "Buy Close"]["Close\nQuantity"].fillna(0).sum()

            long_open_only = group[(group["Open Action"] == "Buy Open") & (group["Close Action"].isna())]
            short_open_only = group[(group["Open Action"] == "Sell Open") & (group["Close Action"].isna())]
            long_close_rows = group[group["Close Action"] == "Sell Close"]
            short_close_rows = group[group["Close Action"] == "Buy Close"]

            long_is_unbalanced = abs(float(long_open_qty) - float(long_close_qty)) > 1e-9
            short_is_unbalanced = abs(float(short_open_qty) - float(short_close_qty)) > 1e-9

            if long_is_unbalanced and (long_open_qty > 0 or long_close_qty > 0):
                long_idx = group[
                    (group["Open Action"] == "Buy Open") | (group["Close Action"] == "Sell Close")
                ].index
                df.loc[long_idx, "Leg Status"] = df.loc[long_idx, "Leg Status"].apply(
                    lambda x: append_leg_status(x, "LONG_QTY_MISMATCH")
                )

            if short_is_unbalanced and (short_open_qty > 0 or short_close_qty > 0):
                short_idx = group[
                    (group["Open Action"] == "Sell Open") | (group["Close Action"] == "Buy Close")
                ].index
                df.loc[short_idx, "Leg Status"] = df.loc[short_idx, "Leg Status"].apply(
                    lambda x: append_leg_status(x, "SHORT_QTY_MISMATCH")
                )

            long_aggregated_close = (
                len(long_open_only) > 0
                and len(long_close_rows) > 0
                and long_close_rows["Close\nQuantity"].fillna(0).max() > 1
                and abs(float(long_open_qty) - float(long_close_qty)) <= 1e-9
            )
            if long_aggregated_close:
                long_related_idx = group[
                    (group["Open Action"] == "Buy Open") | (group["Close Action"] == "Sell Close")
                ].index
                df.loc[long_related_idx, "Leg Status"] = df.loc[long_related_idx, "Leg Status"].apply(
                    lambda x: append_leg_status(x, "MULTI_LEG_AGGREGATED_CLOSE")
                )

                long_close_order_ids = [
                    oid for oid in long_close_rows["Close Order ID"].dropna().tolist() if str(oid).strip()
                ]
                unique_long_close_order_ids = {str(oid) for oid in long_close_order_ids}
                if len(unique_long_close_order_ids) == 1:
                    shared_close_order_id = long_close_order_ids[0]
                    long_open_only_missing_close_id_idx = long_open_only[
                        long_open_only["Close Order ID"].isna()
                    ].index
                    if len(long_open_only_missing_close_id_idx) > 0:
                        df.loc[long_open_only_missing_close_id_idx, "Close Order ID"] = shared_close_order_id

            short_aggregated_close = (
                len(short_open_only) > 0
                and len(short_close_rows) > 0
                and short_close_rows["Close\nQuantity"].fillna(0).max() > 1
                and abs(float(short_open_qty) - float(short_close_qty)) <= 1e-9
            )
            if short_aggregated_close:
                short_related_idx = group[
                    (group["Open Action"] == "Sell Open") | (group["Close Action"] == "Buy Close")
                ].index
                df.loc[short_related_idx, "Leg Status"] = df.loc[short_related_idx, "Leg Status"].apply(
                    lambda x: append_leg_status(x, "MULTI_LEG_AGGREGATED_CLOSE")
                )

                short_close_order_ids = [
                    oid for oid in short_close_rows["Close Order ID"].dropna().tolist() if str(oid).strip()
                ]
                unique_short_close_order_ids = {str(oid) for oid in short_close_order_ids}
                if len(unique_short_close_order_ids) == 1:
                    shared_close_order_id = short_close_order_ids[0]
                    short_open_only_missing_close_id_idx = short_open_only[
                        short_open_only["Close Order ID"].isna()
                    ].index
                    if len(short_open_only_missing_close_id_idx) > 0:
                        df.loc[short_open_only_missing_close_id_idx, "Close Order ID"] = shared_close_order_id

        return df

    def build_validation_issues(df_all: pd.DataFrame):
        if df_all.empty:
            return pd.DataFrame(columns=list(df_all.columns) + ["ValidationIssueType", "ValidationReason"])

        issues = []
        option_rows = df_all[df_all["Symbol"].astype(str).str.contains(" Call| Put", na=False)].copy()
        option_rows = option_rows[option_rows["Assignment Status"].astype(str) != "ASSIGNED_LINKED"]

        if option_rows.empty:
            return pd.DataFrame(columns=list(df_all.columns) + ["ValidationIssueType", "ValidationReason"])

        for symbol, group in option_rows.groupby("Symbol", dropna=False):
            open_qty_total = group[
                group["Open Action"].isin(["Buy Open", "Sell Open"])
            ]["Open\nQuantity"].fillna(0).sum()
            close_qty_total = group[
                group["Close Action"].isin(["Buy Close", "Sell Close"])
            ]["Close\nQuantity"].fillna(0).sum()

            unmatched_close_qty = int(max(0, close_qty_total - open_qty_total))
            unmatched_open_qty = int(max(0, open_qty_total - close_qty_total))
            
            expiration_dt = parse_expiration_date(str(symbol))
            is_expired = expiration_dt is not None and expiration_dt.date() < datetime.date.today()

            # Handle unmatched closes (historical orphans)
            if unmatched_close_qty > 0:
                close_only_rows = group[
                    group["Close Action"].isin(["Buy Close", "Sell Close"])
                    & group["Open Action"].isna()
                    & group["Close\nQuantity"].fillna(0).gt(0)
                ].copy()

                if not close_only_rows.empty:
                    close_only_rows = close_only_rows.sort_values(by=["Close Date", "Close\nQuantity"], ascending=[True, False])

                    for _, candidate in close_only_rows.iterrows():
                        if unmatched_close_qty <= 0:
                            break

                        candidate_close_date = candidate.get("Close Date")
                        if pd.isna(candidate_close_date):
                            continue

                        # Validation Issues is intended for historical orphan closes.
                        # Keep current-year rows on their primary trade sheet only.
                        if getattr(candidate_close_date, "year", None) is None or int(candidate_close_date.year) >= this_year:
                            continue

                        if not is_expired:
                            continue

                        qty = int(candidate.get("Close\nQuantity") or 0)
                        if qty <= 0:
                            continue

                        issue_row = candidate.to_dict()
                        issue_row["ValidationIssueType"] = "historical_orphan_close"
                        issue_row["ValidationReason"] = "Close exists without enough matching open quantity; contract expiration is in the past."
                        issues.append(issue_row)
                        unmatched_close_qty -= qty

            # Handle unmatched opens (expired but unmatched)
            if unmatched_open_qty > 0 and is_expired:
                open_only_rows = group[
                    group["Open Action"].isin(["Buy Open", "Sell Open"])
                    & group["Close Action"].isna()
                    & group["Open\nQuantity"].fillna(0).gt(0)
                ].copy()
                
                for _, candidate in open_only_rows.iterrows():
                    issue_row = candidate.to_dict()
                    issue_row["ValidationIssueType"] = "expired_unmatched_open"
                    issue_row["ValidationReason"] = "Option has expired but no matching close was found. Check adjustments.csv for symbol/strike changes."
                    issues.append(issue_row)

        issue_columns = list(df_all.columns) + ["ValidationIssueType", "ValidationReason"]
        if not issues:
            return pd.DataFrame(columns=issue_columns)
        return pd.DataFrame(issues, columns=issue_columns)

    for entry_idx, entry in sorted(entries_with_indices, key=lambda item: (item[1]['epoch'], item[0])):
        o = entry['open']
        c = entry['close']

        if entry_idx in assignment_linked_buy_indices:
            continue

        if (not o) and c and c.get('action') == 'Sell':
            close_key = assignment_leg_key(c)
            if close_key and close_key in assignment_linked_sell_keys:
                continue

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

        close_year = determine_close_year(c)
        assignment_info = assignment_links.get(entry_idx)

        strategy_link_id = None
        strategy_event = None
        assignment_status = None
        if assignment_info:
            strategy_link_id = f"SPASSIGN-{(o or c).get('order_id') or entry_idx}"
            strategy_event = "SHORT PUT"
            assignment_status = assignment_info.get("status")

        row_data = build_row_data(
            symbol=(o or c).get('symbol'),
            opening=o,
            closing=c,
            is_sold_put=is_sold_put,
            close_year=close_year,
            strategy_link_id=strategy_link_id,
            strategy_event=strategy_event,
            assignment_status=assignment_status
        )
        rows.append(row_data)
        validation_rows.append(row_data.copy())

        if assignment_info and assignment_info.get("status") == "ASSIGNED_LINKED":
            buy_entry_idx = assignment_info.get("buy_entry_idx")
            if buy_entry_idx is not None:
                linked_buy_entry = combined[buy_entry_idx]
                linked_buy_open = linked_buy_entry.get("open")
                linked_buy_symbol = linked_buy_entry.get("symbol")
                sell_legs = assignment_info.get("sell_legs", [])

                # We use match_trades FIFO logic to pair the assignment buy with its linked sells.
                # To bypass symbol grouping, we use a temporary symbol for matching.
                temp_open = copy.deepcopy(linked_buy_open)
                temp_open['_orig_symbol'] = linked_buy_symbol
                temp_open['symbol'] = "MATCH"
                
                temp_closes = []
                for sl in sell_legs:
                    tc = copy.deepcopy(sl)
                    tc['_orig_symbol'] = tc.get('symbol') or linked_buy_symbol
                    tc['symbol'] = "MATCH"
                    temp_closes.append(tc)
                
                assignment_matches = match_trades([temp_open], temp_closes)
                
                for am in assignment_matches:
                    am_o = am.get("open")
                    am_c = am.get("close")
                    
                    row_symbol = (am_o or am_c).get('_orig_symbol')
                    event = "ASSIGNMENT TRADE"
                    if not am_c:
                        event = "ASSIGNMENT BUY"
                    elif not am_o:
                        event = "ASSIGNMENT SELL"
                    
                    am_close_year = None
                    if am_c:
                        am_close_year = determine_close_year(am_c)
                    if am_close_year is None and c:
                        am_close_year = determine_close_year(c)
                    if am_close_year is None and am_o:
                        am_close_year = determine_close_year(am_o)
                    
                    assignment_row = build_row_data(
                        symbol=row_symbol,
                        opening=am_o,
                        closing=am_c or {},
                        is_sold_put=True,
                        close_year=am_close_year,
                        strategy_link_id=strategy_link_id,
                        strategy_event=event,
                        assignment_status="ASSIGNED_LINKED"
                    )
                    rows.append(assignment_row)
                    validation_rows.append(assignment_row.copy())

    # Convert to a DataFrame
    df_raw = pd.DataFrame(rows)
    validation_df_raw = pd.DataFrame(validation_rows)


    df_raw = annotate_leg_status(df_raw)
    validation_df_raw = annotate_leg_status(validation_df_raw)
    
    # Convert date columns to datetime objects so pandas/openpyxl can handle them as dates
    for col in ["Open Date", "Close Date"]:
        df_raw[col] = pd.to_datetime(df_raw[col], errors='coerce').dt.date
        validation_df_raw[col] = pd.to_datetime(validation_df_raw[col], errors='coerce').dt.date

    validation_issues_df = build_validation_issues(validation_df_raw)

    def normalize_for_row_overlap_key(value):
        if value is None or pd.isna(value):
            return ""
        if isinstance(value, (datetime.date, datetime.datetime)):
            return value.isoformat()

        raw = str(value).strip()
        if raw == "":
            return ""

        try:
            dec = Decimal(raw)
            if dec == dec.to_integral_value():
                return str(int(dec))
            return str(dec.normalize())
        except Exception:
            return raw

    def build_row_overlap_key(row: pd.Series):
        return (
            normalize_for_row_overlap_key(row.get("Symbol")),
            normalize_for_row_overlap_key(row.get("Open Date")),
            normalize_for_row_overlap_key(row.get("Open Action")),
            normalize_for_row_overlap_key(row.get("Open\nQuantity")),
            normalize_for_row_overlap_key(row.get("Open Price")),
            normalize_for_row_overlap_key(row.get("Open Order ID")),
            normalize_for_row_overlap_key(row.get("Close Date")),
            normalize_for_row_overlap_key(row.get("Close Action")),
            normalize_for_row_overlap_key(row.get("Close\nQuantity")),
            normalize_for_row_overlap_key(row.get("Close Price")),
            normalize_for_row_overlap_key(row.get("Close Order ID")),
        )

    validation_overlap_keys = {
        build_row_overlap_key(row)
        for _, row in validation_issues_df.iterrows()
    }

    if validation_overlap_keys:
        df_raw = df_raw[
            ~df_raw.apply(lambda row: build_row_overlap_key(row) in validation_overlap_keys, axis=1)
        ].copy()

    df = sort_for_output(df_raw)
    validation_issues_df = sort_for_output(validation_issues_df)
    
    # Partitioning logic - Dynamic years
    # We want sheets for every year present in the data, plus a 'Current or Open' sheet
    all_years = sorted([y for y in df['_close_year'].unique() if pd.notna(y)], reverse=True)
    
    sheets = []
    
    # For prior-year expired options, suppress stale open-only rows in Current/Open
    # when the same symbol already has at least one closed row.
    current_exclude_mask = pd.Series(False, index=df.index)
    if 'Symbol' in df.columns and 'Close Date' in df.columns:
        symbol_series = df['Symbol'].fillna('').astype(str).str.strip()
        expiration_year_series = symbol_series.apply(
            lambda s: (parse_expiration_date(s).year if parse_expiration_date(s) else None)
        )
        expired_prior_year_mask = expiration_year_series.apply(
            lambda y: pd.notna(y) and int(y) < this_year
        )
        close_present_mask = df['Close Date'].notna()
        symbols_with_closed_expired_prior_year = set(symbol_series[expired_prior_year_mask & close_present_mask])
        current_exclude_mask = (
            expired_prior_year_mask
            & df['Close Date'].isna()
            & symbol_series.isin(symbols_with_closed_expired_prior_year)
        )

    # Always include 'Current or Open' first (it will be Year 2026 if run in 2026, or trades with no close year)
    current_trades = df[(~df['_is_sold_put']) & ((df['_close_year'] == this_year) | (df['_close_year'].isna())) & (~current_exclude_mask)]
    current_puts = df[(df['_is_sold_put']) & ((df['_close_year'] == this_year) | (df['_close_year'].isna())) & (~current_exclude_mask)]
    
    if not current_trades.empty:
        sheets.append((current_trades, "Trades Current or Open"))
    if not current_puts.empty:
        sheets.append((current_puts, "Short Puts Current or Open"))
    
    # Then sheets for each previous year
    for year in all_years:
        if year == this_year:
            continue
        year_trades = df[(~df['_is_sold_put']) & (df['_close_year'] == year)]
        year_puts = df[(df['_is_sold_put']) & (df['_close_year'] == year)]
        if not year_trades.empty:
            sheets.append((year_trades, f"Trades {int(year)}"))
        if not year_puts.empty:
            sheets.append((year_puts, f"Short Puts {int(year)}"))

    # Remove helper columns before writing
    cols_to_drop = ['_is_sold_put', '_close_year']
    
    # Dashboard calculations
    def calculate_summary(df_partition, name):
        if df_partition.empty:
            return {
                "Category": name,
                "Total Trades": 0,
                "Closed Trades": 0,
                "Total P/L": 0.0,
                "Win Rate (Closed)": "N/A",
                "Avg Annualized ROI % (Closed Short Puts)": "N/A",
                "Avg Covered Call Annualized ROI %": "N/A",
                "Avg Long Shares Annualized ROI %": "N/A",
                "Avg Long Options ROI %": "N/A",
                "Avg Long Options Annualized ROI %": "N/A",
                "Median Long Options Annualized ROI %": "N/A",
                "Avg Long Options Annualized ROI % (>=7 Days)": "N/A"
            }
        # P/L = (Open Total In + Open Total Out) + (Close Total In + Close Total Out)
        pl = (df_partition['Open Total Out'].fillna(0) + 
              df_partition['Open Total In'].fillna(0) + 
              df_partition['Close Total In'].fillna(0) + 
              df_partition['Close Total Out'].fillna(0)).sum()
        
        count = len(df_partition)
        
        # Win rate: only for closed trades
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

        closed_short_puts = closed_trades[closed_trades['_is_sold_put'] == True]
        short_put_roi = pd.to_numeric(closed_short_puts['Annualized ROI %'], errors='coerce').dropna()
        avg_annualized_roi = "N/A"
        if len(short_put_roi) > 0:
            avg_annualized_roi = f"{short_put_roi.mean():.2f}%"

        covered_call_roi = pd.to_numeric(closed_trades['Covered Call Annualized ROI %'], errors='coerce').dropna()
        avg_covered_call_roi = "N/A"
        if len(covered_call_roi) > 0:
            avg_covered_call_roi = f"{covered_call_roi.mean():.2f}%"

        long_shares_roi = pd.to_numeric(closed_trades['Long Shares Annualized ROI %'], errors='coerce').dropna()
        avg_long_shares_roi = "N/A"
        if len(long_shares_roi) > 0:
            avg_long_shares_roi = f"{long_shares_roi.mean():.2f}%"

        long_options_roi = pd.to_numeric(closed_trades['Long Options Annualized ROI %'], errors='coerce').dropna()
        avg_long_options_roi = "N/A"
        if len(long_options_roi) > 0:
            avg_long_options_roi = f"{long_options_roi.mean():.2f}%"

        long_options_simple_roi = pd.to_numeric(closed_trades['Long Options ROI %'], errors='coerce').dropna()
        avg_long_options_simple_roi = "N/A"
        if len(long_options_simple_roi) > 0:
            avg_long_options_simple_roi = f"{long_options_simple_roi.mean():.2f}%"

        median_long_options_annualized_roi = "N/A"
        if len(long_options_roi) > 0:
            median_long_options_annualized_roi = f"{long_options_roi.median():.2f}%"

        long_options_annualized_for_min_days = pd.to_numeric(closed_trades['Long Options Annualized ROI %'], errors='coerce')
        open_dates = pd.to_datetime(closed_trades['Open Date'], errors='coerce')
        close_dates = pd.to_datetime(closed_trades['Close Date'], errors='coerce')
        days_held_series = (close_dates - open_dates).dt.days
        min_days_filter = days_held_series >= 7
        avg_long_options_annualized_min_7_days = "N/A"
        if min_days_filter.any():
            eligible_values = long_options_annualized_for_min_days[min_days_filter].dropna()
            if len(eligible_values) > 0:
                avg_long_options_annualized_min_7_days = f"{eligible_values.mean():.2f}%"
            
        return {
            "Category": name,
            "Total Trades": count,
            "Closed Trades": len(closed_trades),
            "Total P/L": round(pl, 2),
            "Win Rate (Closed)": win_rate,
            "Avg Annualized ROI % (Closed Short Puts)": avg_annualized_roi,
            "Avg Covered Call Annualized ROI %": avg_covered_call_roi,
            "Avg Long Shares Annualized ROI %": avg_long_shares_roi,
            "Avg Long Options ROI %": avg_long_options_simple_roi,
            "Avg Long Options Annualized ROI %": avg_long_options_roi,
            "Median Long Options Annualized ROI %": median_long_options_annualized_roi,
            "Avg Long Options Annualized ROI % (>=7 Days)": avg_long_options_annualized_min_7_days
        }

    summary_data = []
    fixed_sheets = []
    for data, name in sheets:
        summary_data.append(calculate_summary(data, name))
        fixed_sheets.append((data, name))
    sheets = fixed_sheets

    # --- Estimated Tax Logic 2026 ---
    # Default assumptions
    tax_2025_total_tax = 0.0
    tax_2026_filing_status = "single"
    tax_2026_withholding_to_date = 0.0
    estimated_tax_rate_2026 = 0.25

    if tax_props:
        try:
            tax_2025_total_tax = float(tax_props.get('tax_2025_total_tax', 0.0))
            tax_2026_filing_status = str(tax_props.get('tax_2026_filing_status', 'single')).lower()
            tax_2026_withholding_to_date = float(tax_props.get('tax_2026_withholding_to_date', 0.0))
            estimated_tax_rate_2026 = float(tax_props.get('tax_2026_estimated_rate', 0.25))
        except (ValueError, TypeError):
            pass

    # Safe Harbor calculation
    # For AGI > $150k ($75k MFS), safe harbor is 110% of prior year tax.
    # Otherwise, it's 100%. We'll assume 110% as the conservative default for traders.
    safe_harbor_percentage = 1.10
    total_safe_harbor_required = tax_2025_total_tax * safe_harbor_percentage
    quarterly_safe_harbor = total_safe_harbor_required / 4.0

    estimated_tax_periods_2026 = [
        {
            "Period": "Q1",
            "Income Earned Window": "January 1 – March 31, 2026",
            "Due Date": "April 15, 2026",
            "start": datetime.date(2026, 1, 1),
            "end": datetime.date(2026, 3, 31),
        },
        {
            "Period": "Q2",
            "Income Earned Window": "April 1 – May 31, 2026",
            "Due Date": "June 15, 2026",
            "start": datetime.date(2026, 4, 1),
            "end": datetime.date(2026, 5, 31),
        },
        {
            "Period": "Q3",
            "Income Earned Window": "June 1 – August 31, 2026",
            "Due Date": "September 15, 2026",
            "start": datetime.date(2026, 6, 1),
            "end": datetime.date(2026, 8, 31),
        },
        {
            "Period": "Q4",
            "Income Earned Window": "September 1 – December 31, 2026",
            "Due Date": "January 15, 2027",
            "start": datetime.date(2026, 9, 1),
            "end": datetime.date(2026, 12, 31),
        },
    ]

    closed_rows = df[df['Close Date'].notna()].copy()
    quarter_rows = []
    for period_def in estimated_tax_periods_2026:
        period_mask = (
            (closed_rows['Close Date'] >= period_def["start"])
            & (closed_rows['Close Date'] <= period_def["end"])
        )
        period_df = closed_rows[period_mask]
        period_income = (
            period_df['Open Total Out'].fillna(0)
            + period_df['Open Total In'].fillna(0)
            + period_df['Close Total In'].fillna(0)
            + period_df['Close Total Out'].fillna(0)
        ).sum()
        taxable_income = max(period_income, 0)
        estimated_tax_due = taxable_income * estimated_tax_rate_2026

        # Safe Harbor Logic: Recommended = max(Quarterly Safe Harbor - Quarterly Withholding, 0)
        # Note: We assume withholding is spread evenly across the year for this calculation,
        # or we could just use it as a global offset. Let's use it as a global offset for now.
        # But per-quarter is more precise if we know the withholding-to-date.
        recommended_safe_harbor_payment = max(quarterly_safe_harbor - (tax_2026_withholding_to_date / 4.0), 0)

        quarter_rows.append({
            "Period": period_def["Period"],
            "Income Earned Window": period_def["Income Earned Window"],
            "Due Date": period_def["Due Date"],
            "Trades": len(period_df),
            "Income Earned (2026)": round(period_income, 2),
            "Estimated Tax Rate": f"{estimated_tax_rate_2026 * 100:.0f}%",
            "Estimated Tax Due": round(estimated_tax_due, 2),
            "Safe Harbor Payment (Est)": round(recommended_safe_harbor_payment, 2),
        })

    summary_df = pd.DataFrame(summary_data)
    tax_df = pd.DataFrame(quarter_rows)

    if validation_issues_df.empty:
        validation_summary_df = pd.DataFrame([
            {
                "Validation Issue Type": "None",
                "Rows": 0,
                "Distinct Symbols": 0,
                "Total Close Quantity": 0,
                "Net Cash Impact": 0.0,
                "Gross Cash Moved": 0.0,
            }
        ])
    else:
        validation_issues_df = validation_issues_df.copy()
        for cash_col in ["Open Total In", "Open Total Out", "Close Total In", "Close Total Out"]:
            validation_issues_df[cash_col] = pd.to_numeric(validation_issues_df[cash_col], errors="coerce").fillna(0.0)
        validation_issues_df["_net_cash_impact"] = (
            validation_issues_df["Open Total In"]
            + validation_issues_df["Open Total Out"]
            + validation_issues_df["Close Total In"]
            + validation_issues_df["Close Total Out"]
        )
        validation_issues_df["_gross_cash_moved"] = (
            validation_issues_df["Open Total In"].abs()
            + validation_issues_df["Open Total Out"].abs()
            + validation_issues_df["Close Total In"].abs()
            + validation_issues_df["Close Total Out"].abs()
        )

        validation_summary_df = (
            validation_issues_df.groupby("ValidationIssueType", dropna=False)
            .agg({
                "Symbol": "nunique",
                "Close\nQuantity": "sum",
                "_net_cash_impact": "sum",
                "_gross_cash_moved": "sum",
            })
            .reset_index()
            .rename(columns={
                "ValidationIssueType": "Validation Issue Type",
                "Symbol": "Distinct Symbols",
                "Close\nQuantity": "Total Close Quantity",
                "_net_cash_impact": "Net Cash Impact",
                "_gross_cash_moved": "Gross Cash Moved",
            })
        )
        issue_counts = validation_issues_df["ValidationIssueType"].value_counts(dropna=False).rename_axis(
            "Validation Issue Type"
        ).reset_index(name="Rows")
        validation_summary_df = issue_counts.merge(validation_summary_df, on="Validation Issue Type", how="left")
        validation_summary_df = validation_summary_df.sort_values(by=["Rows", "Total Close Quantity"], ascending=[False, False])

    accounting_format = '_($* #,##0.00_);_($* (#,##0.00);_($* "-"??_);_(@_)'
    date_format = 'mm/dd/yyyy'  # This maps to Excel's Short Date in many locales
    from openpyxl.styles import Alignment, Font

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        summary_df.to_excel(writer, sheet_name='Dashboard', index=False)
        worksheet = writer.sheets['Dashboard']

        # Add a gap and a title for the tax table
        tax_title_row = len(summary_df) + 3
        worksheet.cell(row=tax_title_row, column=1, value="2026 ESTIMATED TAX PLANNING")
        worksheet.cell(row=tax_title_row, column=1).font = Font(bold=True)

        tax_df.to_excel(writer, sheet_name='Dashboard', index=False, startrow=tax_title_row)
        tax_header_row = tax_title_row + 1

        # Formatting Summary table
        for col_idx, col_name in enumerate(summary_df.columns, 1):
            if col_name == "Total P/L":
                for row_idx in range(2, len(summary_df) + 2):
                    worksheet.cell(row=row_idx, column=col_idx).number_format = accounting_format

            # Auto-wrap headers
            header_cell = worksheet.cell(row=1, column=col_idx)
            if header_cell.value and '\n' in str(header_cell.value):
                header_cell.alignment = Alignment(wrapText=True, horizontal='center', vertical='bottom')

        # Formatting Tax table
        for col_idx, col_name in enumerate(tax_df.columns, 1):
            if col_name in {"Income Earned (2026)", "Estimated Tax Due", "Safe Harbor Payment (Est)"}:
                for row_idx in range(tax_header_row + 1, tax_header_row + 1 + len(tax_df)):
                    worksheet.cell(row=row_idx, column=col_idx).number_format = accounting_format

            # Auto-wrap headers
            header_cell = worksheet.cell(row=tax_header_row, column=col_idx)
            if header_cell.value and '\n' in str(header_cell.value):
                header_cell.alignment = Alignment(wrapText=True, horizontal='center', vertical='bottom')

        # Auto-fit Dashboard columns
        num_dashboard_cols = max(len(summary_df.columns), len(tax_df.columns))
        for col_idx in range(1, num_dashboard_cols + 1):
            max_length = 0
            column_letter = worksheet.cell(row=1, column=col_idx).column_letter
            # Iterate through both tables
            for row_idx in range(1, tax_header_row + 1 + len(tax_df)):
                cell = worksheet.cell(row=row_idx, column=col_idx)
                if cell.value:
                    val_str = str(cell.value)
                    if cell.alignment.wrapText:
                        val_str = max(val_str.split('\n'), key=len)
                    if cell.number_format == accounting_format:
                        val_str = "$#,###,###.00"
                    max_length = max(max_length, len(val_str))
            worksheet.column_dimensions[column_letter].width = max_length + 2

        validation_count = len(validation_issues_df)
        pointer_row = tax_header_row + len(tax_df) + 2
        worksheet.cell(row=pointer_row, column=1, value="Validation Issues")
        worksheet.cell(row=pointer_row, column=1).font = Font(bold=True)
        worksheet.cell(row=pointer_row, column=2, value=validation_count)
        worksheet.cell(
            row=pointer_row,
            column=3,
            value="See 'Validation Issues' and 'Validation Summary' tabs",
        )

        for data, name in sheets:
            df_to_write = data.drop(columns=cols_to_drop)
            df_to_write.to_excel(writer, sheet_name=name, index=False)
            
            # Apply formatting to yearly sheets
            worksheet = writer.sheets[name]
            for col_idx, col_name in enumerate(df_to_write.columns, 1):
                # Price and Total columns
                if "Price" in col_name or "Total" in col_name:
                    for row_idx in range(2, len(df_to_write) + 2):
                        cell = worksheet.cell(row=row_idx, column=col_idx)
                        cell.number_format = accounting_format
                
                # Date columns
                if "Date" in col_name:
                    for row_idx in range(2, len(df_to_write) + 2):
                        cell = worksheet.cell(row=row_idx, column=col_idx)
                        # Setting to 'mm-dd-yy' or 'm/d/yy' often maps to the built-in 
                        # 'Short Date' format (format ID 14) in Excel.
                        cell.number_format = 'm/d/yy'
                
                # Auto-fit column width
                max_length = 0
                column_letter = worksheet.cell(row=1, column=col_idx).column_letter
                # Header length
                header_lines = str(col_name).split('\n')
                max_length = max(max_length, max(len(line) for line in header_lines))
                if len(header_lines) > 1:
                    worksheet.cell(row=1, column=col_idx).alignment = Alignment(wrapText=True, horizontal='center', vertical='bottom')

                # Data length
                for row_idx in range(2, len(df_to_write) + 2):
                    cell_value = worksheet.cell(row=row_idx, column=col_idx).value
                    if cell_value:
                        # For dates and currency, we might want a bit more padding
                        val_str = str(cell_value)
                        if "Date" in col_name:
                            val_str = "MM/DD/YYYY" # typical date length
                        elif ("Price" in col_name or "Total" in col_name or col_name == "Net") and not isinstance(cell_value, str):
                            val_str = "$#,###.00" # typical currency length
                        
                        max_length = max(max_length, len(val_str))
                
                adjusted_width = (max_length + 2)
                worksheet.column_dimensions[column_letter].width = adjusted_width

        validation_to_write = validation_issues_df.drop(columns=cols_to_drop, errors='ignore')
        validation_to_write.to_excel(writer, sheet_name="Validation Issues", index=False)

        validation_sheet = writer.sheets["Validation Issues"]
        for col_idx, col_name in enumerate(validation_to_write.columns, 1):
            if "Price" in col_name or "Total" in col_name:
                for row_idx in range(2, len(validation_to_write) + 2):
                    cell = validation_sheet.cell(row=row_idx, column=col_idx)
                    cell.number_format = accounting_format

            if "Date" in col_name:
                for row_idx in range(2, len(validation_to_write) + 2):
                    cell = validation_sheet.cell(row=row_idx, column=col_idx)
                    cell.number_format = 'm/d/yy'

            max_length = 0
            column_letter = validation_sheet.cell(row=1, column=col_idx).column_letter
            header_lines = str(col_name).split('\n')
            max_length = max(max_length, max(len(line) for line in header_lines))
            if len(header_lines) > 1:
                validation_sheet.cell(row=1, column=col_idx).alignment = Alignment(wrapText=True, horizontal='center', vertical='bottom')

            for row_idx in range(2, len(validation_to_write) + 2):
                cell_value = validation_sheet.cell(row=row_idx, column=col_idx).value
                if cell_value:
                    val_str = str(cell_value)
                    if "Date" in col_name:
                        val_str = "MM/DD/YYYY"
                    elif ("Price" in col_name or "Total" in col_name or col_name == "Net") and not isinstance(cell_value, str):
                        val_str = "$#,###.00"
                    max_length = max(max_length, len(val_str))

            validation_sheet.column_dimensions[column_letter].width = (max_length + 2)

        validation_summary_df.to_excel(writer, sheet_name="Validation Summary", index=False)
        validation_summary_sheet = writer.sheets["Validation Summary"]
        for col_idx, col_name in enumerate(validation_summary_df.columns, 1):
            if col_name in {"Net Cash Impact", "Gross Cash Moved"}:
                for row_idx in range(2, len(validation_summary_df) + 2):
                    cell = validation_summary_sheet.cell(row=row_idx, column=col_idx)
                    cell.number_format = accounting_format
            max_length = len(str(col_name))
            for row_idx in range(2, len(validation_summary_df) + 2):
                cell_value = validation_summary_sheet.cell(row=row_idx, column=col_idx).value
                if cell_value is not None:
                    max_length = max(max_length, len(str(cell_value)))
            validation_summary_sheet.column_dimensions[
                validation_summary_sheet.cell(row=1, column=col_idx).column_letter
            ].width = max_length + 2

    print(f"Excel output saved to {output_file}")


def orders(consumer_key: str, consumer_secret: str, account_id_key: str, tokens: dict, output_file: str = None, tax_props: dict = None):
    """
    Main orchestration logic for fetching and processing orders.

    :param consumer_key: The E*TRADE consumer key.
    :param consumer_secret: The E*TRADE consumer secret.
    :param account_id_key: The E*TRADE account ID key.
    :param tokens: A dictionary containing the E*TRADE OAuth tokens.
    :param output_file: Optional path to the output file.
    :param tax_props: Optional dictionary of properties containing tax parameters.
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

    adjustments = load_adjustments()
    apply_corporate_actions(opens=opens, closes=closes, adjustments=adjustments)

    new_trades = match_trades(opens, closes)
    
    # Bring forward historical trades from previous output
    old_trades = load_previous_output(output_file)
    
    apply_corporate_actions(trades=old_trades, adjustments=adjustments)
    
    # Merge and deduplicate
    combined = merge_and_deduplicate(old_trades, new_trades)

    # Report unmatched expired options to the console
    report_unmatched_expired_trades(combined)

    write_excel_output(combined, output_file, tax_props=tax_props)
