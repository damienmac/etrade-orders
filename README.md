# E*TRADE API Order & Trade Performance Tool

This tool automates the process of capturing E*TRADE order history and calculating trade performance. It transforms raw order data into a multi-sheet Excel report with matched opening and closing trades, a performance dashboard, automated handling of expired options, and validation views for orphaned historical closes.

## Key Features

- **Automated Trade Matching:** Automatically pairs opening and closing orders for options and stocks.
- **Performance Dashboard:** A front-page summary of P/L, win rates, and trade counts by year and strategy.
- **Dynamic Yearly Sheets:** Automatically partitions trades into `Trades [Year]` and `Short Puts [Year]` sheets based on the closing date.
- **"Bring Forward" History:** Automatically merges new data with previous Excel (`.xlsx`, `.xlsm`) or CSV reports to build a permanent history beyond E*TRADE's 2-year API limit.
- **Worthless Expiration Handling:** Detects expired options and creates synthetic $0 closing orders to accurately reflect total P/L.
- **Multi-Sheet Excel Output:** Clearly organized reports with "Current or Open" sheets for active and recent trades.
- **Validation Issues Detection:** Flags expired historical close legs that do not have enough matching open quantity in the available history (while avoiding false positives from assignment-linked/split-quantity flows).
- **Validation Summary & Dashboard Pointer:** Adds a `Validation Summary` tab and a `Dashboard` pointer row showing validation issue count for quick review.

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
3. (Optional) Set API environment (defaults to production):
   ```
   environment = "production"
   # or: environment = "sandbox"
   # or: use_sandbox = "true"
   ```
4. (Optional) Configure Tax Information (for Estimated Tax Planning):
   ```
   # 2025 total tax from Form 1040, line 24 (used for safe harbor calculation)
   tax_2025_total_tax = 33115.0
   # Expected 2026 filing status (single, mfj, mfs, hoh)
   tax_2026_filing_status = "mfj"
   # Federal income tax withheld so far in 2026
   tax_2026_withholding_to_date = 31567.57
   # Estimated tax rate to use for P/L (as secondary metric)
   tax_2026_estimated_rate = 0.25
   ```
5. (Optional) Configure the output filename:
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
- **Dashboard Validation Pointer:** Includes a quick row showing total validation issue count and where to review details.
- **Dashboard Estimated Taxes 2026:** Adds a dedicated table for 2026 planning with custom period rows (`Q1`–`Q4`) including income windows, due dates, period income, configurable tax rates, and estimated payment amounts.
- **Trades [Year]:** All stock and option trades (except Short Puts) closed in that specific year.
- **Short Puts [Year]:** Specifically tracks "Sell Open" put options for that year.
- **Current or Open:** Contains all currently open positions and trades closed in the current calendar year.
- **Validation Issues:** Lists flagged rows using the same trade row schema as other tabs, with trailing metadata columns (`ValidationIssueType`, `ValidationReason`).
- **Validation Summary:** Aggregates validation results by issue type with counts, distinct symbols, total close quantity, `Net Cash Impact`, and `Gross Cash Moved`.

### Column Definitions
- **Total In / Total Out:** Raw cash flow for the leg.
- **EXPIRED:** Marked "EXPIRED" for synthetic $0 closing records created for worthless options.
- **Order ID Columns:** Used for robust deduplication when merging historical files.
- **Net:** `Open Total In + Open Total Out + Close Total In + Close Total Out`.
- **Cost To Exercise (Short Puts):** `Strike * 100 * Quantity`.
- **Days to Expiration (Short Puts):** `Expiration Date - Open Date` (calendar days).
- **Annualized ROI % (Short Puts):** `Net / Cost To Exercise / Days to Expiration * 365 * 100`.
- **Covered Call Annualized ROI %:** Annualized return for covered-call style matched rows using the strategy-specific capital base used by the tool.
- **Long Shares Annualized ROI %:** Annualized return for long share trades using entry capital and holding period.
- **Long Options ROI %:** Non-annualized return for long option trades using entry premium capital.
- **Long Options Annualized ROI %:** Annualized return for long option trades (`ROI / days held * 365`).
- **Median Long Options Annualized ROI %:** Median of closed long-option annualized ROI values (less outlier-sensitive than mean).
- **Avg Long Options Annualized ROI % (>=7 Days):** Average annualized long-option ROI only for trades held at least 7 days.

### Estimated Taxes 2026 (Dashboard)
- The dashboard includes a dedicated section for IRS estimated-tax periods:
  - `Q1`: January 1 – March 31, 2026 (due April 15, 2026)
  - `Q2`: April 1 – May 31, 2026 (due June 15, 2026)
  - `Q3`: June 1 – August 31, 2026 (due September 15, 2026)
  - `Q4`: September 1 – December 31, 2026 (due January 15, 2027)
- **Income Earned:** Sum of realized trade net cash for rows closed in the period.
- **Estimated Tax (Rate Based):** `max(Income Earned, 0) * tax_2026_estimated_rate`. This is a rough planning metric for your trading income.
- **Safe Harbor Payment (Est):** Calculated as `max(Quarterly Safe Harbor - Quarterly Withholding, 0)`. 
  - **Safe Harbor Method:** Uses the IRS penalty protection rule of paying at least 110% of the prior year's total tax (Form 1040, Line 24).
  - Assumes AGI > $150k for the 110% threshold, common for active traders.
  - Subtraction assumes federal withholding is spread evenly across the year.
- **Note:** These are planning estimates only and not professional tax advice. Safe-harbor calculations are intended to help you avoid underpayment penalties.

## Stock Splits and Corporate Actions

The tool handles stock splits and other contract adjustments (like capital gains distributions) using a configuration file. This ensures that opening trades placed before an adjustment correctly match with closing trades placed after it.

### Configuration
1. Create a file named `adjustments.csv` (or copy `adjustments.csv.template`).
2. Add entries for each corporate action in the following format:
   `Ticker,Date (YYYY-MM-DD),Ratio,StrikeAdj`
   - **Ticker:** The stock symbol.
   - **Date:** The ex-date of the split or adjustment.
   - **Ratio:** The split ratio (e.g., `6` for a 6-for-1 split). Use `1` if there was no quantity change.
   - **StrikeAdj:** The absolute amount subtracted from the strike price (e.g., `8.03759` for TECL). Use `0` if there was no absolute adjustment.

### Examples:
- **Stock Split (6-for-1 for VUG on 2026-04-21):**
  `VUG,2026-04-21,6,0`
- **Capital Gains Strike Adjustment ($8.03759 for TECL on 2025-12-10):**
  `TECL,2025-12-10,1,8.03759`

The tool automatically normalizes quantities, strike prices, and symbols for all trades occurring before the specified date, allowing the FIFO matching engine to pair them seamlessly with post-adjustment data.

## Troubleshooting

- **401 Unauthorized Error:** Your tokens have expired. Run `python tokens.py` again.
- **404 during `python tokens.py`:** Make sure you are using the latest project code and set the correct API environment (`environment = "production"` for PROD keys, `"sandbox"` for SANDBOX keys).
- **"Bringing Forward" Data:** If you have an old manual spreadsheet, name it `orders_output.csv` in the root directory. The script will automatically migrate its data on the next run.
- **Verification:** Run `python test_tokens_workflow.py` to check your API connection and token status.

## Customization

By default, the tool looks back 2 years for new orders. To change this, you can modify the `two_years_ago` calculation at the top of `orders.py`.
