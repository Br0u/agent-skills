import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "post_theme_config.py"
SPEC = importlib.util.spec_from_file_location("dsvlm_post_cli", SCRIPT)
dsvlm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dsvlm)


class CliAuthorizationTests(unittest.TestCase):
    def run_cli(self, user_request):
        captured = {}
        stdin = io.StringIO(json.dumps({
            "algorithm": "payload-name",
            "conditions": ["内容理解 / 正向思维1 / 测试"],
        }))

        def fake_main(**kwargs):
            captured.update(kwargs)
            return {"api_result": [{"success": True}]}

        with (
            mock.patch.object(
                sys,
                "argv",
                [str(SCRIPT), "--payload", "-", "--user-request", user_request],
            ),
            mock.patch.object(sys, "stdin", stdin),
            mock.patch.object(dsvlm, "main", side_effect=fake_main),
            mock.patch("sys.stdout", new=io.StringIO()),
        ):
            dsvlm.cli()
        return captured

    def test_original_user_post_authorizes_write(self):
        kwargs = self.run_cli(
            "/dsvlm 新建：测试；算法名：request-name；主题：wbr --post"
        )

        self.assertFalse(kwargs["dry_run"])
        self.assertEqual(kwargs["theme_label"], "request-name")
        self.assertEqual(kwargs["theme_name"], "wbr")

    def test_missing_original_user_post_stays_dry_run(self):
        kwargs = self.run_cli(
            "/dsvlm 新建：测试；算法名：request-name；主题：wbr"
        )

        self.assertTrue(kwargs["dry_run"])

    def test_removed_submission_flags_are_rejected(self):
        for flag in (
            "--agent-output",
            "--config",
            "--post",
            "--force-post",
            "--authorization",
            "--api-base",
            "--endpoint",
            "--theme-type-id",
            "--algorithm-name",
        ):
            with self.subTest(flag=flag):
                with (
                    mock.patch.object(sys, "argv", [str(SCRIPT), flag, "value"]),
                    mock.patch("sys.stderr", new=io.StringIO()),
                ):
                    with self.assertRaises(SystemExit) as raised:
                        dsvlm.cli()
                    self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
