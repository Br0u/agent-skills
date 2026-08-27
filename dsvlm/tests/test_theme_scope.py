import importlib.util
from pathlib import Path
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "post_theme_config.py"
SPEC = importlib.util.spec_from_file_location("dsvlm_post", SCRIPT)
dsvlm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dsvlm)


class ThemeScopeTests(unittest.TestCase):
    def test_blank_snake_case_theme_does_not_shadow_valid_camel_case_alias(self):
        result = dsvlm.main(
            theme_label="demo",
            theme_type_id="   ",
            themeTypeId="theme-B",
            rules=[],
            dry_run=True,
        )["api_result"][0]

        self.assertEqual(result["payload"]["themeTypeId"], "theme-B")

    def test_conflicting_top_level_theme_aliases_fail_before_network(self):
        unexpected = mock.Mock(
            side_effect=AssertionError("conflicting aliases must fail before network")
        )

        with (
            mock.patch.dict(
                dsvlm.os.environ,
                {"DSVLM_DYNAMIC_AUTH": "false"},
                clear=True,
            ),
            mock.patch.object(dsvlm, "ENV", {}),
            mock.patch.object(dsvlm, "ensure_authorization", new=unexpected),
            mock.patch.object(dsvlm, "post_payload", new=unexpected),
        ):
            result = dsvlm.main(
                theme_label="demo",
                theme_type_id="theme-A",
                themeTypeId="theme-B",
                rules=[],
                dry_run=False,
                authorization="fake-manual-authorization",
                force_post=True,
            )["api_result"][0]

        self.assertEqual(result["status"], "THEME_MISMATCH_NOT_POSTED")
        self.assertFalse(result["success"])
        unexpected.assert_not_called()

    def test_blank_manual_authorization_is_missing_without_network(self):
        unexpected = mock.Mock(
            side_effect=AssertionError("blank authorization must not reach network")
        )

        with (
            mock.patch.dict(
                dsvlm.os.environ,
                {"DSVLM_DYNAMIC_AUTH": "false"},
                clear=True,
            ),
            mock.patch.object(dsvlm, "ENV", {}),
            mock.patch.object(dsvlm, "post_payload", new=unexpected),
        ):
            result = dsvlm.main(
                theme_label="demo",
                theme_type_id="theme-A",
                rules=[],
                dry_run=False,
                authorization="   ",
                force_post=True,
            )["api_result"][0]

        self.assertEqual(result["status"], "AUTH_MISSING_NOT_POSTED")
        unexpected.assert_not_called()

    def test_blank_manual_authorization_is_not_added_to_dry_run_headers(self):
        with (
            mock.patch.dict(
                dsvlm.os.environ,
                {"DSVLM_DYNAMIC_AUTH": "false"},
                clear=True,
            ),
            mock.patch.object(dsvlm, "ENV", {}),
        ):
            result = dsvlm.main(
                theme_label="demo",
                theme_type_id="theme-A",
                rules=[],
                dry_run=True,
                authorization="   ",
            )["api_result"][0]

        self.assertNotIn("Authorization", result["headers"])

    def test_manual_authorization_is_stripped_before_request(self):
        captured = {}

        def fake_post_payload(api_base, endpoint, payload, headers, timeout, method="POST"):
            captured.update(headers)
            return {"success": True}

        with (
            mock.patch.dict(
                dsvlm.os.environ,
                {"DSVLM_DYNAMIC_AUTH": "false"},
                clear=True,
            ),
            mock.patch.object(dsvlm, "ENV", {}),
            mock.patch.object(dsvlm, "post_payload", side_effect=fake_post_payload),
        ):
            result = dsvlm.main(
                theme_label="demo",
                theme_type_id="theme-A",
                rules=[],
                dry_run=False,
                authorization="  Bearer fake-manual-authorization  ",
                force_post=True,
            )["api_result"][0]

        self.assertTrue(result["success"])
        self.assertEqual(
            captured["Authorization"],
            "Bearer fake-manual-authorization",
        )

    def test_data_page_payload_rejects_missing_or_blank_theme(self):
        with (
            mock.patch.dict(
                dsvlm.os.environ,
                {"DSVLM_THEME_TYPE_ID": "stale-env-theme"},
                clear=True,
            ),
            mock.patch.object(
                dsvlm,
                "ENV",
                {"DSVLM_THEME_TYPE_ID": "stale-file-theme"},
            ),
        ):
            for value in (None, "", "   "):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        dsvlm.build_data_page_payload(theme_type_id=value)

    def test_data_page_payload_normalizes_explicit_theme(self):
        payload = dsvlm.build_data_page_payload(theme_type_id="  theme-A  ")

        self.assertEqual(payload["themeTypeId"], "theme-A")

    def test_data_page_blank_snake_alias_does_not_shadow_camel_alias(self):
        payload = dsvlm.build_data_page_payload(
            theme_type_id="   ",
            themeTypeId="theme-B",
        )

        self.assertEqual(payload["themeTypeId"], "theme-B")

    def test_fetch_page_rejects_conflicting_theme_aliases_before_auth(self):
        unexpected = mock.Mock(
            side_effect=AssertionError("conflicting aliases must fail before auth")
        )

        with (
            mock.patch.object(dsvlm, "ensure_authorization", new=unexpected),
            mock.patch.object(dsvlm, "post_payload", new=unexpected),
        ):
            with self.assertRaises(ValueError):
                dsvlm.fetch_theme_data_page(
                    theme_type_id="theme-A",
                    themeTypeId="theme-B",
                )

        unexpected.assert_not_called()

    def test_fetch_page_rejects_blank_theme_before_auth_or_network(self):
        unexpected = mock.Mock(
            side_effect=AssertionError("blank theme must fail before auth or network")
        )

        with (
            mock.patch.object(dsvlm, "ensure_authorization", new=unexpected),
            mock.patch.object(dsvlm, "post_payload", new=unexpected),
        ):
            with self.assertRaises(ValueError):
                dsvlm.fetch_theme_data_page(theme_type_id="   ")

        unexpected.assert_not_called()

    def test_authorization_probe_uses_explicit_current_theme(self):
        captured = {}

        def fake_fetch_theme_data_page(**kwargs):
            captured.update(kwargs)
            return {"success": True}

        with (
            mock.patch.object(dsvlm, "_setting") as setting,
            mock.patch.object(
                dsvlm,
                "fetch_theme_data_page",
                side_effect=fake_fetch_theme_data_page,
            ),
        ):
            setting.side_effect = lambda name, default="": (
                "fake-access-token" if name == "DSVLM_ACCESS_TOKEN" else default
            )
            result = dsvlm.ensure_authorization(
                "https://example.invalid",
                1,
                theme_type_id="theme-current",
            )

        self.assertTrue(result["success"])
        self.assertEqual(captured["theme_type_id"], "theme-current")
        self.assertFalse(captured["ensure_auth"])

    def test_main_passes_payload_theme_to_authorization_probe(self):
        captured = {}

        def fake_ensure_authorization(api_base, timeout, theme_type_id=None):
            captured["theme_type_id"] = theme_type_id
            return {"success": True}

        with (
            mock.patch.object(
                dsvlm,
                "ensure_authorization",
                side_effect=fake_ensure_authorization,
            ),
            mock.patch.object(
                dsvlm,
                "post_payload",
                return_value={"success": True},
            ),
        ):
            result = dsvlm.main(
                payload={
                    "themeTypeId": "theme-payload",
                    "themeLabel": "demo",
                    "ruleList": [],
                },
                dry_run=False,
                authorization="fake-manual-authorization",
                force_post=True,
            )["api_result"][0]

        self.assertTrue(result["success"])
        self.assertEqual(captured["theme_type_id"], "theme-payload")

    def test_detail_read_remains_usable_without_hidden_theme_probe(self):
        ensure = mock.Mock(return_value={"success": True})
        detail = {
            "success": True,
            "response_text": "{}",
            "response_json": {"data": {"id": "algorithm-1"}},
        }

        with (
            mock.patch.object(dsvlm, "ensure_authorization", new=ensure),
            mock.patch.object(dsvlm, "fetch_theme_detail", return_value=detail),
        ):
            result = dsvlm.fetch_theme_data_detail(theme_id="algorithm-1")

        self.assertTrue(result["success"])
        self.assertEqual(
            ensure.call_args.kwargs.get("theme_type_id"),
            None,
        )

    def test_fetch_page_uses_explicit_theme_type_id(self):
        captured = {}

        def fake_post_payload(
            api_base,
            endpoint,
            payload,
            headers,
            timeout,
            method="POST",
        ):
            captured.update(payload)
            return {
                "success": True,
                "response_json": {"data": {"list": [], "total": 0}},
            }

        with mock.patch.object(dsvlm, "post_payload", new=fake_post_payload):
            dsvlm.fetch_existing_theme_page(
                "http://example",
                1,
                theme_type_id="theme-B",
            )

        self.assertEqual(captured["themeTypeId"], "theme-B")

    def test_real_post_requires_explicit_theme_without_network(self):
        def unexpected_network(*args, **kwargs):
            self.fail("real post without an explicit theme must not access the network")

        with (
            mock.patch.object(
                dsvlm,
                "ensure_authorization",
                new=unexpected_network,
            ),
            mock.patch.object(dsvlm, "post_payload", new=unexpected_network),
        ):
            result = dsvlm.main(
                theme_label="demo",
                rules=[],
                dry_run=False,
            )["api_result"][0]

        self.assertEqual(result["status"], "THEME_REQUIRED_NOT_POSTED")
        self.assertFalse(result["success"])
        self.assertFalse(result["posted"])

    def test_camel_case_theme_survives_empty_snake_case_alias(self):
        result = dsvlm.main(
            theme_label="demo",
            theme_type_id=None,
            themeTypeId="theme-B",
            rules=[],
            dry_run=True,
        )["api_result"][0]

        self.assertEqual(result["payload"]["themeTypeId"], "theme-B")

    def test_raw_payload_theme_is_explicit_for_full_write(self):
        raw_payload = {
            "themeTypeId": "theme-A",
            "themeLabel": "raw-demo",
            "ruleList": [],
        }
        posted_payloads = []

        def fake_post_payload(
            api_base,
            endpoint,
            payload,
            headers,
            timeout,
            method="POST",
        ):
            posted_payloads.append(payload.copy())
            return {"success": True}

        with (
            mock.patch.object(
                dsvlm,
                "ensure_authorization",
                return_value={"success": True},
            ),
            mock.patch.object(dsvlm, "post_payload", new=fake_post_payload),
        ):
            result = dsvlm.main(
                payload=raw_payload,
                dry_run=False,
                authorization="Bearer test",
                force_post=True,
            )["api_result"][0]

        self.assertEqual(result["status"], "POST_SUCCEEDED_DO_NOT_RETRY")
        self.assertEqual(posted_payloads[0]["themeTypeId"], "theme-A")

    def test_mismatched_top_level_and_payload_themes_fail_before_network(self):
        def unexpected_network(*args, **kwargs):
            self.fail("mismatched themes must fail before network access")

        with (
            mock.patch.object(
                dsvlm,
                "ensure_authorization",
                new=unexpected_network,
            ),
            mock.patch.object(dsvlm, "post_payload", new=unexpected_network),
        ):
            result = dsvlm.main(
                payload={
                    "themeTypeId": "theme-A",
                    "themeLabel": "raw-demo",
                },
                theme_type_id="theme-B",
                dry_run=False,
                authorization="Bearer test",
                force_post=True,
            )["api_result"][0]

        self.assertEqual(result["status"], "THEME_MISMATCH_NOT_POSTED")
        self.assertFalse(result["success"])
        self.assertFalse(result["posted"])

    def test_top_level_theme_is_injected_into_a_copied_raw_payload(self):
        raw_payload = {
            "themeLabel": "raw-demo",
            "ruleList": [],
        }

        result = dsvlm.main(
            payload=raw_payload,
            theme_type_id="theme-A",
            dry_run=True,
        )["api_result"][0]

        self.assertEqual(result["payload"]["themeTypeId"], "theme-A")
        self.assertIsNot(result["payload"], raw_payload)
        self.assertNotIn("themeTypeId", raw_payload)

    def test_raw_payload_theme_is_normalized_before_write(self):
        posted = []

        with (
            mock.patch.object(
                dsvlm,
                "ensure_authorization",
                return_value={"success": True},
            ),
            mock.patch.object(
                dsvlm,
                "post_payload",
                side_effect=lambda api_base, endpoint, payload, headers, timeout, method="POST": (
                    posted.append(payload.copy()) or {"success": True}
                ),
            ),
        ):
            result = dsvlm.main(
                payload={
                    "themeTypeId": "  theme-A  ",
                    "themeLabel": "raw-demo",
                    "ruleList": [],
                },
                dry_run=False,
                authorization="fake-manual-authorization",
                force_post=True,
            )["api_result"][0]

        self.assertTrue(result["success"])
        self.assertEqual(posted[0]["themeTypeId"], "theme-A")

    def test_built_payload_keeps_one_theme_through_lookup_sort_and_post(self):
        seen = {}
        page_calls = []

        def fake_fetch_page(api_base, timeout, **kwargs):
            page_calls.append(kwargs)
            return {
                "success": True,
                "response_json": {
                    "data": {"total": 8, "list": [{"sort": 1}, {"sort": 7}]}
                },
            }

        def fake_post_payload(
            api_base,
            endpoint,
            payload,
            headers,
            timeout,
            method="POST",
        ):
            seen["post"] = payload.copy()
            return {"success": True}

        with (
            mock.patch.object(
                dsvlm,
                "ensure_authorization",
                return_value={"success": True},
            ),
            mock.patch.object(dsvlm, "fetch_existing_theme_page", new=fake_fetch_page),
            mock.patch.object(dsvlm, "post_payload", new=fake_post_payload),
        ):
            result = dsvlm.main(
                theme_label="built-demo",
                theme_type_id="theme-B",
                rules=[],
                dry_run=False,
                authorization="Bearer test",
                skip_existing=True,
                _auto_sort=True,
            )["api_result"][0]

        self.assertEqual(result["status"], "POST_SUCCEEDED_DO_NOT_RETRY")
        self.assertEqual(len(page_calls), 1)
        self.assertEqual(page_calls[0]["theme_type_id"], "theme-B")
        self.assertEqual(seen["post"]["themeTypeId"], "theme-B")
        self.assertEqual(seen["post"]["sort"], 9)
