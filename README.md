# E*TRADE API Order Capture Tool

This tool allows you to capture your E*TRADE orders using the E*TRADE API. It retrieves your order history and outputs it in a structured format.

## Prerequisites

- An E*TRADE account
- E*TRADE API keys (consumer key and consumer secret)
- Python 3.6 or higher
- Required Python packages (install via `pip install -r requirements.txt`)

## Setup Instructions

### 1. Configure API Credentials

Before using this tool, you need to edit the `etrade.properties` file with your E*TRADE API credentials:

1. Open `etrade.properties` in a text editor
2. Replace the placeholder values with your actual API credentials:
   ```
   consumer_key = "your_consumer_key_here"
   consumer_secret = "your_consumer_secret_here"
   ```
3. Configure your account ID:
   ```
   account_id = "your_account_id_here"
   ```
4. (Optional) Configure output to a file:
   ```
   output_file = "orders_output.csv"
   ```
5. Save the file

### 2. Generate Authentication Tokens

The E*TRADE API requires OAuth authentication tokens. To generate these tokens:

1. Run the tokens script:
   ```
   python tokens.py
   ```
2. The script will display a URL. Copy this URL and paste it into your web browser.
3. Log in to your E*TRADE account if prompted.
4. Authorize the application when asked.
5. You will receive a verification code. Copy this code.
6. Return to the terminal and paste the verification code when prompted.
7. The script will generate the authentication tokens and save them to `etrade_tokens.py`.

### 3. Capture Orders

After generating the authentication tokens, you can now capture your orders:

1. Run the main script:
   ```
   python main.py
   ```
2. The script will use the tokens from `etrade_tokens.py` to authenticate with the E*TRADE API.
3. It will retrieve your order history and output it in a structured format.

## Workflow Summary

1. Edit `etrade.properties` with your API credentials
2. Run `tokens.py` to generate authentication tokens (saved to `etrade_tokens.py`)
3. Run `main.py` to capture your orders

## Troubleshooting

- If you see a message "Warning: etrade_tokens.py not found", it means you need to run `tokens.py` first.
- Authentication tokens expire after some time. If you encounter authentication errors, regenerate the tokens by running `tokens.py` again.
- Make sure your API credentials in `etrade.properties` are correct and not expired.
- You can run `python test_tokens_workflow.py` to verify that your token workflow is set up correctly.

## Notes

- The authentication tokens are saved to `etrade_tokens.py` and will be automatically used by `main.py`.
- You only need to regenerate tokens when they expire (typically after 24 hours).
- By default, the tool retrieves orders from January 1st of the current year to today. If you need to modify this date range, you can edit the date calculation in `main.py`.
- Output is displayed in CSV format, either to the console or to a file if `output_file` is configured in `etrade.properties`.
