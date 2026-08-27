from pathlib import Path
import unittest


SKILL_DIR = Path(__file__).resolve().parents[1]


class DocumentationSecurityTests(unittest.TestCase):
    def test_platform_http_opt_in_is_documented_everywhere(self):
        for relative_path in (
            "SKILL.md",
            "README.md",
            "references/posting.md",
        ):
            with self.subTest(path=relative_path):
                text = (SKILL_DIR / relative_path).read_text(encoding="utf-8")
                self.assertIn("DSVLM_ALLOW_INSECURE_HTTP", text)
                self.assertIn("8898", text)

    def test_example_keeps_platform_http_opt_in_disabled(self):
        text = (SKILL_DIR / ".env.example").read_text(encoding="utf-8")

        self.assertIn("DSVLM_ALLOW_INSECURE_HTTP=false", text)

    def test_example_contains_only_required_and_service_settings(self):
        text = (SKILL_DIR / ".env.example").read_text(encoding="utf-8")
        keys = {
            line.split("=", 1)[0]
            for line in text.splitlines()
            if "=" in line and not line.startswith("#")
        }

        self.assertEqual(keys, {
            "DSVLM_SERVICE_API_BASE",
            "DSVLM_SERVICE_TOKEN",
            "DSVLM_SERVICE_TIMEOUT",
            "DSVLM_SERVICE_ALLOW_INSECURE_HTTP",
            "DSVLM_ALLOW_INSECURE_HTTP",
            "DSVLM_LOGIN_USERNAME",
            "DSVLM_LOGIN_PASSWORD",
        })

    def test_readme_changelog_records_direct_8898_catalog(self):
        text = (SKILL_DIR / "README.md").read_text(encoding="utf-8")

        self.assertIn("/s/theme/type/all", text)
        self.assertIn("密码按前端规则使用 SM2 加密", text)
        self.assertIn("提交入口收敛为 `--payload -", text)
        self.assertIn("只覆盖 JSON 明确提供的字段", text)
        self.assertIn("CAPTCHA_REQUIRED", text)
        self.assertNotIn("DSVLM_CATALOG_", text)

    def test_current_docs_use_only_structured_submission_input(self):
        for relative_path in ("SKILL.md", "README.md", "references/posting.md"):
            with self.subTest(path=relative_path):
                text = (SKILL_DIR / relative_path).read_text(encoding="utf-8")
                if relative_path == "README.md":
                    text = text.split("## 更新日志", 1)[0]
                self.assertIn("--payload -", text)
                self.assertNotIn("--agent-output", text)
                self.assertNotIn("--force-post", text)
                self.assertNotIn("--config payload.json", text)

    def test_runtime_access_token_is_not_an_example_setting(self):
        text = (SKILL_DIR / ".env.example").read_text(encoding="utf-8")

        self.assertNotIn("DSVLM_ACCESS_TOKEN", text)

    def test_public_config_entry_and_command_are_removed(self):
        self.assertFalse((SKILL_DIR / "scripts/configure_env.command").exists())
        for relative_path in ("SKILL.md", "README.md", "references/posting.md"):
            with self.subTest(path=relative_path):
                text = (SKILL_DIR / relative_path).read_text(encoding="utf-8")
                if relative_path == "README.md":
                    text = text.split("## 更新日志", 1)[0]
                self.assertNotIn("configure_env.command", text)


if __name__ == "__main__":
    unittest.main()
