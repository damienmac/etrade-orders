# E*TRADE API Order & Trade Performance Tool

This tool automates the process of capturing E*TRADE order history and calculating trade performance. It transforms raw order data into a multi-sheet Excel report with matched opening and closing trades, a performance dashboard, and automated handling of expired options.

## Key Features

- **Automated Trade Matching:** Automatically pairs opening and closing orders for options and stocks.
- **Performance Dashboard:** A front-page summary of P/L, win rates, and trade counts by year and strategy.
- **Dynamic Yearly Sheets:** Automatically partitions trades into `Trades [Year]` and `Short Puts [Year]` sheets based on the closing date.
- **"Bring Forward" History:** Automatically merges new data with previous Excel (`.xlsx`, `.xlsm`) or CSV reports to build a permanent history beyond E*TRADE's 2-year API limit.
- **Worthless Expiration Handling:** Detects expired options and creates synthetic $0 closing orders to accurately reflect total P/L.
- **Multi-Sheet Excel Output:** Clearly organized reports with "Current or Open" sheets for active and recent trades.

## Prerequisites

- An E*TRADE account
- E*TRADE API keys (consumer key and consumer secret)
- Python 3.6 or higher
- Required Python packages: `pandas`, `openpyxl`, `pyetrade` (install via `pip install -r requirements.txt`)

## Setup Instructions

### 1. Configure API Credentials

Before using this tool, you need to set up your `etrade.properties` file:

1. Copy the template file:
   ```bash
   cp etrade.properties.template etrade.properties
   ```
2. Open `etrade.properties` and enter your credentials:
   ```
   consumer_key = "your_consumer_key_here"
   consumer_secret = "your_consumer_secret_here"
   account_id = "your_account_id_here"
   ```
3. (Optional) Configure the output filename:
   ```
   output_file = "orders_output.xlsx"
   ```

### 2. Generate Authentication Tokens

The E*TRADE API requires OAuth tokens that typically expire every 24 hours:

1. Run the tokens script:
   ```bash
   python tokens.py
   ```
2. Follow the URL in the terminal, authorize the app in your browser, and enter the verification code back into the prompt.
3. This creates `etrade_tokens.py` which is used automatically by the main script.

### 3. Capture and Process Orders

1. Run the main script:
   ```bash
   python main.py
   ```
2. The script will:
   - Load previous history from the most recent `orders_output_YYYY-MM-DD.xlsx` or `orders_output.csv`.
   - Fetch new executed orders from the last 2 years.
   - Match opens and closes, deduplicating using Order IDs and trade fingerprints.
   - Generate a new dated Excel file (e.g., `orders_output_2026-03-29.xlsx`).

## Understanding the Output

### Excel Sheet Structure
- **Dashboard:** High-level summary of performance metrics (Total P/L, Win Rate, Trade Count) for every year and category.
- **Trades [Year]:** All stock and option trades (except Short Puts) closed in that specific year.
- **Short Puts [Year]:** Specifically tracks "Sell Open" put options for that year.
- **Current or Open:** Contains all currently open positions and trades closed in the current calendar year.

### Column Definitions
- **Total In / Total Out:** Raw cash flow for the leg.
- **EXPIRED:** Marked "EXPIRED" for synthetic $0 closing records created for worthless options.
- **Order ID Columns:** Used for robust deduplication when merging historical files.

## Troubleshooting

- **401 Unauthorized Error:** Your tokens have expired. Run `python tokens.py` again.
- **"Bringing Forward" Data:** If you have an old manual spreadsheet, name it `orders_output.csv` in the root directory. The script will automatically migrate its data on the next run.
- **Verification:** Run `python test_tokens_workflow.py` to check your API connection and token status.

## Customization

By default, the tool looks back 2 years for new orders. To change this, you can modify the `two_years_ago` calculation at the top of `orders.py`.
