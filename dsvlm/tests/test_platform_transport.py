import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "post_theme_config.py"
SPEC = importlib.util.spec_from_file_location("dsvlm_post_transport", SCRIPT)
dsvlm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dsvlm)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class FakeOpener:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class PlatformTransportTests(unittest.TestCase):
    def transport_env(self, allow_insecure="false", **extra):
        values = {"DSVLM_ALLOW_INSECURE_HTTP": allow_insecure, **extra}
        return mock.patch.dict(dsvlm.os.environ, values, clear=True)

    def test_all_credential_bearing_calls_reject_plain_http_by_default(self):
        cases = [
            (
                "post_payload",
                lambda: dsvlm.post_payload(
                    "http://platform.invalid",
                    "/s/theme/data",
                    {},
                    {"Authorization": "fake-post-secret"},
                    1,
                ),
            ),
            (
                "get_payload",
                lambda: dsvlm.get_payload(
                    "http://platform.invalid",
                    "/s/theme/data/1",
                    {"Authorization": "fake-get-secret"},
                    1,
                ),
            ),
            (
                "refresh_authorization",
                lambda: dsvlm.refresh_authorization(write_env=False, timeout=1),
            ),
        ]

        for name, call in cases:
            with self.subTest(name=name):
                opener_factory = mock.Mock(
                    side_effect=AssertionError("plain HTTP must fail before opener creation")
                )
                with (
                    self.transport_env(
                        DSVLM_API_BASE="http://platform.invalid",
                        DSVLM_LOGIN_USERNAME="fake-user",
                        DSVLM_LOGIN_PASSWORD="fake-login-secret",
                    ),
                    mock.patch.object(dsvlm, "ENV", {}),
                    mock.patch("urllib.request.build_opener", new=opener_factory),
                    mock.patch(
                        "urllib.request.urlopen",
                        side_effect=AssertionError("urlopen must never be used"),
                    ),
                ):
                    with self.assertRaises(dsvlm.PlatformTransportError) as error:
                        call()

                opener_factory.assert_not_called()
                self.assertNotIn("fake", str(error.exception).lower())

    def test_all_credential_bearing_calls_use_no_redirect_opener_after_opt_in(self):
        cases = [
            (
                "post_payload",
                lambda: dsvlm.post_payload(
                    "http://platform.invalid",
                    "/s/theme/data",
                    {},
                    {"Authorization": "fake-post-secret"},
                    1,
                ),
                {"code": 0},
            ),
            (
                "get_payload",
                lambda: dsvlm.get_payload(
                    "http://platform.invalid",
                    "/s/theme/data/1",
                    {"Authorization": "fake-get-secret"},
                    1,
                ),
                {"code": 0},
            ),
            (
                "refresh_authorization",
                lambda: dsvlm.refresh_authorization(write_env=False, timeout=1),
                {"code": 0, "data": {"access_token": "fake-refreshed-token-123"}},
            ),
        ]

        for name, call, payload in cases:
            with self.subTest(name=name):
                opener = FakeOpener(FakeResponse(payload))
                factory = mock.Mock(return_value=opener)
                with (
                    self.transport_env(
                        "true",
                        DSVLM_API_BASE="http://platform.invalid",
                        DSVLM_LOGIN_USERNAME="fake-user",
                        DSVLM_LOGIN_PASSWORD="fake-login-secret",
                    ),
                    mock.patch.object(dsvlm, "ENV", {}),
                    mock.patch("urllib.request.build_opener", new=factory),
                    mock.patch(
                        "urllib.request.urlopen",
                        side_effect=AssertionError("credential calls must use an opener"),
                    ),
                ):
                    result = call()

                self.assertTrue(result["success"])
                self.assertEqual(len(opener.requests), 1)
                self.assertTrue(
                    any(
                        isinstance(handler, dsvlm.NoRedirectHandler)
                        for handler in factory.call_args.args
                    )
                )

    def test_redirect_is_rejected_once_without_body_or_token_leak(self):
        fake_secret = "fake-redirect-secret"
        error = dsvlm.urllib.error.HTTPError(
            "https://platform.invalid/s/theme/data",
            302,
            "Found",
            {},
            io.BytesIO(fake_secret.encode("utf-8")),
        )
        opener = FakeOpener(error)
        factory = mock.Mock(return_value=opener)

        with (
            self.transport_env(),
            mock.patch.object(dsvlm, "ENV", {}),
            mock.patch("urllib.request.build_opener", new=factory),
        ):
            with self.assertRaises(dsvlm.PlatformTransportError) as raised:
                dsvlm.post_payload(
                    "https://platform.invalid",
                    "/s/theme/data",
                    {},
                    {"Authorization": fake_secret},
                    1,
                )

        self.assertEqual(raised.exception.status_code, 302)
        self.assertEqual(str(raised.exception), "HTTP 302")
        self.assertNotIn(fake_secret, str(raised.exception))
        self.assertEqual(len(opener.requests), 1)
        self.assertTrue(
            any(
                isinstance(handler, dsvlm.NoRedirectHandler)
                for handler in factory.call_args.args
            )
        )

    def test_authorization_refresh_transport_failure_is_sanitized(self):
        fake_secret = "fake-refresh-response-secret"

        def fake_setting(name, default=""):
            if name == "DSVLM_DYNAMIC_AUTH":
                return "true"
            if name == "DSVLM_ACCESS_TOKEN":
                return ""
            return default

        with (
            mock.patch.object(dsvlm, "_setting", side_effect=fake_setting),
            mock.patch.object(
                dsvlm,
                "refresh_authorization",
                side_effect=dsvlm.PlatformTransportError(
                    fake_secret,
                    status_code=302,
                ),
            ),
        ):
            result = dsvlm.ensure_authorization(
                "https://platform.invalid",
                1,
                theme_type_id="theme-A",
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "AUTH_REFRESH_HTTP_ERROR")
        self.assertEqual(result["status_code"], 302)
        self.assertEqual(result["error"], "HTTP 302")
        self.assertNotIn(fake_secret, str(result))


if __name__ == "__main__":
    unittest.main()
