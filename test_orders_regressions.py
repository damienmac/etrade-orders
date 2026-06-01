import unittest
import datetime
import os
import tempfile
from decimal import Decimal

import pandas as pd

from orders import fetch_executed_orders, link_short_put_assignments, merge_and_deduplicate, parse_mmddyyyy, write_excel_output


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

    def test_parse_mmddyyyy_accepts_iso_datetime_text(self):
        parsed = parse_mmddyyyy("2025-02-25 00:00:00")
        self.assertIsNotNone(parsed)
        self.assertEqual("2025-02-25", parsed.isoformat())

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


if __name__ == "__main__":
    unittest.main()
