import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "post_theme_config.py"
SPEC = importlib.util.spec_from_file_location("dsvlm_post_parsing", SCRIPT)
dsvlm = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(dsvlm)


class AgentOutputParsingTests(unittest.TestCase):
    def test_loop_request_cannot_authorize_a_write(self):
        parsed = dsvlm.parse_user_request("/dsvlm 评审：人员落水 --post")

        self.assertTrue(parsed["loop"])
        self.assertFalse(parsed["post"])
        self.assertEqual(parsed["algorithm_name"], "")

    def test_build_payload_has_no_hidden_theme_default(self):
        payload = dsvlm.build_payload(theme_label="测试算法", rules=[])

        self.assertEqual(payload["themeTypeId"], "")

    def test_target_rule_requires_an_explicit_threshold(self):
        with self.assertRaisesRegex(ValueError, "阈值"):
            dsvlm._platform_rule(
                "目标理解 / 多模态目标理解 / person / 大于 / 0"
            )

    def test_structured_payload_tracks_explicit_fields_and_request_name_wins(self):
        parsed = dsvlm.parse_structured_payload(
            {
                "algorithm": "payload-name",
                "mode": "深度解析模式",
                "level": "五级预警",
                "area_flag": False,
                "portal_flag": False,
                "docking_code": "",
                "sort": "auto",
                "conditions": [
                    "目标理解 / 多模态目标理解 / person / 大于 / 0 / 阈值 70",
                    "内容理解 / 正向思维1 / 戴红色帽子",
                ],
            },
            "/dsvlm 新建：测试；算法名：request-name；主题：wbr --post",
        )

        self.assertEqual(parsed["theme_label"], "request-name")
        self.assertEqual(parsed["mode"], 2)
        self.assertEqual(parsed["level"], 5)
        self.assertFalse(parsed["area_flag"])
        self.assertFalse(parsed["portal_flag"])
        self.assertEqual(parsed["docking_code"], "")
        self.assertTrue(parsed["_auto_sort"])
        self.assertEqual(
            parsed["_provided_fields"],
            {
                "themeLabel",
                "mode",
                "level",
                "areaFlag",
                "portalFlag",
                "dockingCode",
                "sort",
                "rule",
                "ruleList",
            },
        )

    def test_structured_payload_requires_nonempty_conditions(self):
        with self.assertRaisesRegex(ValueError, "conditions"):
            dsvlm.parse_structured_payload(
                {"algorithm": "demo", "conditions": []},
                "/dsvlm 新建：测试；主题：wbr",
            )

    def test_update_request_preserves_requirement_description_and_authorization(self):
        parsed = dsvlm.parse_user_request(
            "/dsvlm 优化：识别火情；问题：灯光误报；"
            "补充：排除稳定灯光和车灯；主题：wbr --post"
        )

        self.assertEqual(parsed["algorithm_name"], "识别火情")
        self.assertEqual(parsed["update_requirement"], "灯光误报")
        self.assertEqual(parsed["description"], "排除稳定灯光和车灯")
        self.assertEqual(parsed["theme_name"], "wbr")
        self.assertTrue(parsed["update"])
        self.assertTrue(parsed["post"])

    def test_less_common_components_keep_their_platform_ids(self):
        cases = {
            "逻辑理解 / 前置条件结束": {"parsingId": "logic_pre", "rule": ""},
            "逻辑理解 / 预警内容描述 / 发现明火": {
                "parsingId": "alarm_msg",
                "rule": "发现明火",
            },
            "全结构化理解 / 全结构化理解 / 全量提取画面结构": {
                "parsingId": "all_struct",
                "rule": "全量提取画面结构",
            },
            "全结构化理解 / 全结构化理解-深度 / 深度提取画面结构": {
                "parsingId": "all_struct_dec",
                "rule": "深度提取画面结构",
            },
        }

        for rule, expected in cases.items():
            with self.subTest(rule=rule):
                self.assertEqual(dsvlm._platform_rule(rule), expected)

    def test_update_merge_preserves_fields_not_explicitly_provided(self):
        payload = dsvlm.build_payload(
            theme_label="垃圾车识别",
            rules=[{"parsingId": "1", "rule": "新规则"}],
        )
        merged = dsvlm._apply_existing_for_update(
            payload,
            {
                "id": "algorithm-1",
                "themeLabel": "垃圾车识别",
                "themeTypeId": "theme-1",
                "sort": "7",
                "coding": "keep-me",
                "mode": 2,
                "level": 5,
                "areaFlag": False,
                "remark": "keep-remark",
            },
            {"themeLabel", "rule", "ruleList"},
            auto_sort=True,
        )

        self.assertEqual(merged["id"], "algorithm-1")
        self.assertEqual(merged["themeTypeId"], "theme-1")
        self.assertEqual(merged["sort"], 7)
        self.assertEqual(merged["coding"], "keep-me")
        self.assertEqual(merged["mode"], 2)
        self.assertEqual(merged["level"], 5)
        self.assertFalse(merged["areaFlag"])
        self.assertEqual(merged["remark"], "keep-remark")

    def test_update_merge_applies_explicit_false_and_blank_values(self):
        payload = dsvlm.build_payload(
            theme_label="垃圾车识别",
            portal_flag=False,
            docking_code="",
            rules=[{"parsingId": "1", "rule": "新规则"}],
        )
        merged = dsvlm._apply_existing_for_update(
            payload,
            {
                "id": "algorithm-1",
                "themeTypeId": "theme-1",
                "portalFlag": 1,
                "dockingCode": "OLD",
            },
            {"portalFlag", "dockingCode", "rule", "ruleList"},
        )

        self.assertEqual(merged["portalFlag"], 0)
        self.assertEqual(merged["dockingCode"], "")

if __name__ == "__main__":
    unittest.main()
