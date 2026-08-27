import importlib.util
from pathlib import Path
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "post_theme_config.py"
SPEC = importlib.util.spec_from_file_location("dsvlm_simplified_theme_lookup", SCRIPT)
dsvlm = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(dsvlm)


class SimplifiedRequestTests(unittest.TestCase):
    def test_new_request_uses_custom_theme_name(self):
        parsed = dsvlm.parse_user_request(
            "/dsvlm 新建：识别垃圾车；算法名：垃圾车识别；主题：园区A --post"
        )

        self.assertEqual(parsed["scene"], "识别垃圾车")
        self.assertEqual(parsed["algorithm_name"], "垃圾车识别")
        self.assertEqual(parsed["theme_name"], "园区A")
        self.assertTrue(parsed["post"])

    def test_theme_name_is_not_hardcoded_to_wbr(self):
        for theme_name in ("wbr", "港口二期"):
            with self.subTest(theme_name=theme_name):
                parsed = dsvlm.parse_user_request(
                    "/dsvlm 优化：识别火情；问题：灯光误报；主题：%s" % theme_name
                )
                self.assertEqual(parsed["theme_name"], theme_name)
                self.assertTrue(parsed["update"])

    def test_deprecated_user_flags_are_rejected(self):
        for request in (
            "/dsvlm 场景：人员落水 --loop",
            "/dsvlm --识别火情 --update --灯光误报",
            "/dsvlm 场景：垃圾车 --垃圾车识别 --d:补充",
        ):
            with self.subTest(request=request):
                with self.assertRaisesRegex(ValueError, "已移除"):
                    dsvlm.parse_user_request(request)


class ThemeCatalogTests(unittest.TestCase):
    def test_catalog_reuses_8898_auth_and_current_theme_endpoint(self):
        response = {
            "success": True,
            "response_json": {
                "code": 0,
                "data": [{"id": "id-a", "themeName": "园区A"}],
            },
        }
        with (
            mock.patch.object(
                dsvlm,
                "ensure_authorization",
                return_value={"success": True},
            ) as ensure_auth,
            mock.patch.object(dsvlm, "get_payload", return_value=response) as get,
        ):
            items = dsvlm.fetch_theme_catalog(
                api_base="https://platform.example.com",
                timeout=7,
            )

        self.assertEqual(items, [{"id": "id-a", "themeName": "园区A"}])
        ensure_auth.assert_called_once_with("https://platform.example.com", 7)
        self.assertEqual(get.call_args.args[1], "/s/theme/type/all")

    def test_exact_custom_name_resolves_theme_type_id(self):
        with mock.patch.object(
            dsvlm,
            "fetch_theme_catalog",
            return_value=[
                {"themeName": "wbr", "themeTypeId": "id-wbr"},
                {"themeName": "港口二期", "id": "id-port"},
            ],
        ):
            result = dsvlm.resolve_theme_name(" 港口二期 ")

        self.assertEqual(result["status"], "THEME_RESOLVED")
        self.assertEqual(result["theme_type_id"], "id-port")

    def test_matching_is_case_sensitive_and_fails_closed(self):
        with mock.patch.object(
            dsvlm,
            "fetch_theme_catalog",
            return_value=[{"themeName": "wbr", "themeTypeId": "id-wbr"}],
        ):
            result = dsvlm.resolve_theme_name("WBR")

        self.assertEqual(result["status"], "THEME_NOT_FOUND")
        self.assertFalse(result["success"])

    def test_duplicate_exact_names_are_ambiguous(self):
        with mock.patch.object(
            dsvlm,
            "fetch_theme_catalog",
            return_value=[
                {"themeName": "wbr", "themeTypeId": "id-1"},
                {"themeName": "wbr", "themeTypeId": "id-2"},
            ],
        ):
            result = dsvlm.resolve_theme_name("wbr")

        self.assertEqual(result["status"], "THEME_AMBIGUOUS")
        self.assertNotIn("theme_type_id", result)

    def test_main_injects_resolved_id(self):
        with mock.patch.object(
            dsvlm,
            "resolve_theme_name",
            return_value={
                "success": True,
                "status": "THEME_RESOLVED",
                "theme_name": "园区A",
                "theme_type_id": "id-a",
            },
        ):
            result = dsvlm.main(
                theme_name="园区A",
                theme_label="测试算法",
                rules=[],
                dry_run=True,
            )

        payload = result["api_result"][0]["payload"]
        self.assertEqual(payload["themeTypeId"], "id-a")

    def test_successful_theme_catalog_avoids_a_redundant_auth_probe(self):
        page = {
            "success": True,
            "response_json": {"data": {"total": 0, "list": []}},
        }
        unexpected_probe = mock.Mock(
            side_effect=AssertionError("catalog success already verified auth")
        )
        with (
            mock.patch.object(
                dsvlm,
                "resolve_theme_name",
                return_value={
                    "success": True,
                    "status": "THEME_RESOLVED",
                    "theme_name": "园区A",
                    "theme_type_id": "id-a",
                },
            ),
            mock.patch.object(dsvlm, "ensure_authorization", new=unexpected_probe),
            mock.patch.object(dsvlm, "fetch_existing_theme_page", return_value=page),
            mock.patch.object(dsvlm, "post_payload", return_value={"success": True}),
            mock.patch.dict(
                dsvlm.os.environ,
                {"DSVLM_ACCESS_TOKEN": "valid-runtime-token-123"},
                clear=True,
            ),
            mock.patch.object(dsvlm, "ENV", {}),
        ):
            result = dsvlm.main(
                theme_name="园区A",
                theme_label="测试算法",
                rules=[{"parsingId": "1", "rule": "测试"}],
                dry_run=False,
            )["api_result"][0]

        self.assertEqual(result["status"], "POST_SUCCEEDED_DO_NOT_RETRY")

    def test_main_stops_when_explicit_id_disagrees_with_name(self):
        with mock.patch.object(
            dsvlm,
            "resolve_theme_name",
            return_value={
                "success": True,
                "status": "THEME_RESOLVED",
                "theme_name": "园区A",
                "theme_type_id": "id-a",
            },
        ):
            result = dsvlm.main(
                theme_name="园区A",
                theme_type_id="id-b",
                theme_label="测试算法",
                rules=[],
                dry_run=False,
            )

        item = result["api_result"][0]
        self.assertEqual(item["status"], "THEME_MISMATCH_NOT_POSTED")
        self.assertFalse(item["posted"])

    def test_optimization_requires_theme_even_without_post(self):
        result = dsvlm.main(
            theme_label="识别火情",
            rules=[],
            update_existing=True,
            dry_run=True,
        )

        item = result["api_result"][0]
        self.assertEqual(item["status"], "THEME_REQUIRED_NOT_POSTED")
        self.assertFalse(item["posted"])


if __name__ == "__main__":
    unittest.main()
