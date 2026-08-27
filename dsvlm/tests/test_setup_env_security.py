import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "configure_env.py"
SPEC = importlib.util.spec_from_file_location("configure_env", SCRIPT)
setup_env = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(setup_env)


class SetupEnvSecurityTests(unittest.TestCase):
    def test_one_account_configures_only_direct_8898_login(self):
        values = setup_env.values_from_credentials("admin", "password ")

        self.assertEqual(set(values), {
            "DSVLM_ALLOW_INSECURE_HTTP",
            "DSVLM_LOGIN_USERNAME",
            "DSVLM_LOGIN_PASSWORD",
        })
        self.assertEqual(values["DSVLM_LOGIN_USERNAME"], "admin")
        self.assertEqual(values["DSVLM_LOGIN_PASSWORD"], "password ")
        self.assertNotIn("DSVLM_PORTAL_AUTO_LOGIN_URL", values)
        self.assertNotIn("DSVLM_LOGIN_AUTHORIZATION", values)
        self.assertNotIn("DSVLM_LOGIN_KEY", values)
        self.assertNotIn("DSVLM_LOGIN_CAPTCHA", values)
        self.assertNotIn("DSVLM_THEME_TYPE_ID", values)

    def test_password_with_trailing_space_is_written_quoted(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"

            setup_env.write_env(env_path, {"DSVLM_LOGIN_PASSWORD": "password "})

            self.assertIn('DSVLM_LOGIN_PASSWORD="password "', env_path.read_text())

    def test_unneeded_dsvlm_keys_are_removed_but_service_settings_remain(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "DSVLM_PORTAL_ACCESS_TOKEN=old\n"
                "DSVLM_THEME_TYPE_ID=old\n"
                "DSVLM_ACCEPT=application/json\n"
                "DSVLM_SERVICE_TOKEN=service-token\n"
                "KEEP=1\n",
                encoding="utf-8",
            )

            setup_env.write_env(env_path, setup_env.values_from_credentials("u", "p"))

            text = env_path.read_text(encoding="utf-8")
            self.assertNotIn("DSVLM_PORTAL_ACCESS_TOKEN", text)
            self.assertNotIn("DSVLM_THEME_TYPE_ID", text)
            self.assertNotIn("DSVLM_ACCEPT=", text)
            self.assertIn("DSVLM_SERVICE_TOKEN=service-token", text)
            self.assertIn("KEEP=1", text)

    def test_new_env_file_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"

            setup_env.write_env(env_path, {"DSVLM_ACCESS_TOKEN": "test-token"})

            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)

    def test_unsafe_env_value_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("KEEP=original\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "environment value"):
                setup_env.write_env(
                    env_path,
                    {"DSVLM_ACCESS_TOKEN": "token\nINJECTED=value"},
                )

            self.assertEqual(env_path.read_text(encoding="utf-8"), "KEEP=original\n")

    def test_replace_failure_preserves_existing_env(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("KEEP=original\n", encoding="utf-8")

            with mock.patch.object(os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    setup_env.write_env(env_path, {"KEEP": "changed"})

            self.assertEqual(env_path.read_text(encoding="utf-8"), "KEEP=original\n")
            self.assertEqual(list(Path(directory).iterdir()), [env_path])


if __name__ == "__main__":
    unittest.main()
