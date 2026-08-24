import unittest
import datetime
import os
import tempfile
from decimal import Decimal

import pandas as pd

from orders import add_expired_worthless_orders, fetch_executed_orders, link_short_put_assignments, load_previous_output, match_trades, merge_and_deduplicate, parse_mmddyyyy, write_excel_output


class OrdersRegressionsTest(unittest.TestCase):
    def test_zero_close_after_expiration_is_not_assignment_unresolved(self):
        combined = [
            {
                "symbol": "HWM Apr 17 '26 $220 Put",
                "epoch": 1,
                "open": {
                    "symbol": "HWM Apr 17 '26 $220 Put",
                    "date": "04/01/2026",
                    "action": "Sell Open",
                    "quantity": 1,
                    "price": Decimal("2.00"),
                    "order_id": 101,
                },
                "close": {
                    "symbol": "HWM Apr 17 '26 $220 Put",
                    "date": "04/18/2026",
                    "action": "Buy Close",
                    "quantity": 1,
                    "price": Decimal("0.00"),
                    "order_id": 102,
                },
            }
        ]

        links = link_short_put_assignments(combined)
        self.assertEqual({}, links)

    def test_zero_close_before_expiration_without_stock_buy_is_unresolved(self):
        combined = [
            {
                "symbol": "KBH May 15 '26 $55 Put",
                "epoch": 1,
                "open": {
                    "symbol": "KBH May 15 '26 $55 Put",
                    "date": "05/01/2026",
                    "action": "Sell Open",
                    "quantity": 1,
                    "price": Decimal("1.00"),
                    "order_id": 201,
                },
                "close": {
                    "symbol": "KBH May 15 '26 $55 Put",
                    "date": "05/12/2026",
                    "action": "Buy Close",
                    "quantity": 1,
                    "price": Decimal("0.00"),
                    "order_id": 202,
                },
            }
        ]

        links = link_short_put_assignments(combined)
        self.assertEqual("ASSIGNED_UNRESOLVED", links[0]["status"])

    def test_nonzero_close_before_expiration_is_not_assignment_candidate(self):
        combined = [
            {
                "symbol": "MBLY May 15 '26 $8 Put",
                "epoch": 1,
                "open": {
                    "symbol": "MBLY May 15 '26 $8 Put",
                    "date": "02/20/2026",
                    "action": "Sell Open",
                    "quantity": 3,
                    "price": Decimal("0.52"),
                    "order_id": 17989,
                },
                "close": {
                    "symbol": "MBLY May 15 '26 $8 Put",
                    "date": "05/11/2026",
                    "action": "Buy Close",
                    "quantity": 3,
                    "price": Decimal("0.01"),
                    "order_id": 18114,
                },
            }
        ]

        links = link_short_put_assignments(combined)
        self.assertEqual({}, links)

    def test_merge_keeps_assignment_stock_buy_when_order_id_is_shared(self):
        new_trades = [
            {
                "symbol": "KB HOME COM",
                "epoch": 1,
                "open": {
                    "symbol": "KB HOME COM",
                    "date": "05/12/2026",
                    "action": "Buy",
                    "quantity": 100,
                    "price": Decimal("55.00"),
                    "order_id": 18122,
                },
                "close": None,
            }
        ]
        old_trades = [
            {
                "symbol": "KBH May 15 '26 $55 Put",
                "epoch": 1,
                "open": None,
                "close": {
                    "symbol": "KBH May 15 '26 $55 Put",
                    "date": "05/12/2026",
                    "action": "Buy Close",
                    "quantity": 1,
                    "price": Decimal("0.00"),
                    "order_id": 18122,
                },
            }
        ]

        combined = merge_and_deduplicate(old_trades, new_trades)

        self.assertEqual(2, len(combined))
        symbols = sorted([trade["symbol"] for trade in combined])
        self.assertEqual(["KB HOME COM", "KBH May 15 '26 $55 Put"], symbols)

    def test_merge_dedupes_same_leg_across_iso_and_mmddyyyy_dates(self):
        new_trades = [
            {
                "symbol": "KB HOME COM",
                "epoch": 1,
                "open": {
                    "symbol": "KB HOME COM",
                    "date": "02/22/2025",
                    "action": "Buy",
                    "quantity": 200,
                    "price": Decimal("80.0"),
                    "order_id": 16329,
                },
                "close": None,
            }
        ]
        old_trades = [
            {
                "symbol": "KB HOME COM",
                "epoch": 1,
                "open": {
                    "symbol": "KB HOME COM",
                    "date": "2025-02-22 00:00:00",
                    "action": "Buy",
                    "quantity": 200,
                    "price": Decimal("80.00"),
                    "order_id": 16329,
                },
                "close": None,
            }
        ]

        combined = merge_and_deduplicate(old_trades, new_trades)

        self.assertEqual(1, len(combined))
        self.assertEqual("KB HOME COM", combined[0]["symbol"])

    def test_merge_keeps_distinct_same_fingerprint_legs_when_order_ids_differ(self):
        symbol = "NVDA Jun 05 '26 $220 Call"
        new_trades = [
            {
                "symbol": symbol,
                "epoch": 1,
                "open": {
                    "symbol": symbol,
                    "date": "05/27/2026",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("4.20"),
                    "order_id": 18158,
                },
                "close": None,
            }
        ]
        old_trades = [
            {
                "symbol": symbol,
                "epoch": 1,
                "open": {
                    "symbol": symbol,
                    "date": "05/27/2026",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("4.20"),
                    "order_id": 18159,
                },
                "close": None,
            }
        ]

        combined = merge_and_deduplicate(old_trades, new_trades)

        self.assertEqual(2, len(combined))
        open_ids = sorted([trade["open"]["order_id"] for trade in combined if trade.get("open")])
        self.assertEqual([18158, 18159], open_ids)

    def test_merge_dedupes_same_order_id_when_old_excel_id_is_float_like_text(self):
        symbol = "NVDA Jun 05 '26 $220 Call"
        new_trades = [
            {
                "symbol": symbol,
                "epoch": 1,
                "open": {
                    "symbol": symbol,
                    "date": "05/27/2026",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("2.67"),
                    "order_id": 18166,
                },
                "close": None,
            }
        ]
        old_trades = [
            {
                "symbol": symbol,
                "epoch": 1,
                "open": {
                    "symbol": symbol,
                    "date": "05/27/2026",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("2.67"),
                    "order_id": "18166.0",
                },
                "close": None,
            }
        ]

        combined = merge_and_deduplicate(old_trades, new_trades)

        self.assertEqual(1, len(combined))
        self.assertEqual(symbol, combined[0]["symbol"])

    def test_merge_dedupes_legacy_no_order_id_row_against_id_backed_row(self):
        symbol = "AMAT Apr 12 '24 $215 Call"
        new_trades = [
            {
                "symbol": symbol,
                "epoch": 1,
                "open": {
                    "symbol": symbol,
                    "date": "04/10/2024",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("2.34"),
                    "order_id": 90001,
                },
                "close": {
                    "symbol": symbol,
                    "date": "04/12/2024",
                    "action": "Sell Close",
                    "quantity": 1,
                    "price": Decimal("2.80"),
                    "order_id": 90002,
                },
            }
        ]
        old_trades = [
            {
                "symbol": symbol,
                "epoch": 1,
                "open": {
                    "symbol": symbol,
                    "date": "04/10/2024",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("2.34"),
                    "order_id": None,
                },
                "close": None,
            }
        ]

        combined = merge_and_deduplicate(old_trades, new_trades)

        self.assertEqual(1, len(combined))
        self.assertIsNotNone(combined[0]["close"])
        self.assertEqual(90001, combined[0]["open"]["order_id"])
        self.assertEqual(90002, combined[0]["close"]["order_id"])

    def test_parse_mmddyyyy_accepts_iso_datetime_text(self):
        parsed = parse_mmddyyyy("2025-02-25 00:00:00")
        self.assertIsNotNone(parsed)
        self.assertEqual("2025-02-25", parsed.isoformat())

    def test_load_previous_output_skips_csv_merge_when_excel_history_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = os.getcwd()
            try:
                os.chdir(temp_dir)

                excel_path = os.path.join(temp_dir, "orders_output_2026-07-05.xlsx")
                excel_rows = pd.DataFrame([
                    {
                        "Symbol": "TSLA Sep 20 '24 $240 Call",
                        "Open Date": "09/16/2024",
                        "Open Action": "Buy Open",
                        "Open Quantity": 2,
                        "Open Price": 1.24,
                        "Open Total Out": 248,
                        "Open Order ID": 15007,
                        "Close Date": "09/17/2024",
                        "Close Action": "Sell Close",
                        "Close Quantity": 2,
                        "Close Price": 2.70,
                        "Close Total In": 540,
                        "Close Order ID": 15031,
                    }
                ])
                with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                    excel_rows.to_excel(writer, sheet_name="Trades 2024", index=False)

                csv_rows = pd.DataFrame([
                    {
                        "Symbol": "TSLA Sep 20 '24 $240 Call",
                        "Open Date": "09/16/2024",
                        "Open Action": "Buy Open",
                        "Open Quantity": 2,
                        "Open Price": 1.24,
                        "Open Total Out": 248,
                        "Close Date": None,
                        "Close Action": None,
                        "Close Quantity": None,
                        "Close Price": None,
                    }
                ])
                csv_rows.to_csv(os.path.join(temp_dir, "orders_output.csv"), index=False)

                loaded = load_previous_output("orders_output.xlsx")

                self.assertEqual(1, len(loaded))
                self.assertIsNotNone(loaded[0]["close"])
                self.assertEqual(15007, loaded[0]["open"]["order_id"])
            finally:
                os.chdir(cwd)

    def test_assignment_stock_buy_is_hidden_from_trades_tab(self):
        year = datetime.datetime.now().year
        trade_date = f"05/12/{year}"
        combined = [
            {
                "symbol": f"KBH May 15 '{str(year)[-2:]} $55 Put",
                "epoch": 1,
                "open": {
                    "symbol": f"KBH May 15 '{str(year)[-2:]} $55 Put",
                    "date": trade_date,
                    "action": "Sell Open",
                    "quantity": 1,
                    "price": Decimal("1.20"),
                    "order_id": 18122,
                },
                "close": {
                    "symbol": f"KBH May 15 '{str(year)[-2:]} $55 Put",
                    "date": trade_date,
                    "action": "Buy Close",
                    "quantity": 1,
                    "price": Decimal("0.00"),
                    "order_id": 18122,
                },
            },
            {
                "symbol": "KB HOME COM (KBH)",
                "epoch": 2,
                "open": {
                    "symbol": "KB HOME COM (KBH)",
                    "date": trade_date,
                    "action": "Buy",
                    "quantity": 100,
                    "price": Decimal("55.00"),
                    "order_id": 18122,
                },
                "close": None,
            },
            {
                "symbol": "AAPL",
                "epoch": 3,
                "open": {
                    "symbol": "AAPL",
                    "date": trade_date,
                    "action": "Buy",
                    "quantity": 1,
                    "price": Decimal("100.00"),
                    "order_id": 99999,
                },
                "close": None,
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            short_puts = pd.read_excel(output_file, sheet_name="Short Puts Current or Open")
            trades = pd.read_excel(output_file, sheet_name="Trades Current or Open")

            self.assertTrue(
                (
                    (short_puts["Strategy Event"] == "ASSIGNMENT BUY")
                    & short_puts["Symbol"].astype(str).str.contains("KB HOME", na=False)
                ).any()
            )
            self.assertFalse(trades["Symbol"].astype(str).str.contains("KB HOME|KBH", na=False).any())
            self.assertTrue(trades["Symbol"].astype(str).str.contains("AAPL", na=False).any())

    def test_historical_assignment_buy_is_written_to_historical_short_put_sheet(self):
        historical_year = datetime.datetime.now().year - 1
        trade_date = f"10/16/{historical_year}"
        option_symbol = f"MLTX Oct 17 '{str(historical_year)[-2:]} $22.5 Put"
        combined = [
            {
                "symbol": option_symbol,
                "epoch": 1,
                "open": {
                    "symbol": option_symbol,
                    "date": trade_date,
                    "action": "Sell Open",
                    "quantity": 1,
                    "price": Decimal("1.20"),
                    "order_id": 17617,
                },
                "close": {
                    "symbol": option_symbol,
                    "date": trade_date,
                    "action": "Buy Close",
                    "quantity": 1,
                    "price": Decimal("0.00"),
                    "order_id": 17617,
                },
            },
            {
                "symbol": "MOONLAKE IMMUNOTHERAPEUTICS CLASS A ORD (MLTX)",
                "epoch": 2,
                "open": {
                    "symbol": "MOONLAKE IMMUNOTHERAPEUTICS CLASS A ORD (MLTX)",
                    "date": trade_date,
                    "action": "Buy",
                    "quantity": 100,
                    "price": Decimal("22.50"),
                    "order_id": 17715,
                },
                "close": None,
            },
            {
                "symbol": "AAPL",
                "epoch": 3,
                "open": {
                    "symbol": "AAPL",
                    "date": f"05/12/{datetime.datetime.now().year}",
                    "action": "Buy",
                    "quantity": 1,
                    "price": Decimal("100.00"),
                    "order_id": 99999,
                },
                "close": None,
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            xls = pd.ExcelFile(output_file)
            historical_sheet = f"Short Puts {historical_year}"
            self.assertIn(historical_sheet, xls.sheet_names)

            short_puts_historical = pd.read_excel(output_file, sheet_name=historical_sheet)
            self.assertTrue(
                (
                    (short_puts_historical["Strategy Event"] == "ASSIGNMENT BUY")
                    & short_puts_historical["Symbol"].astype(str).str.contains("MOONLAKE|MLTX", na=False)
                ).any()
            )

            if "Short Puts Current or Open" in xls.sheet_names:
                short_puts_current = pd.read_excel(output_file, sheet_name="Short Puts Current or Open")
                self.assertFalse(
                    (
                        (short_puts_current["Strategy Event"] == "ASSIGNMENT BUY")
                        & short_puts_current["Symbol"].astype(str).str.contains("MOONLAKE|MLTX", na=False)
                    ).any()
                )

    def test_validation_sheet_flags_expired_orphan_close(self):
        current_year = datetime.datetime.now().year
        expired_year = current_year - 1
        option_symbol = f"MSFT Jan 16 '{str(expired_year)[-2:]} $395 Call"
        close_date = f"01/20/{expired_year}"
        combined = [
            {
                "symbol": option_symbol,
                "epoch": 1,
                "open": None,
                "close": {
                    "symbol": option_symbol,
                    "date": close_date,
                    "action": "Sell Close",
                    "quantity": 2,
                    "price": Decimal("84.98"),
                    "order_id": 17901,
                },
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            validation = pd.read_excel(output_file, sheet_name="Validation Issues")
            self.assertEqual(1, len(validation))
            self.assertEqual("historical_orphan_close", validation.iloc[0]["ValidationIssueType"])
            self.assertEqual("Sell Close", validation.iloc[0]["Close Action"])

    def test_validation_sheet_skips_split_quantity_when_net_balanced(self):
        current_year = datetime.datetime.now().year
        expired_year = current_year - 1
        option_symbol = f"MSFT Jan 16 '{str(expired_year)[-2:]} $405 Call"
        open_date = f"01/05/{expired_year}"
        close_date = f"01/12/{expired_year}"
        combined = [
            {
                "symbol": option_symbol,
                "epoch": 1,
                "open": {
                    "symbol": option_symbol,
                    "date": open_date,
                    "action": "Sell Open",
                    "quantity": 2,
                    "price": Decimal("100.00"),
                    "order_id": 17001,
                },
                "close": {
                    "symbol": option_symbol,
                    "date": close_date,
                    "action": "Buy Close",
                    "quantity": 1,
                    "price": Decimal("75.08"),
                    "order_id": 17002,
                },
            },
            {
                "symbol": option_symbol,
                "epoch": 2,
                "open": None,
                "close": {
                    "symbol": option_symbol,
                    "date": close_date,
                    "action": "Buy Close",
                    "quantity": 1,
                    "price": Decimal("70.00"),
                    "order_id": 17003,
                },
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            validation = pd.read_excel(output_file, sheet_name="Validation Issues")
            self.assertTrue(validation.empty)

    def test_validation_sheet_skips_current_year_orphan_close(self):
        current_year = datetime.datetime.now().year
        option_symbol = f"VUG Jun 18 '{str(current_year)[-2:]} $49.17 Put"
        close_date = f"06/19/{current_year}"
        combined = [
            {
                "symbol": option_symbol,
                "epoch": 1,
                "open": None,
                "close": {
                    "symbol": option_symbol,
                    "date": close_date,
                    "action": "Buy Close",
                    "quantity": 1,
                    "price": Decimal("0.00"),
                    "order_id": 18056,
                },
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            validation = pd.read_excel(output_file, sheet_name="Validation Issues")
            self.assertTrue(validation.empty)

            xls = pd.ExcelFile(output_file)
            self.assertIn("Trades Current or Open", xls.sheet_names)
            current_trades = pd.read_excel(output_file, sheet_name="Trades Current or Open")
            self.assertTrue((current_trades["Symbol"].astype(str) == option_symbol).any())

    def test_historical_orphan_close_is_only_on_validation_sheet_not_year_sheet(self):
        current_year = datetime.datetime.now().year
        expired_year = current_year - 2
        option_symbol = f"DNUT Nov 15 '{str(expired_year)[-2:]} $15 Call"
        close_date = f"09/20/{expired_year}"
        combined = [
            {
                "symbol": option_symbol,
                "epoch": 1,
                "open": None,
                "close": {
                    "symbol": option_symbol,
                    "date": close_date,
                    "action": "Buy Close",
                    "quantity": 2,
                    "price": Decimal("0.18"),
                    "total_out": Decimal("35.00"),
                    "order_id": 15069,
                },
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            validation = pd.read_excel(output_file, sheet_name="Validation Issues")
            self.assertEqual(1, len(validation))
            self.assertEqual(option_symbol, validation.iloc[0]["Symbol"])
            self.assertEqual("historical_orphan_close", validation.iloc[0]["ValidationIssueType"])

            xls = pd.ExcelFile(output_file)
            year_sheet = f"Trades {expired_year}"
            if year_sheet in xls.sheet_names:
                trades_year = pd.read_excel(output_file, sheet_name=year_sheet)
                self.assertFalse((trades_year["Symbol"].astype(str) == option_symbol).any())

    def test_validation_summary_includes_cash_totals(self):
        current_year = datetime.datetime.now().year
        expired_year = current_year - 1
        option_symbol = f"MSFT Jan 16 '{str(expired_year)[-2:]} $395 Call"
        close_date = f"01/20/{expired_year}"
        combined = [
            {
                "symbol": option_symbol,
                "epoch": 1,
                "open": None,
                "close": {
                    "symbol": option_symbol,
                    "date": close_date,
                    "action": "Sell Close",
                    "quantity": 2,
                    "price": Decimal("84.98"),
                    "total_in": Decimal("16996.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 17901,
                },
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            summary = pd.read_excel(output_file, sheet_name="Validation Summary")
            self.assertIn("Net Cash Impact", summary.columns)
            self.assertIn("Gross Cash Moved", summary.columns)
            self.assertEqual(16996.00, float(summary.iloc[0]["Net Cash Impact"]))
            self.assertEqual(16996.00, float(summary.iloc[0]["Gross Cash Moved"]))

    def test_real_zero_dollar_close_after_expiration_marks_expired(self):
        current_year = datetime.datetime.now().year
        option_symbol = f"TSCO Jan 17 '{str(current_year)[-2:]} $55 Call"
        combined = [
            {
                "symbol": option_symbol,
                "epoch": 1,
                "open": {
                    "symbol": option_symbol,
                    "date": f"01/10/{current_year}",
                    "action": "Sell Open",
                    "quantity": 1,
                    "price": Decimal("1.10"),
                    "total_in": Decimal("110.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 18101,
                },
                "close": {
                    "symbol": option_symbol,
                    "date": f"01/18/{current_year}",
                    "action": "Buy Close",
                    "quantity": 1,
                    "price": Decimal("0.00"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 18102,
                },
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            current_or_open = pd.read_excel(output_file, sheet_name="Trades Current or Open")
            row = current_or_open[current_or_open["Symbol"].astype(str) == option_symbol].iloc[0]
            self.assertEqual("EXPIRED", row["EXPIRED"])

    def test_real_zero_dollar_close_after_expiration_marks_expired_for_short_call_and_short_put(self):
        current_year = datetime.datetime.now().year
        short_call_symbol = f"TSCO Jan 17 '{str(current_year)[-2:]} $55 Call"
        short_put_symbol = f"TSCO Jan 17 '{str(current_year)[-2:]} $45 Put"
        combined = [
            {
                "symbol": short_call_symbol,
                "epoch": 1,
                "open": {
                    "symbol": short_call_symbol,
                    "date": f"01/10/{current_year}",
                    "action": "Sell Open",
                    "quantity": 1,
                    "price": Decimal("1.10"),
                    "total_in": Decimal("110.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 18111,
                },
                "close": {
                    "symbol": short_call_symbol,
                    "date": f"01/18/{current_year}",
                    "action": "Buy Close",
                    "quantity": 1,
                    "price": Decimal("0.00"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 18112,
                },
            },
            {
                "symbol": short_put_symbol,
                "epoch": 2,
                "open": {
                    "symbol": short_put_symbol,
                    "date": f"01/10/{current_year}",
                    "action": "Sell Open",
                    "quantity": 1,
                    "price": Decimal("0.90"),
                    "total_in": Decimal("90.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 18121,
                },
                "close": {
                    "symbol": short_put_symbol,
                    "date": f"01/18/{current_year}",
                    "action": "Buy Close",
                    "quantity": 1,
                    "price": Decimal("0.00"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 18122,
                },
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            current_or_open = pd.read_excel(output_file, sheet_name="Trades Current or Open")
            call_row = current_or_open[current_or_open["Symbol"].astype(str) == short_call_symbol].iloc[0]
            short_put_sheets = [s for s in pd.ExcelFile(output_file).sheet_names if s.startswith("Short Puts ")]
            self.assertTrue(short_put_sheets)
            short_put_rows = pd.read_excel(output_file, sheet_name=short_put_sheets[0])
            put_row = short_put_rows[short_put_rows["Symbol"].astype(str) == short_put_symbol].iloc[0]
            self.assertEqual("EXPIRED", call_row["EXPIRED"])
            self.assertEqual("EXPIRED", put_row["EXPIRED"])

    def test_expired_worthless_generation_is_quantity_aware_for_uneven_legs(self):
        expired_symbol = "NVDA Jun 05 '20 $220 Call"
        opens = [
            {
                "symbol": expired_symbol,
                "date": "05/22/2020",
                "epoch": 1,
                "action": "Buy Open",
                "quantity": 1,
                "price": Decimal("1.00"),
                "order_id": 90101,
            },
            {
                "symbol": expired_symbol,
                "date": "05/27/2020",
                "epoch": 2,
                "action": "Buy Open",
                "quantity": 1,
                "price": Decimal("1.10"),
                "order_id": 90102,
            },
            {
                "symbol": expired_symbol,
                "date": "05/27/2020",
                "epoch": 3,
                "action": "Buy Open",
                "quantity": 1,
                "price": Decimal("1.20"),
                "order_id": 90103,
            },
        ]
        closes = [
            {
                "symbol": expired_symbol,
                "date": "06/01/2020",
                "epoch": 4,
                "action": "Sell Close",
                "quantity": 3,
                "price": Decimal("2.00"),
                "order_id": 90201,
            }
        ]

        add_expired_worthless_orders(opens, closes)

        synthetic = [c for c in closes if str(c.get("order_id", "")).startswith("SYNTH-")]
        self.assertEqual([], synthetic)

    def test_synthetic_buy_close_logs_error(self):
        expired_symbol = "NVDA Jun 05 '20 $220 Call"
        opens = [
            {
                "symbol": expired_symbol,
                "date": "05/22/2020",
                "epoch": 1,
                "action": "Sell Open",
                "quantity": 1,
                "price": Decimal("1.00"),
                "order_id": 90301,
            }
        ]
        closes = []

        with self.assertLogs("orders", level="ERROR") as logs:
            add_expired_worthless_orders(opens, closes)

        synthetic_buy_closes = [
            c for c in closes
            if c.get("action") == "Buy Close" and str(c.get("order_id", "")).startswith("SYNTH-")
        ]
        self.assertEqual(1, len(synthetic_buy_closes))
        self.assertTrue(any("Synthetic Buy Close created" in message for message in logs.output))

    def test_synthetic_sell_close_logs_error(self):
        expired_symbol = "NVDA Jun 05 '20 $220 Call"
        opens = [
            {
                "symbol": expired_symbol,
                "date": "05/22/2020",
                "epoch": 1,
                "action": "Buy Open",
                "quantity": 1,
                "price": Decimal("1.00"),
                "order_id": 90351,
            }
        ]
        closes = []

        with self.assertLogs("orders", level="ERROR") as logs:
            add_expired_worthless_orders(opens, closes)

        synthetic_sell_closes = [
            c for c in closes
            if c.get("action") == "Sell Close" and str(c.get("order_id", "")).startswith("SYNTH-")
        ]
        self.assertEqual(1, len(synthetic_sell_closes))
        self.assertTrue(any("Synthetic Sell Close created" in message for message in logs.output))

    def test_leg_status_marks_multi_open_with_aggregated_close(self):
        current_year = datetime.datetime.now().year
        symbol = f"LMND Mar 20 '{str(current_year)[-2:]} $60 Call"
        combined = [
            {
                "symbol": symbol,
                "epoch": 1,
                "open": {
                    "symbol": symbol,
                    "date": f"03/10/{current_year}",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("1.50"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-150.00"),
                    "order_id": 18019,
                },
                "close": None,
            },
            {
                "symbol": symbol,
                "epoch": 2,
                "open": {
                    "symbol": symbol,
                    "date": f"03/11/{current_year}",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("1.10"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-110.00"),
                    "order_id": 18023,
                },
                "close": None,
            },
            {
                "symbol": symbol,
                "epoch": 3,
                "open": {
                    "symbol": symbol,
                    "date": f"03/10/{current_year}",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("1.60"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-160.00"),
                    "order_id": 18017,
                },
                "close": {
                    "symbol": symbol,
                    "date": f"03/16/{current_year}",
                    "action": "Sell Close",
                    "quantity": 3,
                    "price": Decimal("1.70"),
                    "total_in": Decimal("510.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 18088,
                },
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            trades = pd.read_excel(output_file, sheet_name="Trades Current or Open")
            rows = trades[trades["Symbol"].astype(str) == symbol]
            self.assertEqual(3, len(rows))
            self.assertIn("Leg Status", rows.columns)
            self.assertTrue(rows["Leg Status"].astype(str).str.contains("MULTI_LEG_AGGREGATED_CLOSE", na=False).all())
            self.assertIn("Close Order ID", rows.columns)
            self.assertEqual({18088}, set(rows["Close Order ID"].dropna().astype(int).tolist()))

            open_only_rows = rows[rows["Close Action"].isna()]
            self.assertEqual(2, len(open_only_rows))
            self.assertTrue(open_only_rows["Leg Status"].astype(str).str.contains("OPEN_WITHOUT_CLOSE", na=False).all())
            self.assertTrue((open_only_rows["Close Order ID"].dropna().astype(int) == 18088).all())

    def test_multi_open_rows_are_consecutive_with_close_on_last_row(self):
        symbol = "NVDA Jun 05 '30 $220 Call"
        current_year = datetime.datetime.now().year
        opens = [
            {
                "symbol": symbol,
                "date": f"05/22/{current_year}",
                "epoch": 1,
                "action": "Buy Open",
                "quantity": 1,
                "price": Decimal("1.00"),
                "total_in": Decimal("0.00"),
                "total_out": Decimal("-100.00"),
                "order_id": 90401,
            },
            {
                "symbol": symbol,
                "date": f"05/27/{current_year}",
                "epoch": 2,
                "action": "Buy Open",
                "quantity": 1,
                "price": Decimal("1.10"),
                "total_in": Decimal("0.00"),
                "total_out": Decimal("-110.00"),
                "order_id": 90402,
            },
            {
                "symbol": symbol,
                "date": f"05/28/{current_year}",
                "epoch": 3,
                "action": "Buy Open",
                "quantity": 1,
                "price": Decimal("1.20"),
                "total_in": Decimal("0.00"),
                "total_out": Decimal("-120.00"),
                "order_id": 90403,
            },
        ]
        closes = [
            {
                "symbol": symbol,
                "date": f"06/01/{current_year}",
                "epoch": 4,
                "action": "Sell Close",
                "quantity": 3,
                "price": Decimal("2.00"),
                "total_in": Decimal("600.00"),
                "total_out": Decimal("0.00"),
                "order_id": 90411,
            }
        ]

        combined = match_trades(opens.copy(), closes.copy())

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            trades = pd.read_excel(output_file, sheet_name="Trades Current or Open").rename(columns=lambda c: c.replace("\n", " "))
            rows = trades[trades["Symbol"].astype(str) == symbol].copy()
            self.assertEqual(3, len(rows))
            self.assertEqual([90401, 90402, 90403], rows["Open Order ID"].tolist())
            self.assertTrue(pd.isna(rows.iloc[0]["Close Quantity"]))
            self.assertTrue(pd.isna(rows.iloc[1]["Close Quantity"]))
            self.assertEqual(3, int(rows.iloc[2]["Close Quantity"]))

    def test_fetch_executed_orders_buy_close_is_negative_cash_flow(self):
        class FakeOrderApi:
            def list_orders(self, account_id_key, marker, count, from_date, to_date):
                return {
                    "OrdersResponse": {
                        "Order": [
                            {
                                "orderId": 20001,
                                "OrderDetail": [
                                    {
                                        "status": "EXECUTED",
                                        "executedTime": 1700000000000,
                                        "Instrument": [
                                            {
                                                "symbolDescription": "MSFT Jan 16 '25 $395 Call",
                                                "orderAction": "BUY_CLOSE",
                                                "filledQuantity": 2,
                                                "averageExecutionPrice": "84.98",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                        "marker": None,
                    }
                }

        opens, closes = fetch_executed_orders(
            etrade_order=FakeOrderApi(),
            account_id_key="dummy",
            from_dt=datetime.datetime.now() - datetime.timedelta(days=30),
            to_dt=datetime.datetime.now(),
            action_mapping={
                "BUY_CLOSE": "Buy Close",
                "BUY_OPEN": "Buy Open",
                "SELL_CLOSE": "Sell Close",
                "SELL_OPEN": "Sell Open",
                "BUY": "Buy",
                "SELL": "Sell",
            },
        )

        self.assertEqual(0, len(opens))
        self.assertEqual(1, len(closes))
        self.assertEqual("Buy Close", closes[0]["action"])
        self.assertEqual(Decimal("0"), closes[0]["total_in"])
        self.assertEqual(Decimal("-16996.00"), closes[0]["total_out"])

    def test_trades_sheet_is_sorted_by_close_date_then_symbol(self):
        current_year = datetime.datetime.now().year
        combined = [
            {
                "symbol": "ZZZ",
                "epoch": 3,
                "open": {
                    "symbol": "ZZZ",
                    "date": f"01/01/{current_year}",
                    "action": "Buy",
                    "quantity": 1,
                    "price": Decimal("100.00"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-100.00"),
                    "order_id": 30001,
                },
                "close": {
                    "symbol": "ZZZ",
                    "date": f"03/01/{current_year}",
                    "action": "Sell",
                    "quantity": 1,
                    "price": Decimal("110.00"),
                    "total_in": Decimal("110.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 30002,
                },
            },
            {
                "symbol": "AAA",
                "epoch": 1,
                "open": {
                    "symbol": "AAA",
                    "date": f"01/15/{current_year}",
                    "action": "Buy",
                    "quantity": 1,
                    "price": Decimal("100.00"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-100.00"),
                    "order_id": 30003,
                },
                "close": {
                    "symbol": "AAA",
                    "date": f"02/01/{current_year}",
                    "action": "Sell",
                    "quantity": 1,
                    "price": Decimal("120.00"),
                    "total_in": Decimal("120.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 30004,
                },
            },
            {
                "symbol": "MMM",
                "epoch": 2,
                "open": {
                    "symbol": "MMM",
                    "date": f"02/15/{current_year}",
                    "action": "Buy",
                    "quantity": 1,
                    "price": Decimal("50.00"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-50.00"),
                    "order_id": 30005,
                },
                "close": None,
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            trades = pd.read_excel(output_file, sheet_name="Trades Current or Open")
            self.assertEqual(["AAA", "ZZZ", "MMM"], trades["Symbol"].tolist())

    def test_expired_option_open_only_duplicate_is_removed_when_closed_row_exists(self):
        expired_symbol = "GOOGL Jun 21 '24 $180 Call"
        old_trades = [
            {
                "symbol": expired_symbol,
                "epoch": 1,
                "open": {
                    "symbol": expired_symbol,
                    "date": "06/01/2024",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("5.00"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-500.00"),
                    "order_id": 41001,
                },
                "close": {
                    "symbol": expired_symbol,
                    "date": "06/15/2024",
                    "action": "Sell Close",
                    "quantity": 1,
                    "price": Decimal("6.00"),
                    "total_in": Decimal("600.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 41002,
                },
            }
        ]
        new_trades = [
            {
                "symbol": expired_symbol,
                "epoch": 2,
                "open": {
                    "symbol": expired_symbol,
                    "date": "06/01/2024",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("5.00"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-500.00"),
                    "order_id": 41011,
                },
                "close": None,
            }
        ]

        combined = merge_and_deduplicate(old_trades, new_trades)

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            xls = pd.ExcelFile(output_file)
            self.assertNotIn("Trades Current or Open", xls.sheet_names)
            historical_sheet = [s for s in xls.sheet_names if s.startswith("Trades ") and s != "Trades Current or Open"]
            self.assertTrue(historical_sheet)
            historical_trades = pd.read_excel(output_file, sheet_name=historical_sheet[0])

            self.assertTrue(historical_trades["Symbol"].astype(str).eq(expired_symbol).any())

    def test_expired_option_unbalanced_multi_open_close_does_not_leave_current_open_duplicate(self):
        expired_symbol = "GOOGL Jun 21 '24 $180 Call"
        old_trades = [
            {
                "symbol": expired_symbol,
                "epoch": 1,
                "open": {
                    "symbol": expired_symbol,
                    "date": "04/26/2024",
                    "action": "Buy Open",
                    "quantity": 5,
                    "price": Decimal("3.68"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-1840.00"),
                    "order_id": 51001,
                },
                "close": {
                    "symbol": expired_symbol,
                    "date": "05/13/2024",
                    "action": "Sell Close",
                    "quantity": 5,
                    "price": Decimal("1.70"),
                    "total_in": Decimal("850.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 51002,
                },
            },
            {
                "symbol": expired_symbol,
                "epoch": 2,
                "open": {
                    "symbol": expired_symbol,
                    "date": "04/30/2024",
                    "action": "Buy Open",
                    "quantity": 10,
                    "price": Decimal("2.38"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-2380.00"),
                    "order_id": 51003,
                },
                "close": {
                    "symbol": expired_symbol,
                    "date": "05/13/2024",
                    "action": "Sell Close",
                    "quantity": 5,
                    "price": Decimal("1.80"),
                    "total_in": Decimal("900.00"),
                    "total_out": Decimal("0.00"),
                    "order_id": 51004,
                },
            },
        ]
        new_trades = [
            {
                "symbol": expired_symbol,
                "epoch": 3,
                "open": {
                    "symbol": expired_symbol,
                    "date": "05/06/2024",
                    "action": "Buy Open",
                    "quantity": 5,
                    "price": Decimal("1.87"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-935.00"),
                    "order_id": 51011,
                },
                "close": None,
            },
            {
                "symbol": expired_symbol,
                "epoch": 4,
                "open": {
                    "symbol": expired_symbol,
                    "date": "05/10/2024",
                    "action": "Buy Open",
                    "quantity": 5,
                    "price": Decimal("1.82"),
                    "total_in": Decimal("0.00"),
                    "total_out": Decimal("-910.00"),
                    "order_id": 51012,
                },
                "close": None,
            },
        ]

        combined = merge_and_deduplicate(old_trades, new_trades)

        with tempfile.TemporaryDirectory() as temp_dir:
            out_base = os.path.join(temp_dir, "orders_output.csv")
            write_excel_output(combined, out_base)
            output_file = os.path.join(temp_dir, f"orders_output_{datetime.datetime.now().strftime('%Y-%m-%d')}.xlsx")

            xls = pd.ExcelFile(output_file)
            symbol_rows = 0
            current_symbol_rows = 0
            for sheet_name in xls.sheet_names:
                if not sheet_name.startswith("Trades "):
                    continue
                sheet_df = pd.read_excel(output_file, sheet_name=sheet_name)
                if "Symbol" not in sheet_df.columns:
                    continue
                matches = int(sheet_df["Symbol"].astype(str).eq(expired_symbol).sum())
                symbol_rows += matches
                if sheet_name == "Trades Current or Open":
                    current_symbol_rows += matches

            self.assertGreaterEqual(symbol_rows, 2)
            self.assertEqual(0, current_symbol_rows)

            historical_sheet = [s for s in xls.sheet_names if s.startswith("Trades ") and s != "Trades Current or Open"]
            self.assertTrue(historical_sheet)
            historical_trades = pd.read_excel(output_file, sheet_name=historical_sheet[0])
            self.assertTrue(historical_trades["Symbol"].astype(str).eq(expired_symbol).any())

    def test_expired_symbol_keeps_distinct_open_rows_when_only_some_are_closed(self):
        expired_symbol = "NVDA Jun 05 '26 $220 Call"
        old_trades = [
            {
                "symbol": expired_symbol,
                "epoch": 1,
                "open": {
                    "symbol": expired_symbol,
                    "date": "05/22/2026",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("4.10"),
                    "order_id": 71001,
                },
                "close": None,
            },
            {
                "symbol": expired_symbol,
                "epoch": 2,
                "open": {
                    "symbol": expired_symbol,
                    "date": "05/27/2026",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("3.95"),
                    "order_id": 71002,
                },
                "close": None,
            },
        ]
        new_trades = [
            {
                "symbol": expired_symbol,
                "epoch": 3,
                "open": {
                    "symbol": expired_symbol,
                    "date": "05/27/2026",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("3.85"),
                    "order_id": 71003,
                },
                "close": {
                    "symbol": expired_symbol,
                    "date": "06/01/2026",
                    "action": "Sell Close",
                    "quantity": 3,
                    "price": Decimal("5.20"),
                    "order_id": 71010,
                },
            },
        ]

        combined = merge_and_deduplicate(old_trades, new_trades)

        nvda_rows = [
            row for row in combined
            if str(row.get("symbol", "")).strip() == expired_symbol
        ]
        self.assertEqual(3, len(nvda_rows))
        self.assertEqual(3, sum(1 for row in nvda_rows if row.get("open")))
        self.assertEqual(1, sum(1 for row in nvda_rows if row.get("close")))

    def test_expired_symbol_prefers_real_close_over_synthetic_for_same_open_leg(self):
        expired_symbol = "TSLA Sep 20 '24 $240 Call"
        duplicated_open = {
            "symbol": expired_symbol,
            "date": "09/16/2024",
            "action": "Buy Open",
            "quantity": 2,
            "price": Decimal("1.42"),
            "order_id": 15005,
        }
        combined = merge_and_deduplicate(
            old_trades=[
                {
                    "symbol": expired_symbol,
                    "epoch": 1,
                    "open": duplicated_open,
                    "close": {
                        "symbol": expired_symbol,
                        "date": "09/17/2024",
                        "action": "Sell Close",
                        "quantity": 4,
                        "price": Decimal("2.70"),
                        "order_id": 15031,
                    },
                },
                {
                    "symbol": expired_symbol,
                    "epoch": 2,
                    "open": dict(duplicated_open),
                    "close": {
                        "symbol": expired_symbol,
                        "date": "09/20/2024",
                        "action": "Sell Close",
                        "quantity": 2,
                        "price": Decimal("0.00"),
                        "order_id": "SYNTH-TSLA Sep 20 '24 $240 Call-20240920-Sell Close",
                        "is_expired": True,
                    },
                },
            ],
            new_trades=[],
        )

        tsla_rows = [
            row for row in combined
            if str(row.get("symbol", "")).strip() == expired_symbol
        ]

        self.assertEqual(1, len(tsla_rows))
        self.assertEqual(15031, tsla_rows[0]["close"]["order_id"])

    def test_expired_prior_year_symbol_drops_open_only_when_any_close_exists(self):
        expired_symbol = "TSLA Sep 20 '24 $240 Call"
        combined = merge_and_deduplicate(
            old_trades=[
                {
                    "symbol": expired_symbol,
                    "epoch": 1,
                    "open": {
                        "symbol": expired_symbol,
                        "date": "09/16/2024",
                        "action": "Buy Open",
                        "quantity": 2,
                        "price": Decimal("1.24"),
                        "order_id": 15007,
                    },
                    "close": None,
                },
                {
                    "symbol": expired_symbol,
                    "epoch": 2,
                    "open": {
                        "symbol": expired_symbol,
                        "date": "09/16/2024",
                        "action": "Buy Open",
                        "quantity": 2,
                        "price": Decimal("1.42"),
                        "order_id": 15005,
                    },
                    "close": {
                        "symbol": expired_symbol,
                        "date": "09/17/2024",
                        "action": "Sell Close",
                        "quantity": 4,
                        "price": Decimal("2.70"),
                        "order_id": 15031,
                    },
                },
            ],
            new_trades=[],
        )

        tsla_rows = [
            row for row in combined
            if str(row.get("symbol", "")).strip() == expired_symbol
        ]
        self.assertEqual(1, len(tsla_rows))
        self.assertTrue(tsla_rows[0].get("open"))
        self.assertTrue(tsla_rows[0].get("close"))
        self.assertEqual(15005, tsla_rows[0]["open"]["order_id"])
        self.assertEqual(15031, tsla_rows[0]["close"]["order_id"])

    def test_current_open_sheet_excludes_expired_prior_year_open_only_when_symbol_has_close(self):
        expired_symbol = "TMUS Jul 26 '24 $182.50 Call"
        combined = [
            {
                "symbol": expired_symbol,
                "epoch": 1,
                "open": {
                    "symbol": expired_symbol,
                    "date": "07/23/2024",
                    "action": "Buy Open",
                    "quantity": 2,
                    "price": Decimal("3.07"),
                    "order_id": 14442,
                },
                "close": None,
            },
            {
                "symbol": expired_symbol,
                "epoch": 2,
                "open": {
                    "symbol": expired_symbol,
                    "date": "07/22/2024",
                    "action": "Buy Open",
                    "quantity": 1,
                    "price": Decimal("3.38"),
                    "order_id": 14423,
                },
                "close": {
                    "symbol": expired_symbol,
                    "date": "07/24/2024",
                    "action": "Sell Close",
                    "quantity": 5,
                    "price": Decimal("1.08"),
                    "order_id": 14458,
                },
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "orders_output.xlsx")
            write_excel_output(combined, output_path)
            xlsx_files = [
                name for name in os.listdir(temp_dir)
                if name.startswith("orders_output") and name.endswith(".xlsx")
            ]
            self.assertTrue(xlsx_files, "Expected an .xlsx output file to be created")
            generated_path = os.path.join(temp_dir, xlsx_files[0])

            xls = pd.ExcelFile(generated_path)
            if "Trades Current or Open" in xls.sheet_names:
                current_df = pd.read_excel(generated_path, sheet_name="Trades Current or Open")
                current_df.columns = [col.replace("\n", " ") for col in current_df.columns]
                self.assertTrue("Symbol" in current_df.columns)
                self.assertFalse((current_df["Symbol"].astype(str) == expired_symbol).any())

            yearly_df = pd.read_excel(generated_path, sheet_name="Trades 2024")
            yearly_df.columns = [col.replace("\n", " ") for col in yearly_df.columns]
            yearly_rows = yearly_df[yearly_df["Symbol"].astype(str) == expired_symbol]
            self.assertEqual(1, len(yearly_rows))
            self.assertEqual(14423, int(yearly_rows.iloc[0]["Open Order ID"]))
            self.assertEqual(14458, int(yearly_rows.iloc[0]["Close Order ID"]))


if __name__ == "__main__":
    unittest.main()
