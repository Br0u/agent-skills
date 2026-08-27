import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "post_theme_config.py"
SPEC = importlib.util.spec_from_file_location("dsvlm_auth_responses", SCRIPT)
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


class AuthResponseHandlingTests(unittest.TestCase):
    login_password = 'password="alpha\\beta"-123'

    def refresh_env(self):
        return {
            "DSVLM_API_BASE": "https://platform.invalid",
            "DSVLM_LOGIN_USERNAME": "login-user",
            "DSVLM_LOGIN_PASSWORD": self.login_password,
        }

    def call_refresh(self, payload, status=200, write_env=False):
        with (
            mock.patch.dict(dsvlm.os.environ, self.refresh_env(), clear=True),
            mock.patch.object(dsvlm, "ENV", {}),
            mock.patch.object(
                dsvlm,
                "_open_platform_request",
                return_value=FakeResponse(payload, status=status),
            ),
        ):
            return dsvlm.refresh_authorization(write_env=write_env, timeout=1)

    def assert_secret_representations_absent(self, result, *secrets):
        rendered = json.dumps(result, ensure_ascii=False)
        for secret in secrets:
            escaped_once = json.dumps(secret, ensure_ascii=False)[1:-1]
            escaped_twice = json.dumps(escaped_once, ensure_ascii=False)[1:-1]
            for representation in (secret, escaped_once, escaped_twice):
                self.assertNotIn(representation, rendered)

    def test_mask_string_replaces_nested_json_escaped_secret(self):
        secret = 'Bearer "quoted\\value"-123'
        escaped_once = json.dumps(secret, ensure_ascii=False)[1:-1]
        escaped_twice = json.dumps(escaped_once, ensure_ascii=False)[1:-1]

        masked = dsvlm._mask_string(
            "once=%s;twice=%s" % (escaped_once, escaped_twice),
            [secret],
        )

        self.assertNotIn(escaped_once, masked)
        self.assertNotIn(escaped_twice, masked)
        self.assertEqual(masked.count("<set>"), 2)

    def test_refresh_masks_cross_field_and_outbound_secrets(self):
        response_token = "refresh-response-token-123"
        echoed_credentials = json.dumps(
            {
                "password": self.login_password,
            },
            ensure_ascii=False,
        )
        result = self.call_refresh(
            {
                "code": 0,
                "data": {"access_token": response_token},
                "message": "%s|%s" % (response_token, echoed_credentials),
            }
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["wrote_access_token"])
        self.assertNotIn("Authorization", result["headers"])
        self.assertEqual(result["response_json"]["data"]["access_token"], "<set>")
        self.assert_secret_representations_absent(
            result,
            response_token,
            self.login_password,
        )

    def test_refresh_encrypts_password_like_current_8898_frontend(self):
        captured = {}

        def open_request(request, timeout):
            captured["payload"] = json.loads(request.data)
            captured["headers"] = dict(request.header_items())
            return FakeResponse({"code": 0, "data": {"access_token": "valid-direct-login-token-123"}})

        with (
            mock.patch.dict(dsvlm.os.environ, self.refresh_env(), clear=True),
            mock.patch.object(dsvlm, "ENV", {}),
            mock.patch.object(dsvlm, "sm2_encrypt", return_value="encrypted-password"),
            mock.patch.object(dsvlm, "_open_platform_request", side_effect=open_request),
        ):
            result = dsvlm.refresh_authorization(write_env=False, timeout=1)

        self.assertTrue(result["success"])
        self.assertEqual(captured["payload"], {
            "username": "login-user",
            "password": "04encrypted-password",
            "key": "",
            "captcha": "",
        })
        self.assertNotIn("Authorization", captured["headers"])

    def test_refresh_rejects_missing_credentials_before_encryption(self):
        with (
            mock.patch.dict(dsvlm.os.environ, {}, clear=True),
            mock.patch.object(dsvlm, "ENV", {}),
            mock.patch.object(
                dsvlm,
                "sm2_encrypt",
                side_effect=AssertionError("must not encrypt an empty password"),
            ),
        ):
            result = dsvlm.refresh_authorization(write_env=False, timeout=1)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "AUTH_CONFIG_REQUIRED")

    def test_quoted_env_password_preserves_trailing_space(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text('DSVLM_LOGIN_PASSWORD="password "\n', encoding="utf-8")

            self.assertEqual(dsvlm.load_env_file(env_path)["DSVLM_LOGIN_PASSWORD"], "password ")

    def test_refresh_requires_business_success_and_named_token_field(self):
        token = "refresh-valid-token-123"
        failures = (
            b"not-json",
            ["unexpected-list"],
            {},
            {"code": 0, "message": "this-long-message-is-not-a-token"},
            {"code": False, "access_token": token},
            {"code": "0", "access_token": token},
            {"code": 999, "access_token": token},
        )
        for payload in failures:
            with self.subTest(payload=payload):
                with mock.patch.object(dsvlm, "_write_env_value") as write_env:
                    result = self.call_refresh(payload, write_env=True)
                self.assertFalse(result["success"])
                self.assertFalse(result["wrote_access_token"])
                write_env.assert_not_called()

        for status in (200, 201, 204):
            with self.subTest(status=status):
                result = self.call_refresh(
                    {"code": 0, "data": {"accessToken": token}},
                    status=status,
                )
                self.assertTrue(result["success"])

    def test_failed_login_reports_when_platform_requires_captcha(self):
        with mock.patch.object(
            dsvlm,
            "get_payload",
            return_value={
                "success": True,
                "response_json": {"code": 0, "data": True},
            },
        ):
            result = self.call_refresh({"code": 500, "message": "login failed"})

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "CAPTCHA_REQUIRED")

    def test_successful_login_does_not_check_captcha(self):
        with mock.patch.object(
            dsvlm,
            "get_payload",
            side_effect=AssertionError("captcha check is failure-only"),
        ):
            result = self.call_refresh(
                {"code": 0, "data": {"accessToken": "valid-access-token-123"}}
            )

        self.assertTrue(result["success"])

    def test_ensure_authorization_preserves_captcha_required_status(self):
        with (
            mock.patch.object(
                dsvlm,
                "_setting",
                side_effect=lambda key, default="": (
                    "true" if key == "DSVLM_DYNAMIC_AUTH" else ""
                ),
            ),
            mock.patch.object(
                dsvlm,
                "refresh_authorization",
                return_value={"success": False, "status": "CAPTCHA_REQUIRED"},
            ),
        ):
            result = dsvlm.ensure_authorization("https://platform.invalid", 1)

        self.assertEqual(result["status"], "CAPTCHA_REQUIRED")

    def test_find_token_uses_deterministic_key_priority(self):
        priorities = (
            ("access_token", "snake-access-token-123"),
            ("accessToken", "camel-access-token-123"),
            ("access-token", "hyphen-access-token-123"),
            ("token", "generic-token-value-123"),
            ("authorization", "authorization-token-123"),
        )

        self.assertEqual(
            dsvlm.REFRESH_TOKEN_KEYS,
            tuple(key for key, _ in priorities),
        )
        for key, expected in priorities:
            with self.subTest(key=key):
                candidate = "  %s  " % expected if key == "access_token" else expected
                self.assertEqual(dsvlm._find_token({key: candidate}), expected)

    def test_find_token_ignores_untrusted_branch_decoys(self):
        real_token = "trusted-data-token-123"
        result = dsvlm._find_token(
            {
                "meta": {"access_token": "meta-decoy-token-123"},
                "debug": {
                    "data": {"access_token": "debug-decoy-token-123"}
                },
                "data": {"access_token": real_token},
            }
        )

        self.assertEqual(result, real_token)

    def test_find_token_fails_closed_on_conflicting_trusted_candidates(self):
        conflicts = (
            {
                "token": "trusted-root-token-123",
                "data": {"access_token": "trusted-data-token-456"},
            },
            {
                "data": {
                    "accessToken": "trusted-data-token-123",
                    "data": {"access_token": "trusted-nested-token-456"},
                }
            },
        )
        for response in conflicts:
            with self.subTest(response=response):
                self.assertEqual(dsvlm._find_token(response), "")

        duplicate = "identical-trusted-token-123"
        self.assertEqual(
            dsvlm._find_token(
                {
                    "token": duplicate,
                    "data": {
                        "access_token": duplicate,
                        "data": {"authorization": duplicate},
                    },
                }
            ),
            duplicate,
        )

    def test_find_token_rejects_unsafe_candidates_and_arbitrary_strings(self):
        invalid_candidates = (
            None,
            1234567890123456,
            "",
            "   ",
            "too-short",
            "token with internal space 123",
            "token\twith-tab-123",
            "token\rwith-cr-123",
            "token\nwith-lf-123",
            "token\x00with-nul-123",
            "x" * 8193,
        )

        for candidate in invalid_candidates:
            with self.subTest(candidate=repr(candidate)[:80]):
                self.assertEqual(
                    dsvlm._find_token(
                        {
                            "access_token": candidate,
                            "data": {
                                "message": "this-arbitrary-long-string-is-not-a-token"
                            },
                        }
                    ),
                    "",
                )

        self.assertEqual(
            dsvlm._find_token(
                {
                    "access_token": "malicious\naccess-token-123",
                    "data": {"token": "recognized-nested-token-123"},
                }
            ),
            "recognized-nested-token-123",
        )

    def test_write_env_value_rejects_injection_before_any_mutation(self):
        invalid_values = (
            ("BAD-KEY", "valid-token-value-123"),
            ("9INVALID", "valid-token-value-123"),
            ("DSVLM_ACCESS_TOKEN\nINJECTED", "valid-token-value-123"),
            ("DSVLM_ACCESS_TOKEN", "token\rINJECTED=1"),
            ("DSVLM_ACCESS_TOKEN", "token\nINJECTED=1"),
            ("DSVLM_ACCESS_TOKEN", "token\x00INJECTED=1"),
        )

        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            original = "KEEP=value\n"
            env_path.write_text(original, encoding="utf-8")
            module_env = {"KEEP": "value"}
            process_env = {"KEEP_PROCESS": "value"}

            with (
                mock.patch.object(dsvlm, "ENV", module_env),
                mock.patch.dict(dsvlm.os.environ, process_env, clear=True),
            ):
                for key, value in invalid_values:
                    with self.subTest(key=repr(key), value=repr(value)):
                        with self.assertRaises(ValueError):
                            dsvlm._write_env_value(key, value, path=env_path)
                        self.assertEqual(env_path.read_text(encoding="utf-8"), original)
                        self.assertEqual(module_env, {"KEEP": "value"})
                        self.assertEqual(dict(dsvlm.os.environ), process_env)

    def test_write_env_value_preserves_valid_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "KEEP=value\nDSVLM_ACCESS_TOKEN=old-token-value-123\n",
                encoding="utf-8",
            )
            module_env = {"KEEP": "value"}

            with (
                mock.patch.object(dsvlm, "ENV", module_env),
                mock.patch.dict(dsvlm.os.environ, {}, clear=True),
            ):
                dsvlm._write_env_value(
                    "DSVLM_ACCESS_TOKEN",
                    "new-token-value-123",
                    path=env_path,
                )

                self.assertEqual(
                    env_path.read_text(encoding="utf-8"),
                    "KEEP=value\nDSVLM_ACCESS_TOKEN=new-token-value-123\n",
                )
                self.assertEqual(
                    module_env["DSVLM_ACCESS_TOKEN"],
                    "new-token-value-123",
                )
                self.assertEqual(
                    dsvlm.os.environ["DSVLM_ACCESS_TOKEN"],
                    "new-token-value-123",
                )

    def test_write_env_value_is_atomic_on_write_or_replace_failure(self):
        failures = ("write", "replace")
        for failure in failures:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                env_path = Path(directory) / ".env"
                original = "KEEP=value\nDSVLM_ACCESS_TOKEN=old-token-value-123\n"
                env_path.write_text(original, encoding="utf-8")
                module_env = {
                    "KEEP": "value",
                    "DSVLM_ACCESS_TOKEN": "old-token-value-123",
                }
                process_env = {
                    "DSVLM_ACCESS_TOKEN": "old-token-value-123",
                }

                patches = [
                    mock.patch.object(dsvlm, "ENV", module_env),
                    mock.patch.dict(dsvlm.os.environ, process_env, clear=True),
                ]
                if failure == "write":
                    patches.append(
                        mock.patch.object(
                            dsvlm,
                            "_write_env_temp_file",
                            side_effect=OSError("simulated write failure"),
                            create=True,
                        )
                    )
                else:
                    patches.append(
                        mock.patch.object(
                            dsvlm.os,
                            "replace",
                            side_effect=OSError("simulated replace failure"),
                        )
                    )

                with patches[0], patches[1], patches[2]:
                    with self.assertRaises(OSError):
                        dsvlm._write_env_value(
                            "DSVLM_ACCESS_TOKEN",
                            "new-token-value-123",
                            path=env_path,
                        )

                    self.assertEqual(env_path.read_text(encoding="utf-8"), original)
                    self.assertEqual(
                        module_env["DSVLM_ACCESS_TOKEN"],
                        "old-token-value-123",
                    )
                    self.assertEqual(
                        dsvlm.os.environ["DSVLM_ACCESS_TOKEN"],
                        "old-token-value-123",
                    )
                    self.assertEqual(
                        sorted(path.name for path in Path(directory).iterdir()),
                        [".env"],
                    )

    def test_refresh_rejects_malicious_or_blank_token_without_persisting(self):
        invalid_tokens = (
            "",
            "   ",
            "token with internal space 123",
            "token\rwith-cr-123",
            "token\nwith-lf-123",
            "token\x00with-nul-123",
            "x" * 8193,
        )

        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            original = "KEEP=value\n"
            env_path.write_text(original, encoding="utf-8")

            for token in invalid_tokens:
                with self.subTest(token=repr(token)[:80]):
                    module_env = {"KEEP": "value"}
                    process_env = {
                        **self.refresh_env(),
                        "DSVLM_ACCESS_TOKEN": "existing-token-value-123",
                    }
                    dsvlm_write_env = dsvlm._write_env_value

                    def write_env(key, value):
                        return dsvlm_write_env(key, value, path=env_path)

                    with (
                        mock.patch.object(dsvlm, "ENV", module_env),
                        mock.patch.dict(dsvlm.os.environ, process_env, clear=True),
                        mock.patch.object(
                            dsvlm,
                            "_open_platform_request",
                            return_value=FakeResponse(
                                {"code": 0, "data": {"access_token": token}}
                            ),
                        ),
                        mock.patch.object(
                            dsvlm,
                            "_write_env_value",
                            side_effect=write_env,
                        ) as persisted,
                    ):
                        result = dsvlm.refresh_authorization(
                            write_env=True,
                            timeout=1,
                        )
                        self.assertFalse(result["success"])
                        self.assertFalse(result["wrote_access_token"])
                        persisted.assert_not_called()
                        self.assertEqual(module_env, {"KEEP": "value"})
                        self.assertEqual(
                            dsvlm.os.environ["DSVLM_ACCESS_TOKEN"],
                            "existing-token-value-123",
                        )

                    self.assertEqual(env_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
