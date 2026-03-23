import sys
from properties import load_properties
from account_info import get_account_info
from orders import orders

# Try to import tokens from etrade_tokens.py
try:
    from etrade_tokens import tokens
    print("Using tokens from etrade_tokens.py")
except ImportError:
    print("Error: etrade_tokens.py not found. Please run tokens.py first to generate tokens.")
    tokens = {}  # Define for linting purposes before exiting
    sys.exit(1)


def main():
    """
    Entry point for the script. Loads and validates properties before starting the order processing.
    """
    # Get properties from the file
    properties = load_properties()
    if not properties:
        print("Error: Failed to load properties. Please check your etrade.properties file.")
        sys.exit(1)

    consumer_key = properties.get('consumer_key')
    consumer_secret = properties.get('consumer_secret')
    account_id = properties.get('account_id')
    output_file = properties.get('output_file')

    # Validate parameters
    missing = []
    if not consumer_key:
        missing.append("consumer_key")
    if not consumer_secret:
        missing.append("consumer_secret")
    if not account_id:
        missing.append("account_id")

    if missing:
        print(f"Error: Missing or empty required properties in etrade.properties: {', '.join(missing)}")
        sys.exit(1)

    # Get the account ID key needed for API calls
    account_id_key = get_account_info(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        account_id=account_id,
        tokens=tokens
    )

    orders(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        account_id_key=account_id_key,
        tokens=tokens,
        output_file=output_file
    )


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    main()
