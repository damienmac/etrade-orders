import unittest
from unittest.mock import patch

from tokens import (
    build_authorization_url,
    fetch_access_token,
    fetch_request_token,
    get_oauth_urls,
    normalize_environment,
    parse_oauth_response,
    resolve_environment,
)


class TokensHelpersTest(unittest.TestCase):
    class _FakeResponse:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text

    class _FallbackSession:
        post_calls = 0
        get_calls = 0

        def __init__(self, *args, **kwargs):
            pass

        def post(self, *args, **kwargs):
            TokensHelpersTest._FallbackSession.post_calls += 1
            return TokensHelpersTest._FakeResponse(404, "Not Found")

        def get(self, *args, **kwargs):
            TokensHelpersTest._FallbackSession.get_calls += 1
            return TokensHelpersTest._FakeResponse(
                200,
                "oauth_token=acc123&oauth_token_secret=sec456",
            )

    class _RetryThenSuccessSession:
        post_calls = 0

        def __init__(self, *args, **kwargs):
            pass

        def post(self, *args, **kwargs):
            TokensHelpersTest._RetryThenSuccessSession.post_calls += 1
            if TokensHelpersTest._RetryThenSuccessSession.post_calls == 1:
                return TokensHelpersTest._FakeResponse(404, "Not Found")
            return TokensHelpersTest._FakeResponse(
                200,
                "oauth_token=req123&oauth_token_secret=req456",
            )
    def test_normalize_environment(self):
        self.assertEqual("production", normalize_environment(None))
        self.assertEqual("production", normalize_environment("prod"))
        self.assertEqual("sandbox", normalize_environment("sandbox"))
        self.assertEqual("production", normalize_environment("unknown-value"))

    def test_resolve_environment(self):
        self.assertEqual("sandbox", resolve_environment({"environment": "sandbox"}))
        self.assertEqual("sandbox", resolve_environment({"use_sandbox": "true"}))
        self.assertEqual("production", resolve_environment({}))

    def test_get_oauth_urls(self):
        prod_urls = get_oauth_urls({})
        self.assertIn("https://api.etrade.com", prod_urls["request_token_url"])

        sb_urls = get_oauth_urls({"environment": "sandbox"})
        self.assertIn("https://apisb.etrade.com", sb_urls["request_token_url"])

    def test_parse_oauth_response(self):
        payload = "oauth_token=abc123&oauth_token_secret=secret456&oauth_callback_confirmed=true"
        parsed = parse_oauth_response(payload)
        self.assertEqual("abc123", parsed["oauth_token"])
        self.assertEqual("secret456", parsed["oauth_token_secret"])
        self.assertEqual("true", parsed["oauth_callback_confirmed"])

    def test_build_authorization_url(self):
        url = build_authorization_url("ckey", "rtok")
        self.assertEqual("https://us.etrade.com/e/t/etws/authorize?key=ckey&token=rtok", url)

    @patch("tokens.time.sleep", return_value=None)
    @patch("tokens.OAuth1Session", new=_FallbackSession)
    def test_fetch_access_token_falls_back_to_get(self, _mock_sleep):
        TokensHelpersTest._FallbackSession.post_calls = 0
        TokensHelpersTest._FallbackSession.get_calls = 0

        token_data = fetch_access_token(
            "consumer",
            "secret",
            "request-token",
            "request-secret",
            "YT3DC",
            "https://api.etrade.com/oauth/access_token",
        )
        self.assertEqual("acc123", token_data["oauth_token"])
        self.assertEqual("sec456", token_data["oauth_token_secret"])
        self.assertEqual(3, TokensHelpersTest._FallbackSession.post_calls)
        self.assertEqual(1, TokensHelpersTest._FallbackSession.get_calls)

    @patch("tokens.time.sleep", return_value=None)
    @patch("tokens.OAuth1Session", new=_RetryThenSuccessSession)
    def test_fetch_request_token_retries_transient_404(self, _mock_sleep):
        TokensHelpersTest._RetryThenSuccessSession.post_calls = 0

        token_data = fetch_request_token(
            "consumer",
            "secret",
            "https://api.etrade.com/oauth/request_token",
        )

        self.assertEqual("req123", token_data["oauth_token"])
        self.assertEqual("req456", token_data["oauth_token_secret"])
        self.assertEqual(2, TokensHelpersTest._RetryThenSuccessSession.post_calls)


if __name__ == "__main__":
    unittest.main()
