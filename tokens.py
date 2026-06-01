import time
from urllib.parse import parse_qsl

from requests_oauthlib import OAuth1Session

from properties import load_properties

"""
Run this to generate the tokens dict you will paste into the other files here that access the API.
You need to click on the URL and get the verifier code, and enter it back here.
"""

"""
After registering, you see this at the top of the page.

Individual Consumer Key
We see you already have an active key, here are the details below:
Your active SANDBOX API key is: 6de...f59, and secret is: 06b...2ee.
Your active PROD API key is: 86b...9ef, and secret is: bb7...0c2.
"""

AUTHORIZE_URL = "https://us.etrade.com/e/t/etws/authorize"
TRANSIENT_HTTP_STATUSES = {404, 500, 502, 503, 504}
RETRY_ATTEMPTS = 3


def normalize_environment(raw_value):
    if not raw_value:
        return "production"

    value = str(raw_value).strip().lower()
    if value in {"production", "prod", "live"}:
        return "production"
    if value in {"sandbox", "sb", "dev", "development", "test"}:
        return "sandbox"

    # Default to production if an unknown value is provided
    return "production"


def resolve_environment(properties):
    explicit = (
        properties.get('environment')
        or properties.get('api_env')
        or properties.get('etrade_env')
    )

    if explicit:
        return normalize_environment(explicit)

    use_sandbox = str(properties.get('use_sandbox', '')).strip().lower()
    if use_sandbox in {"1", "true", "yes", "y", "on"}:
        return "sandbox"

    return "production"


def get_oauth_urls(properties):
    environment = resolve_environment(properties)
    base_url = "https://apisb.etrade.com" if environment == "sandbox" else "https://api.etrade.com"
    return {
        "environment": environment,
        "request_token_url": f"{base_url}/oauth/request_token",
        "access_token_url": f"{base_url}/oauth/access_token",
        "authorize_url": AUTHORIZE_URL,
    }


def parse_oauth_response(response_text):
    parsed = dict(parse_qsl((response_text or "").strip(), keep_blank_values=True))
    return parsed


def _is_retryable_status(status_code):
    return status_code in TRANSIENT_HTTP_STATUSES


def _request_with_retry(session, method_name, token_url, attempts=RETRY_ATTEMPTS):
    request_attempts = []

    for attempt in range(1, attempts + 1):
        response = getattr(session, method_name)(token_url, timeout=30)
        status_code = getattr(response, 'status_code', 'n/a')
        response_body = (response.text or '').strip()[:200]

        request_attempts.append(
            {
                'method': method_name.upper(),
                'attempt': attempt,
                'status_code': status_code,
                'body': response_body,
            }
        )

        if isinstance(status_code, int) and status_code < 400:
            return response, request_attempts

        if attempt < attempts and _is_retryable_status(status_code):
            time.sleep(attempt)
            continue

        return response, request_attempts


def _format_attempt_summary(attempts):
    return '; '.join(
        f"{entry['method']} attempt {entry['attempt']} {entry['status_code']} {entry['body']}"
        for entry in attempts
    )


def exchange_oauth_token_with_fallback(session, token_url):
    attempts = []

    for method_name in ("post", "get"):
        response, method_attempts = _request_with_retry(session, method_name, token_url)
        attempts.extend(method_attempts)
        token_data = parse_oauth_response(response.text)

        if token_data.get("oauth_token") and token_data.get("oauth_token_secret"):
            return token_data

    attempt_summary = _format_attempt_summary(attempts)
    raise RuntimeError(
        "Unable to exchange OAuth token with E*TRADE. "
        f"Tried both POST and GET at {token_url}. Details: {attempt_summary}"
    )


def fetch_request_token(consumer_key, consumer_secret, request_token_url):
    session = OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        callback_uri="oob",
        signature_type="AUTH_HEADER",
    )
    response, attempts = _request_with_retry(session, 'post', request_token_url)
    if isinstance(response.status_code, int) and response.status_code >= 400:
        attempt_summary = _format_attempt_summary(attempts)
        raise RuntimeError(
            "Unable to fetch request token from E*TRADE. "
            f"Tried POST at {request_token_url}. Details: {attempt_summary}"
        )

    token_data = parse_oauth_response(response.text)
    if not token_data.get("oauth_token") or not token_data.get("oauth_token_secret"):
        raise ValueError("Unable to parse request token response from E*TRADE.")
    return token_data


def fetch_access_token(consumer_key, consumer_secret, request_token, request_token_secret, verifier_code, access_token_url):
    verifier_code = (verifier_code or "").strip()
    if not verifier_code:
        raise ValueError("Verification code is required.")

    session = OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=request_token,
        resource_owner_secret=request_token_secret,
        verifier=verifier_code,
        signature_type="AUTH_HEADER",
    )
    return exchange_oauth_token_with_fallback(session, access_token_url)


def build_authorization_url(consumer_key, request_token, authorize_url=AUTHORIZE_URL):
    return f"{authorize_url}?key={consumer_key}&token={request_token}"


def get_tokens():
    # Get properties from the file
    properties = load_properties()
    consumer_key = properties.get('consumer_key')
    consumer_secret = properties.get('consumer_secret')

    if not consumer_key or not consumer_secret:
        raise ValueError("Missing consumer_key or consumer_secret in etrade.properties")

    oauth_urls = get_oauth_urls(properties)
    print(f"Using E*TRADE environment: {oauth_urls['environment']}")

    request_token_data = fetch_request_token(
        consumer_key,
        consumer_secret,
        oauth_urls['request_token_url']
    )
    authorization_url = build_authorization_url(
        consumer_key,
        request_token_data['oauth_token'],
        oauth_urls['authorize_url']
    )
    print(authorization_url)  # Use the printed URL

    verifier_code = input("Enter verification code: ")
    tokens = fetch_access_token(
        consumer_key,
        consumer_secret,
        request_token_data['oauth_token'],
        request_token_data['oauth_token_secret'],
        verifier_code,
        oauth_urls['access_token_url']
    )

    print(f"tokens = {tokens}")

    # Save tokens to a file
    with open('etrade_tokens.py', 'w') as f:
        f.write("# This file is auto-generated by tokens.py\n")
        f.write("# Do not edit manually\n\n")
        f.write(f"tokens = {tokens}\n")

    print(f"Tokens saved to etrade_tokens.py")


if __name__ == '__main__':
    get_tokens()
