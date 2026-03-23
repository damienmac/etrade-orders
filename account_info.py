import sys
import pyetrade

def get_account_info(consumer_key: str, consumer_secret: str, account_id: str, tokens: dict) -> str:
    """
    Retrieves E*TRADE account information based on credentials provided.

    :param consumer_key: The E*TRADE consumer key.
    :param consumer_secret: The E*TRADE consumer secret.
    :param account_id: The E*TRADE account ID.
    :param tokens: A dictionary containing the E*TRADE OAuth tokens.
    :return: The accountIdKey for the specified account.
    :raises SystemExit: If API credentials or account information cannot be retrieved.
    """
    try:
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
        sys.exit(1)

    try:
        accounts_list = etrade_accounts.list_accounts(resp_format='json')
        # print(json.dumps(accounts_list, indent=4))

        accounts = accounts_list\
            .get("AccountListResponse", {})\
            .get("Accounts", {})\
            .get("Account", [])

        if not accounts:
            print("Error: No accounts found or unexpected API response format.")
            sys.exit(1)

        # Find the account with the specified ID
        matching_accounts = [a for a in accounts if a.get("accountId") == account_id]
        if not matching_accounts:
            print(f"Error: Account with ID {account_id} not found. Available accounts:")
            for a in accounts:
                print(f"  - {a.get('accountId')}: {a.get('accountName')}")
            sys.exit(1)

        account = matching_accounts[0]
        account_id_key = account.get("accountIdKey", "")
        if not account_id_key:
            print(f"Error: Could not retrieve accountIdKey for account {account_id}.")
            sys.exit(1)

        return account_id_key
    except Exception as e:
        print(f"Error retrieving account information: {e}")
        sys.exit(1)
