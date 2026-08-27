import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "post_theme_config.py"
SPEC = importlib.util.spec_from_file_location("dsvlm_post_sanitization", SCRIPT)
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


class ResponseSanitizationTests(unittest.TestCase):
    def run_post(
        self,
        post_result,
        *,
        authorization="fake-manual-authorization",
        cookie="",
        csrf_token="",
    ):
        local_secret = "fake-known-local-secret"
        with (
            mock.patch.dict(
                dsvlm.os.environ,
                {
                    "DSVLM_DYNAMIC_AUTH": "false",
                    "DSVLM_LOGIN_PASSWORD": local_secret,
                },
                clear=True,
            ),
            mock.patch.object(dsvlm, "ENV", {}),
            mock.patch.object(dsvlm, "post_payload", return_value=post_result),
        ):
            result = dsvlm.main(
                payload={
                    "themeTypeId": "theme-A",
                    "themeLabel": "demo",
                    "ruleList": [],
                },
                dry_run=False,
                authorization=authorization,
                cookie=cookie,
                csrf_token=csrf_token,
                force_post=True,
            )["api_result"][0]
        return result, local_secret

    def run_actual_response(self, payload, *, status=200):
        with (
            mock.patch.dict(
                dsvlm.os.environ,
                {"DSVLM_DYNAMIC_AUTH": "false"},
                clear=True,
            ),
            mock.patch.object(dsvlm, "ENV", {}),
            mock.patch.object(
                dsvlm,
                "_open_platform_request",
                return_value=FakeResponse(payload, status=status),
            ),
        ):
            return dsvlm.main(
                payload={
                    "themeTypeId": "theme-A",
                    "themeLabel": "demo",
                    "ruleList": [],
                },
                dry_run=False,
                authorization="fake-manual-authorization",
                force_post=True,
            )["api_result"][0]

    def test_sensitive_key_value_is_replaced_in_ordinary_message_fields(self):
        response_secret = "secret-123"
        result, _ = self.run_post(
            {
                "success": True,
                "response_text": json.dumps(
                    {"token": response_secret, "message": response_secret}
                ),
                "response_json": {
                    "code": 0,
                    "token": response_secret,
                    "message": response_secret,
                },
            }
        )

        rendered = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(response_secret, rendered)
        self.assertEqual(result["response_json"]["token"], "<set>")
        self.assertEqual(result["response_json"]["message"], "<set>")

    def test_sensitive_key_aliases_are_normalized_before_replacement(self):
        for key in (
            "access-token",
            "access_token",
            "accessToken",
            "Authorization",
            "cookie",
            "csrf_token",
            "X-CSRF-Token",
        ):
            secret = "fake-%s-secret-123" % key
            with self.subTest(key=key):
                result = dsvlm._sanitize_response_result(
                    {
                        "response_text": json.dumps({key: secret, "message": secret}),
                        "response_json": {key: secret, "message": secret},
                    }
                )

                self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))
                self.assertEqual(result["response_json"][key], "<set>")
                self.assertEqual(result["response_json"]["message"], "<set>")

    def test_business_failure_masks_per_call_authorization_cookie_and_csrf(self):
        authorization = "fake-explicit-authorization-123"
        cookie = "fake-explicit-cookie-123"
        csrf_token = "fake-explicit-csrf-123"
        echoed = "|".join((authorization, cookie, csrf_token))
        result, _ = self.run_post(
            {
                "success": False,
                "response_text": json.dumps({"code": 999, "message": echoed}),
                "response_json": {"code": 999, "message": echoed},
            },
            authorization=authorization,
            cookie=cookie,
            csrf_token=csrf_token,
        )

        rendered = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["status"], "POST_FAILED")
        for secret in (authorization, cookie, csrf_token):
            self.assertNotIn(secret, rendered)

    def test_exception_masks_per_call_authorization_cookie_and_csrf(self):
        authorization = "fake-exception-authorization-123"
        cookie = "fake-exception-cookie-123"
        csrf_token = "fake-exception-csrf-123"
        echoed = "|".join((authorization, cookie, csrf_token))

        with (
            mock.patch.dict(
                dsvlm.os.environ,
                {"DSVLM_DYNAMIC_AUTH": "false"},
                clear=True,
            ),
            mock.patch.object(dsvlm, "ENV", {}),
            mock.patch.object(
                dsvlm,
                "post_payload",
                side_effect=RuntimeError(echoed),
            ),
        ):
            result = dsvlm.main(
                payload={
                    "themeTypeId": "theme-A",
                    "themeLabel": "demo",
                    "ruleList": [],
                },
                dry_run=False,
                authorization=authorization,
                cookie=cookie,
                csrf_token=csrf_token,
                force_post=True,
            )["api_result"][0]

        self.assertEqual(result["status"], "POST_EXCEPTION")
        for secret in (authorization, cookie, csrf_token):
            self.assertNotIn(secret, result["error"])

    def test_post_payload_masks_dynamic_authorization_echoed_in_message(self):
        dynamic_authorization = "fake-dynamic-authorization-123"
        response = FakeResponse(
            {"code": 0, "message": dynamic_authorization},
            status=200,
        )

        with (
            mock.patch.object(
                dsvlm,
                "_dynamic_authorization",
                return_value=dynamic_authorization,
            ),
            mock.patch.object(
                dsvlm,
                "_open_platform_request",
                return_value=response,
            ),
        ):
            result = dsvlm.post_payload(
                "https://platform.invalid",
                "/s/theme/data",
                {},
                {},
                1,
            )

        self.assertTrue(result["success"])
        self.assertNotIn(dynamic_authorization, json.dumps(result, ensure_ascii=False))

    def test_post_payload_masks_dynamic_authorization_echoed_in_exception(self):
        dynamic_authorization = "fake-dynamic-exception-authorization-123"

        with (
            mock.patch.object(
                dsvlm,
                "_dynamic_authorization",
                return_value=dynamic_authorization,
            ),
            mock.patch.object(
                dsvlm,
                "_open_platform_request",
                side_effect=RuntimeError("request failed: %s" % dynamic_authorization),
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                dsvlm.post_payload(
                    "https://platform.invalid",
                    "/s/theme/data",
                    {},
                    {},
                    1,
                )

        self.assertNotIn(dynamic_authorization, str(raised.exception))
        self.assertIn("<set>", str(raised.exception))

    def test_nonconforming_2xx_responses_never_report_post_success(self):
        for payload in (
            b"not-json",
            ["unexpected-list"],
            {},
            {"data": {}},
            {"code": 999, "message": "failed"},
        ):
            with self.subTest(payload=payload):
                result = self.run_actual_response(payload)
                self.assertEqual(result["status"], "POST_FAILED")
                self.assertFalse(result["success"])

    def test_any_2xx_with_object_code_zero_reports_post_success(self):
        for status in (200, 201, 204):
            with self.subTest(status=status):
                result = self.run_actual_response({"code": 0}, status=status)
                self.assertEqual(result["status"], "POST_SUCCEEDED_DO_NOT_RETRY")
                self.assertTrue(result["success"])

    def test_success_response_masks_token_fields_and_known_local_secrets(self):
        response_token = "fake-response-token-123456"
        authorization_token = "fake-response-authorization-123456"
        access_token = "fake-response-access-token-123456"
        result, local_secret = self.run_post(
            {
                "success": True,
                "response_text": json.dumps(
                    {
                        "token": response_token,
                        "Authorization": authorization_token,
                        "access-token": access_token,
                        "message": "fake-known-local-secret",
                    }
                ),
                "response_json": {
                    "code": 0,
                    "token": response_token,
                    "Authorization": authorization_token,
                    "access-token": access_token,
                    "message": "fake-known-local-secret",
                },
            }
        )

        rendered = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(response_token, rendered)
        self.assertNotIn(authorization_token, rendered)
        self.assertNotIn(access_token, rendered)
        self.assertNotIn(local_secret, rendered)
        self.assertEqual(result["response_json"]["token"], "<set>")
        self.assertEqual(result["response_json"]["Authorization"], "<set>")
        self.assertEqual(result["response_json"]["access-token"], "<set>")
        self.assertIn("<set>", result["response_text"])

    def test_business_failure_response_is_sanitized_before_return(self):
        response_token = "fake-business-token-123456"
        result, local_secret = self.run_post(
            {
                "success": False,
                "response_text": json.dumps(
                    {
                        "code": 999,
                        "token": response_token,
                        "message": "fake-known-local-secret",
                    }
                ),
                "response_json": {
                    "code": 999,
                    "token": response_token,
                    "message": "fake-known-local-secret",
                },
            }
        )

        rendered = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["status"], "POST_FAILED")
        self.assertNotIn(response_token, rendered)
        self.assertNotIn(local_secret, rendered)
        self.assertEqual(result["response_json"]["token"], "<set>")

    def test_unexpected_exception_message_masks_known_local_secret(self):
        local_secret = "fake-exception-local-secret"
        with (
            mock.patch.dict(
                dsvlm.os.environ,
                {
                    "DSVLM_DYNAMIC_AUTH": "false",
                    "DSVLM_LOGIN_PASSWORD": local_secret,
                },
                clear=True,
            ),
            mock.patch.object(dsvlm, "ENV", {}),
            mock.patch.object(
                dsvlm,
                "post_payload",
                side_effect=RuntimeError("request failed: %s" % local_secret),
            ),
        ):
            result = dsvlm.main(
                payload={
                    "themeTypeId": "theme-A",
                    "themeLabel": "demo",
                    "ruleList": [],
                },
                dry_run=False,
                authorization="fake-manual-authorization",
                force_post=True,
            )["api_result"][0]

        self.assertEqual(result["status"], "POST_EXCEPTION")
        self.assertNotIn(local_secret, result["error"])
        self.assertIn("<set>", result["error"])


if __name__ == "__main__":
    unittest.main()
