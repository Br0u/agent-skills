#!/usr/bin/env python3
"""华鲲元启视频算法配置客户端；默认预览，只认原始用户请求里的 --post。"""

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_API_BASE = "http://61.172.168.94:8898"
DEFAULT_ENDPOINT = "/s/theme/data"
DEFAULT_DATA_PAGE_ENDPOINT = "/s/theme/data/page"
DEFAULT_DATA_DETAIL_ENDPOINT = "/s/theme/data/{id}"
DEFAULT_THEME_CATALOG_ENDPOINT = "/s/theme/type/all"
DEFAULT_CAPTCHA_ENABLED_ENDPOINT = "/s/sys/auth/captcha/enabled"
DEFAULT_SM2_PUBLIC_KEY = (
    "040a302b5e4b961afb3908a4ae191266ac5866be100fc52e3b8dba9707c8620e64ae790ceffc"
    "3bfbf262dc098d293dd3e303356cb91b54861c767997799d2f0060"
)
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = SKILL_DIR / ".env"
SENSITIVE_HEADER_NAMES = {"Authorization", "Cookie", "X-CSRF-Token", "access-token"}
REFRESH_TOKEN_KEYS = (
    "access_token",
    "accessToken",
    "access-token",
    "token",
    "authorization",
)
MIN_REFRESH_TOKEN_LENGTH = 16
MAX_REFRESH_TOKEN_LENGTH = 8192
ENV_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MODE_MAP = {
    "通用模式": 1,
    "普通模式": 1,
    "深度解析模式": 2,
    "深度模式": 2,
    "深度串行解析": 3,
}
LEVEL_MAP = {
    "一级预警": 1,
    "一级": 1,
    "二级预警": 2,
    "二级": 2,
    "三级预警": 3,
    "三级": 3,
    "四级预警": 4,
    "四级": 4,
    "五级预警": 5,
    "五级": 5,
}
PARSING_ID_MAP = {
    ("内容理解", "正向思维1"): "1",
    ("内容理解", "正向思维2"): "11",
    ("内容理解", "正向思维20"): "21",
    ("内容理解", "反向思维1"): "2",
    ("内容理解", "反向思维2"): "12",
    ("内容理解", "反向思维20"): "22",
    ("深度内容理解", "正向深度思维1"): "101",
    ("深度内容理解", "正向深度思维2"): "103",
    ("深度内容理解", "正向深度思维20"): "121",
    ("深度内容理解", "反向深度思维1"): "102",
    ("深度内容理解", "反向深度思维2"): "104",
    ("深度内容理解", "反向深度思维20"): "122",
    ("目标理解", "通用目标理解"): "counter",
    ("目标理解", "多模态目标理解"): "dmt_counter",
    ("文字理解", "OCR"): "ocr",
    ("文字理解", "文字理解"): "ocr",
    ("逻辑理解", "或者"): "logic_or",
    ("逻辑理解", "前置条件结束"): "logic_pre",
    ("逻辑理解", "输出分支预警"): "logic_branch",
    ("逻辑理解", "输出其他预警"): "logic_else",
    ("逻辑理解", "预警结果反转"): "alarm_reverse",
    ("逻辑理解", "预警内容输出"): "alarm_ocr",
    ("逻辑理解", "预警结果数量"): "alarm_counter",
    ("逻辑理解", "预警框内目标数量"): "alarm_inner",
    ("逻辑理解", "预警内容描述"): "alarm_msg",
    ("全结构化理解", "全结构化理解"): "all_struct",
    ("全结构化理解", "全结构化理解-深度"): "all_struct_dec",
}
TARGET_NAME_MAP = {
    "人": "person",
    "机动车辆": "car",
    "汽车": "car",
    "卡车": "truck",
    "摩托车/电动车": "motorcycle",
    "公交车": "bus",
    "火车": "train",
    "船": "boat",
    "红绿灯": "traffic light",
    "狗": "dog",
    "猫": "cat",
    "手包": "handbag",
    "行李箱": "suitcase",
    "背包": "backpack",
    "屏幕": "tv",
    "笔记本电脑": "laptop",
    "椅子": "chair",
    "键盘": "keyboard",
    "电话": "cell phone",
    "盆栽植物": "potted plant",
    "瓶子": "bottle",
    "杯子": "cup",
    "碗": "bowl",
    "床": "bed",
    "伞": "umbrella",
    "香蕉": "banana",
}
TARGET_OPERATOR_MAP = {"大于": "gt", "小于": "lt", "等于": "eq", "gt": "gt", "lt": "lt", "eq": "eq"}


class PlatformTransportError(RuntimeError):
    """A platform request was blocked or failed without exposing its body."""

    def __init__(self, message, *, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class ThemeCatalogError(RuntimeError):
    """A DSVLM theme-catalog lookup failed without exposing credentials."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so credential-bearing requests stay on one origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_env_file(path=DEFAULT_ENV_PATH):
    """读取 skill 目录下的 .env；不依赖 python-dotenv，减少外部依赖。"""
    values = {}
    path = Path(path)
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


ENV = load_env_file()


def _setting(name, default=""):
    return os.environ.get(name) or ENV.get(name) or default


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalized_theme_type_id(value):
    return str(value).strip() if value is not None else ""


def _normalized_authorization(value):
    return str(value).strip() if value is not None else ""


def _require_theme_type_id(value):
    theme_type_id = _normalized_theme_type_id(value)
    if not theme_type_id:
        raise ValueError("theme_type_id is required")
    return theme_type_id


def _resolve_theme_type_aliases(values, *, required=False):
    snake_theme_type_id = _normalized_theme_type_id(values.get("theme_type_id"))
    camel_theme_type_id = _normalized_theme_type_id(values.get("themeTypeId"))
    if (
        snake_theme_type_id
        and camel_theme_type_id
        and snake_theme_type_id != camel_theme_type_id
    ):
        raise ValueError("theme_type_id and themeTypeId do not match")
    resolved = snake_theme_type_id or camel_theme_type_id
    return _require_theme_type_id(resolved) if required else resolved


def _validate_platform_transport(url):
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme == "https":
        return
    if scheme == "http" and _as_bool(
        _setting("DSVLM_ALLOW_INSECURE_HTTP", "false"),
        False,
    ):
        return
    if scheme == "http":
        raise PlatformTransportError("plain HTTP is disabled")
    raise PlatformTransportError("unsupported platform URL scheme")


def _open_platform_request(request, timeout):
    _validate_platform_transport(request.full_url)
    opener = urllib.request.build_opener(NoRedirectHandler())
    try:
        return opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        status_code = error.code
        error.close()
        raise PlatformTransportError(
            "HTTP %s" % status_code,
            status_code=status_code,
        ) from None
    except urllib.error.URLError:
        raise PlatformTransportError("platform request failed") from None


def _catalog_items(response):
    for container in (response, response.get("data")):
        if isinstance(container, list):
            return container
        if isinstance(container, dict):
            for key in ("dataList", "list", "records"):
                if isinstance(container.get(key), list):
                    return container[key]
    raise ThemeCatalogError("CATALOG_FAILED", "主题目录返回中缺少主题列表。")


def fetch_theme_catalog(*, api_base=None, timeout=None):
    """Reuse 8898 authentication and return the current theme records."""
    api_base = (api_base or _setting("DSVLM_API_BASE", DEFAULT_API_BASE)).strip().rstrip("/")
    timeout = _as_int(timeout or _setting("DSVLM_TIMEOUT"), 30)
    auth = ensure_authorization(api_base, timeout)
    if not auth.get("success"):
        raise ThemeCatalogError("AUTH_FAILED", "主题目录登录失败。")

    endpoint = _setting("DSVLM_THEME_CATALOG_ENDPOINT", DEFAULT_THEME_CATALOG_ENDPOINT)
    catalog = get_payload(api_base, endpoint, _base_headers(api_base), timeout)
    if not catalog.get("success"):
        auth = refresh_authorization(timeout=timeout)
        if not auth.get("success"):
            raise ThemeCatalogError("AUTH_FAILED", "主题目录登录失败。")
        catalog = get_payload(api_base, endpoint, _base_headers(api_base), timeout)
    if not catalog.get("success"):
        raise ThemeCatalogError("CATALOG_FAILED", "读取主题目录失败。")
    return _catalog_items(catalog.get("response_json") or {})


def resolve_theme_name(theme_name, **kwargs):
    """Resolve one user-supplied theme name by exact, case-sensitive match."""
    normalized = str(theme_name or "").strip()
    if not normalized:
        return {
            "success": False,
            "status": "THEME_NAME_REQUIRED",
            "message": "主题名不能为空。",
        }
    try:
        items = fetch_theme_catalog(**kwargs)
    except ThemeCatalogError as error:
        return {"success": False, "status": error.status, "message": str(error)}

    ids = {
        str(item.get("themeTypeId") or item.get("id") or "").strip()
        for item in items
        if isinstance(item, dict)
        and str(item.get("themeName") or "").strip() == normalized
        and str(item.get("themeTypeId") or item.get("id") or "").strip()
    }
    if not ids:
        return {
            "success": False,
            "status": "THEME_NOT_FOUND",
            "message": "未找到精确匹配的主题名：%s。" % normalized,
        }
    if len(ids) != 1:
        return {
            "success": False,
            "status": "THEME_AMBIGUOUS",
            "message": "主题名存在多个匹配：%s。" % normalized,
        }
    return {
        "success": True,
        "status": "THEME_RESOLVED",
        "theme_name": normalized,
        "theme_type_id": ids.pop(),
    }


def _is_auto_sort(value):
    return str(value or "").strip().lower() in {"", "auto", "自动"}


def _normalize_rule_list(value):
    if not value:
        value = [{"parsingId": "1", "rule": ""}]
    if isinstance(value, str):
        value = json.loads(value)

    rules = []
    for item in value:
        parsing_id = item.get("parsingId", item.get("parsing_id", "1"))
        rules.append({
            "parsingId": str(parsing_id),
            "rule": item.get("rule", ""),
            "monitoringAreaCode": item.get("monitoringAreaCode", ""),
            "ratio": item.get("ratio", 0.0),
            "ratioY": item.get("ratioY", 0.0),
            "ratioMax": item.get("ratioMax", 100.0),
            "ratioYMax": item.get("ratioYMax", 100.0),
        })
    return rules or _normalize_rule_list([{"parsingId": "1", "rule": ""}])


def build_payload(**kwargs):
    """构造 /s/theme/data 保存接口需要的 payload。字段名来自浏览器抓包。"""
    rule_list = _normalize_rule_list(
        kwargs.get("rule_list") or kwargs.get("rules") or kwargs.get("conditions")
    )
    theme_label = (
        kwargs.get("theme_label")
        or kwargs.get("algorithm")
        or kwargs.get("name")
        or ""
    )

    return {
        "id": kwargs.get("id", ""),
        "themeTypeId": (
            kwargs.get("theme_type_id")
            or kwargs.get("themeTypeId")
            or ""
        ),
        "themeLabel": theme_label,
        "alarmOcrFlag": _as_bool(kwargs.get("alarm_ocr_flag", kwargs.get("alarmOcrFlag")), False),
        "areaFlag": _as_bool(kwargs.get("area_flag", kwargs.get("areaFlag")), True),
        "coding": kwargs.get("coding", ""),
        "dockingCode": kwargs.get("docking_code", kwargs.get("dockingCode", "")),
        "extensionRatio": _as_int(kwargs.get("extension_ratio", kwargs.get("extensionRatio")), 0),
        "extensionType": _as_int(kwargs.get("extension_type", kwargs.get("extensionType")), 2),
        "isForward": _as_bool(kwargs.get("is_forward", kwargs.get("isForward")), True),
        "level": _as_int(kwargs.get("level"), 1),
        "mode": _as_int(kwargs.get("mode"), 1),
        "parsingWordsId": kwargs.get("parsing_words_id", kwargs.get("parsingWordsId", "")),
        "parsingWordsId2": kwargs.get("parsing_words_id2", kwargs.get("parsingWordsId2", "")),
        "parsingWordsId3": kwargs.get("parsing_words_id3", kwargs.get("parsingWordsId3", "")),
        "portalFlag": _as_int(kwargs.get("portal_flag", kwargs.get("portalFlag")), 0),
        "question": kwargs.get("question", ""),
        "question2": kwargs.get("question2", ""),
        "question3": kwargs.get("question3", ""),
        "remark": kwargs.get("remark", ""),
        "rule": json.dumps(rule_list, ensure_ascii=False),
        "ruleList": rule_list,
        "sort": _as_int(kwargs.get("sort"), 1),
        "structFlag": _as_int(kwargs.get("struct_flag", kwargs.get("structFlag")), 0),
        "targetExtensionRatio": kwargs.get(
            "target_extension_ratio", kwargs.get("targetExtensionRatio", "")
        ),
    }


def build_data_page_payload(**kwargs):
    """构造 /s/theme/data/page 列表接口 payload；只读，用来验证链路。"""
    theme_type_id = _resolve_theme_type_aliases(kwargs, required=True)
    return {
        "themeLabel": kwargs.get("theme_label", ""),
        "themeTypeId": theme_type_id,
        "page": _as_int(kwargs.get("page"), 1),
        "limit": _as_int(kwargs.get("limit"), 20),
        "order": kwargs.get("order", "sort"),
        "asc": _as_bool(kwargs.get("asc"), True),
        "pageSizes": kwargs.get("page_sizes", [20, 50, 100, 200]),
    }


def _as_percent_int(value, default=0):
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else default


def _parse_choice(value, choices, default, label):
    value = str(value or "").strip()
    if not value:
        return default
    parsed = int(value) if value.isdigit() else choices.get(value)
    if parsed not in set(choices.values()):
        raise ValueError("unknown %s: %s" % (label, value))
    return parsed


def _parse_flag(value, default, label):
    if isinstance(value, bool):
        return value
    value = str(value if value is not None else "").strip()
    if not value:
        return default
    if value in {"关", "关闭", "false", "False", "0", "否"}:
        return False
    if value in {"开", "开启", "true", "True", "1", "是"}:
        return True
    raise ValueError("unknown %s: %s" % (label, value))


def _confidence_value(parts):
    for part in parts:
        match = re.fullmatch(r"阈值\s*(\d+(?:\.\d+)?)%?", part.strip())
        if match:
            value = float(match.group(1))
            return str(value / 100 if value > 1 else value).rstrip("0").rstrip(".")
    raise ValueError("目标规则必须显式填写阈值，例如：阈值 60")


def _target_rule(component, parts):
    if len(parts) < 4:
        raise ValueError(
            "目标规则必须填写数量和阈值: %s / %s"
            % (component, " / ".join(parts))
        )
    target = TARGET_NAME_MAP.get(parts[0], parts[0])
    operator = TARGET_OPERATOR_MAP.get(parts[1])
    if not operator:
        raise ValueError("unknown target operator: %s" % parts[1])
    count = _as_int(parts[2], 0)
    confidence = _confidence_value(parts[3:])
    return "%s|%s|%s|%s" % (target, operator, count, confidence)


def _platform_rule(raw_rule):
    parts = [part.strip() for part in raw_rule.split("/") if part.strip()]
    if len(parts) < 2:
        raise ValueError("invalid 思维条件: %s" % raw_rule)
    module, component = parts[0], parts[1]
    parsing_id = PARSING_ID_MAP.get((module, component))
    if not parsing_id:
        raise ValueError("unknown 思维条件 component: %s / %s" % (module, component))
    if module == "目标理解":
        rule = _target_rule(component, parts[2:])
    elif module == "逻辑理解":
        rule = " / ".join(parts[2:]).strip()
    else:
        rule = " / ".join(parts[2:]).strip()
        if not rule:
            raise ValueError("missing rule text: %s" % raw_rule)
    return {"parsingId": parsing_id, "rule": rule}


def parse_user_request(user_request):
    """解析简化调用格式：新建、评审、优化、配置；仅保留 --post。"""
    empty = {
        "action": "",
        "scene": "",
        "algorithm_name": "",
        "theme_name": "",
        "post": False,
        "update": False,
        "update_requirement": "",
        "description": "",
        "loop": False,
        "config": False,
    }
    text = str(user_request or "").strip()
    if not text:
        return empty
    if re.search(r"--\s*(?:loop|save|update)\b|--\s*d\s*[:：]", text, re.IGNORECASE):
        raise ValueError("--loop、--save、--update 和 --d: 已移除，请使用新建、评审、优化。")
    text = re.sub(r"^/dsvlm\s*", "", text, flags=re.IGNORECASE).strip()
    post = bool(re.search(r"(?:^|\s)--post\s*$", text))
    text = re.sub(r"(?:^|\s)--post\s*$", "", text).strip()
    if "--post" in text:
        raise ValueError("--post 必须独立放在请求末尾。")
    if text == "配置":
        return dict(empty, action="配置", config=True)

    parts = [part.strip() for part in re.split(r"[；;]|\n+", text) if part.strip()]
    if not parts:
        return empty
    action_match = re.fullmatch(r"(新建|评审|优化)\s*[:：]\s*(.+)", parts[0])
    if not action_match:
        raise ValueError("仅支持：新建：…、评审：…、优化：…、配置。")
    action, subject = action_match.groups()
    fields = {}
    for part in parts[1:]:
        match = re.fullmatch(r"([^:：]+)\s*[:：]\s*(.*)", part)
        if match:
            fields[match.group(1).strip()] = match.group(2).strip()

    result = dict(
        empty,
        action=action,
        post=post if action in {"新建", "优化"} else False,
        update=action == "优化",
        loop=action == "评审",
        theme_name=fields.get("主题", ""),
        description=fields.get("补充", ""),
    )
    if action == "新建":
        result["scene"] = subject.strip()
        result["algorithm_name"] = fields.get("算法名", "")
    elif action == "优化":
        result["algorithm_name"] = subject.strip()
        result["update_requirement"] = fields.get("问题", "")
    else:
        result["scene"] = subject.strip()
    return result


def parse_structured_payload(config, user_request=""):
    """把 stdin JSON 转为 build_payload 参数，并保留显式字段信息。"""
    if not isinstance(config, dict):
        raise ValueError("payload must be a JSON object")
    request_args = parse_user_request(user_request)
    if request_args.get("loop"):
        raise ValueError("review requests cannot build or submit a platform payload")
    allowed = {
        "algorithm",
        "mode",
        "level",
        "area_flag",
        "portal_flag",
        "docking_code",
        "sort",
        "extension_ratio",
        "target_extension_ratio",
        "conditions",
        "remark",
    }
    unknown = set(config) - allowed
    if unknown:
        raise ValueError("unknown payload fields: %s" % ", ".join(sorted(unknown)))
    name = request_args["algorithm_name"] or str(config.get("algorithm") or "").strip()
    conditions = config.get("conditions")
    if not name:
        raise ValueError("missing algorithm name")
    if not isinstance(conditions, list) or not conditions or not all(
        isinstance(item, str) and item.strip() for item in conditions
    ):
        raise ValueError("conditions must be a nonempty list of strings")

    platform_fields = {
        "algorithm": "themeLabel",
        "mode": "mode",
        "level": "level",
        "area_flag": "areaFlag",
        "portal_flag": "portalFlag",
        "docking_code": "dockingCode",
        "sort": "sort",
        "extension_ratio": "extensionRatio",
        "target_extension_ratio": "targetExtensionRatio",
        "remark": "remark",
    }
    provided_fields = {platform_fields[key] for key in config if key in platform_fields}
    provided_fields.update({"themeLabel", "rule", "ruleList"})
    sort_value = config.get("sort", "auto")
    kwargs = {
        "theme_label": name,
        "theme_name": request_args["theme_name"],
        "rules": [_platform_rule(item.strip()) for item in conditions],
        "sort": 1 if _is_auto_sort(sort_value) else _as_int(sort_value, 1),
        "_auto_sort": _is_auto_sort(sort_value),
        "_provided_fields": provided_fields,
        "update_existing": request_args["update"],
    }
    if "mode" in config:
        kwargs["mode"] = _parse_choice(config["mode"], MODE_MAP, 1, "解析模式")
    if "level" in config:
        kwargs["level"] = _parse_choice(config["level"], LEVEL_MAP, 1, "预警等级")
    if "area_flag" in config:
        kwargs["area_flag"] = _parse_flag(config["area_flag"], True, "启用区域框")
    if "portal_flag" in config:
        kwargs["portal_flag"] = _parse_flag(config["portal_flag"], False, "添加到门户")
    if "docking_code" in config:
        kwargs["docking_code"] = str(config["docking_code"] or "")
    if "extension_ratio" in config:
        kwargs["extension_ratio"] = _as_percent_int(config["extension_ratio"], 0)
    if "target_extension_ratio" in config:
        kwargs["target_extension_ratio"] = config["target_extension_ratio"]
    if "remark" in config:
        kwargs["remark"] = str(config["remark"] or "")
    return kwargs


SM2_P = int("FFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00000000FFFFFFFFFFFFFFFF", 16)
SM2_A = int("FFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00000000FFFFFFFFFFFFFFFC", 16)
SM2_B = int("28E9FA9E9D9F5E344D5A9E4BCF6509A7F39789F515AB8F92DDBCBD414D940E93", 16)
SM2_N = int("FFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFF7203DF6B21C6052B53BBF40939D54123", 16)
SM2_G = (
    int("32C4AE2C1F1981195F9904466A39C9948FE30BBFF2660BE1715A4589334C74C7", 16),
    int("BC3736A2F4F6779C59BDCEE36B692153D0A9877CC62A474002DF32E52139F0A0", 16),
)


# 以下 SM2/SM3 是为了复刻前端鉴权逻辑。
# 前端逻辑：Authorization = "04" + sm2Encrypt(access_token + 当前毫秒时间戳)。
# 不引入 gmssl 依赖，避免 demo 脚本在新环境里先卡安装。
def _rotl(value, bits):
    bits %= 32
    return ((value << bits) | (value >> (32 - bits))) & 0xFFFFFFFF


def _sm3_hash(data):
    data = bytes(data)
    length = len(data) * 8
    data += b"\x80"
    data += b"\x00" * ((56 - len(data) % 64) % 64)
    data += length.to_bytes(8, "big")
    vector = [
        0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
        0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E,
    ]
    for offset in range(0, len(data), 64):
        block = data[offset:offset + 64]
        w = [int.from_bytes(block[i:i + 4], "big") for i in range(0, 64, 4)]
        for j in range(16, 68):
            value = w[j - 16] ^ w[j - 9] ^ _rotl(w[j - 3], 15)
            value = value ^ _rotl(value, 15) ^ _rotl(value, 23)
            w.append(value ^ _rotl(w[j - 13], 7) ^ w[j - 6])
        w1 = [w[j] ^ w[j + 4] for j in range(64)]
        a, b, c, d, e, f, g, h = vector
        for j in range(64):
            tj = 0x79CC4519 if j <= 15 else 0x7A879D8A
            ss1 = _rotl((_rotl(a, 12) + e + _rotl(tj, j)) & 0xFFFFFFFF, 7)
            ss2 = ss1 ^ _rotl(a, 12)
            if j <= 15:
                ff = a ^ b ^ c
                gg = e ^ f ^ g
            else:
                ff = (a & b) | (a & c) | (b & c)
                gg = (e & f) | ((~e) & g)
            tt1 = (ff + d + ss2 + w1[j]) & 0xFFFFFFFF
            tt2 = (gg + h + ss1 + w[j]) & 0xFFFFFFFF
            d = c
            c = _rotl(b, 9)
            b = a
            a = tt1
            h = g
            g = _rotl(f, 19)
            f = e
            e = tt2 ^ _rotl(tt2, 9) ^ _rotl(tt2, 17)
        vector = [x ^ y for x, y in zip(vector, [a, b, c, d, e, f, g, h])]
    return b"".join(item.to_bytes(4, "big") for item in vector)


def _int32(value):
    return int(value).to_bytes(32, "big")


def _point_add(point_a, point_b):
    if point_a is None:
        return point_b
    if point_b is None:
        return point_a
    x1, y1 = point_a
    x2, y2 = point_b
    if x1 == x2 and (y1 + y2) % SM2_P == 0:
        return None
    if point_a == point_b:
        slope = (3 * x1 * x1 + SM2_A) * pow(2 * y1, -1, SM2_P)
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, SM2_P)
    slope %= SM2_P
    x3 = (slope * slope - x1 - x2) % SM2_P
    y3 = (slope * (x1 - x3) - y1) % SM2_P
    return x3, y3


def _point_mul(k, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def _kdf(data, length):
    counter = 1
    output = b""
    while len(output) < length:
        output += _sm3_hash(data + counter.to_bytes(4, "big"))
        counter += 1
    return output[:length]


def sm2_encrypt(message, public_key_hex=DEFAULT_SM2_PUBLIC_KEY, mode=1):
    """生成和前端 sm-crypto 兼容的 SM2 密文；返回值不含最外层 04 前缀。"""
    message_bytes = message.encode("utf-8") if isinstance(message, str) else bytes(message)
    public_key_hex = public_key_hex.strip()
    if public_key_hex.startswith("04"):
        public_key_hex = public_key_hex[2:]
    if len(public_key_hex) != 128:
        raise ValueError("SM2 public key must be 64-byte hex, optionally prefixed with 04")
    public_key = (int(public_key_hex[:64], 16), int(public_key_hex[64:], 16))
    while True:
        k = secrets.randbelow(SM2_N - 1) + 1
        c1 = _point_mul(k, SM2_G)
        x2, y2 = _point_mul(k, public_key)
        x2b = _int32(x2)
        y2b = _int32(y2)
        t = _kdf(x2b + y2b, len(message_bytes))
        if any(t):
            break
    c2 = bytes(a ^ b for a, b in zip(message_bytes, t))
    c3 = _sm3_hash(x2b + message_bytes + y2b)
    c1_hex = _int32(c1[0]).hex() + _int32(c1[1]).hex()
    if mode == 0:
        return c1_hex + c2.hex() + c3.hex()
    return c1_hex + c3.hex() + c2.hex()


def _dynamic_authorization(timestamp_ms):
    """按平台前端规则动态生成 Authorization，不能直接复用抓包里的旧值。"""
    token = _setting("DSVLM_ACCESS_TOKEN")
    public_key = _setting("DSVLM_SM2_PUBLIC_KEY", DEFAULT_SM2_PUBLIC_KEY)
    if not token or not public_key:
        return ""
    return "04" + sm2_encrypt(token + str(timestamp_ms), public_key, 1)


def _headers_for_timestamp(headers, timestamp_ms):
    """同一个毫秒时间戳必须同时用于 URL ?t= 和 Authorization 加密串。"""
    headers = dict(headers)
    if _as_bool(_setting("DSVLM_DYNAMIC_AUTH", "true"), True):
        authorization = _dynamic_authorization(timestamp_ms)
        if authorization:
            headers["Authorization"] = authorization
    return headers


def _platform_response_succeeded(status_code, parsed):
    """Only an explicit platform business success may authorize a write result."""
    return (
        type(status_code) is int
        and 200 <= status_code < 300
        and isinstance(parsed, dict)
        and type(parsed.get("code")) is int
        and parsed.get("code") == 0
    )


def post_payload(api_base, endpoint, payload, headers, timeout, method="POST"):
    """统一 POST 入口；写入和只读列表都走这里，避免鉴权逻辑分叉。"""
    timestamp_ms = int(time.time() * 1000)
    url = "%s%s?t=%d" % (api_base.rstrip("/"), endpoint, timestamp_ms)
    headers = _headers_for_timestamp(headers, timestamp_ms)
    request_secrets = _credential_header_values(headers)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with _open_platform_request(request, timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            return _sanitize_response_result(
                {
                    "url": url,
                    "status_code": response.status,
                    "success": _platform_response_succeeded(response.status, parsed),
                    "response_text": text,
                    "response_json": parsed,
                },
                extra_secrets=request_secrets,
            )
    except PlatformTransportError as error:
        raise PlatformTransportError(
            _mask_string(str(error), request_secrets),
            status_code=error.status_code,
        ) from None
    except Exception as error:
        raise RuntimeError(_mask_string(str(error), request_secrets)) from None


def get_payload(api_base, endpoint, headers, timeout):
    """统一 GET 入口；用于读取单条算法详情。"""
    timestamp_ms = int(time.time() * 1000)
    url = "%s%s?t=%d" % (api_base.rstrip("/"), endpoint, timestamp_ms)
    headers = _headers_for_timestamp(headers, timestamp_ms)
    request_secrets = _credential_header_values(headers)
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with _open_platform_request(request, timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            return _sanitize_response_result(
                {
                    "url": url,
                    "status_code": response.status,
                    "success": _platform_response_succeeded(response.status, parsed),
                    "response_text": text,
                    "response_json": parsed,
                },
                extra_secrets=request_secrets,
            )
    except PlatformTransportError as error:
        raise PlatformTransportError(
            _mask_string(str(error), request_secrets),
            status_code=error.status_code,
        ) from None
    except Exception as error:
        raise RuntimeError(_mask_string(str(error), request_secrets)) from None


def _theme_list(result):
    parsed = result.get("response_json")
    if not isinstance(parsed, dict):
        return []
    data = parsed.get("data")
    if not isinstance(data, dict):
        return []
    items = data.get("list")
    return items if isinstance(items, list) else []


def _theme_total(result):
    parsed = result.get("response_json")
    if not isinstance(parsed, dict):
        return 0
    data = parsed.get("data")
    if not isinstance(data, dict):
        return 0
    return _as_int(data.get("total"), 0)


def _theme_detail(result):
    parsed = result.get("response_json")
    if not isinstance(parsed, dict):
        return {}
    data = parsed.get("data")
    if isinstance(data, dict):
        return data
    return parsed if parsed.get("id") else {}


def fetch_existing_theme_page(
    api_base,
    timeout,
    theme_label="",
    limit=200,
    theme_type_id=None,
):
    endpoint = _setting("DSVLM_DATA_PAGE_ENDPOINT", DEFAULT_DATA_PAGE_ENDPOINT)
    payload = build_data_page_payload(
        theme_label=theme_label,
        limit=limit,
        theme_type_id=theme_type_id,
    )
    result = post_payload(api_base, endpoint, payload, _base_headers(api_base), timeout)
    if not result.get("success"):
        raise RuntimeError("读取现有算法列表失败，已停止提交")
    return result


def fetch_theme_detail(api_base, timeout, theme_id):
    endpoint_template = _setting("DSVLM_DATA_DETAIL_ENDPOINT", DEFAULT_DATA_DETAIL_ENDPOINT)
    endpoint = endpoint_template.format(id=urllib.parse.quote(str(theme_id), safe=""))
    result = get_payload(api_base, endpoint, _base_headers(api_base), timeout)
    if not result.get("success"):
        raise RuntimeError("读取算法详情失败，已停止更新")
    return result


def ensure_authorization(api_base, timeout, theme_type_id=None):
    """复用可用 token；只在缺失或探活失败时刷新一次。"""
    if not _as_bool(_setting("DSVLM_DYNAMIC_AUTH", "true"), True):
        return {"success": True, "status": "DYNAMIC_AUTH_DISABLED"}
    current_theme_type_id = _normalized_theme_type_id(theme_type_id)
    if _setting("DSVLM_ACCESS_TOKEN") and not current_theme_type_id:
        return {"success": True, "status": "AUTH_REUSED_UNPROBED"}
    if _setting("DSVLM_ACCESS_TOKEN"):
        try:
            probe = fetch_theme_data_page(
                api_base=api_base,
                timeout=timeout,
                limit=1,
                ensure_auth=False,
                theme_type_id=current_theme_type_id,
            )
        except PlatformTransportError as error:
            if error.status_code not in (401, 403):
                return {
                    "success": False,
                    "status": "AUTH_PROBE_HTTP_ERROR",
                    "status_code": error.status_code,
                }
        except Exception as error:
            return {"success": False, "status": "AUTH_PROBE_EXCEPTION", "error": "探活失败：%s" % error}
        else:
            if probe.get("success"):
                return {"success": True, "status": "AUTH_REUSED"}
    try:
        result = refresh_authorization(timeout=timeout)
    except PlatformTransportError as error:
        status_code = error.status_code
        return {
            "success": False,
            "status": "AUTH_REFRESH_HTTP_ERROR",
            "status_code": status_code,
            "error": "HTTP %s" % status_code if status_code else "platform request failed",
        }
    if result.get("success"):
        result["status"] = "AUTH_REFRESHED"
    elif not result.get("status"):
        result["status"] = "AUTH_REFRESH_FAILED"
    return result


def _theme_summary(item):
    return {
        "id": item.get("id", ""),
        "themeLabel": item.get("themeLabel", ""),
        "sort": item.get("sort"),
        "level": item.get("level"),
        "mode": item.get("mode"),
        "updateTime": item.get("updateTime", ""),
    }


def _already_exists_result(payload, existing):
    label = payload.get("themeLabel", "")
    return {
        "success": True,
        "status": "ALREADY_EXISTS_DO_NOT_RETRY",
        "posted": False,
        "already_exists": True,
        "message": "同名算法已存在，脚本已跳过写入；需要修改时请使用优化请求。",
        "themeLabel": label,
        "existing": _theme_summary(existing),
    }


def _update_target_not_found_result(payload):
    label = payload.get("themeLabel", "")
    return {
        "success": False,
        "status": "UPDATE_TARGET_NOT_FOUND_NOT_POSTED",
        "posted": False,
        "message": "未找到同名算法，已停止；update 模式不会新建算法。",
        "themeLabel": label,
    }


def _apply_existing_for_update(payload, existing, provided_fields, auto_sort=False):
    existing_id = existing.get("id")
    if not existing_id:
        raise ValueError("现有算法缺少 id，无法执行修改保存")
    merged = build_payload()
    for key in merged:
        if key in existing:
            merged[key] = existing[key]
        elif key in payload:
            merged[key] = payload[key]
    for key in provided_fields:
        if key in payload and key not in {"id", "themeTypeId"}:
            merged[key] = payload[key]
    merged["id"] = existing_id
    if existing.get("themeTypeId"):
        merged["themeTypeId"] = existing["themeTypeId"]
    if auto_sort and existing.get("sort") not in (None, ""):
        merged["sort"] = _as_int(existing.get("sort"), merged.get("sort", 1))
    return merged


def _base_headers(api_base):
    """基础请求头；动态 Authorization 会在 post_payload 里覆盖旧抓包值。"""
    headers = {
        "Accept": _setting("DSVLM_ACCEPT", "application/json, text/plain, */*"),
        "Accept-Language": _setting("DSVLM_ACCEPT_LANGUAGE", "zh-CN"),
        "Content-Type": _setting("DSVLM_CONTENT_TYPE", "application/json;charset=UTF-8"),
        "Origin": _setting("DSVLM_ORIGIN", api_base.rstrip("/")),
        "Referer": _setting("DSVLM_REFERER", api_base.rstrip("/") + "/"),
        "User-Agent": _setting("DSVLM_USER_AGENT", "Mozilla/5.0"),
    }
    authorization = _setting("DSVLM_AUTHORIZATION")
    if authorization:
        headers["Authorization"] = authorization
    proxy_connection = _setting("DSVLM_PROXY_CONNECTION")
    if proxy_connection:
        headers["Proxy-Connection"] = proxy_connection
    return headers


def _mask_text(text):
    """输出日志时遮住本地敏感值，避免把 token/cookie 打到终端里。"""
    for secret in (
        _setting("DSVLM_AUTHORIZATION"),
        _setting("DSVLM_ACCESS_TOKEN"),
        _setting("DSVLM_LOGIN_PASSWORD"),
        _setting("DSVLM_COOKIE"),
    ):
        if secret:
            for representation in _secret_representations((secret,)):
                text = text.replace(representation, "<set>")
    return text


def _is_sensitive_value_key(key):
    normalized = str(key).strip().lower().replace("-", "_")
    compact = normalized.replace("_", "")
    return compact in {
        "accesstoken",
        "refreshtoken",
        "token",
        "authorization",
        "cookie",
        "password",
        "csrftoken",
        "xcsrftoken",
    }


def _normalized_secret_values(values):
    secrets = {
        str(value)
        for value in values
        if value is not None and str(value)
    }
    return sorted(secrets, key=len, reverse=True)


def _secret_representations(values, max_json_depth=2):
    """Return literal and JSON-escaped spellings, including nested JSON strings."""
    representations = set(_normalized_secret_values(values))
    frontier = set(representations)
    for _ in range(max_json_depth):
        encoded = {
            json.dumps(value, ensure_ascii=ensure_ascii)[1:-1]
            for value in frontier
            for ensure_ascii in (False, True)
        }
        representations.update(encoded)
        frontier = encoded
    return sorted(representations, key=len, reverse=True)


def _mask_string(value, extra_secrets=()):
    masked = _mask_text(str(value))
    for representation in _secret_representations(extra_secrets):
        masked = masked.replace(representation, "<set>")
    return masked


def _credential_header_values(headers):
    return [
        value
        for key, value in (headers or {}).items()
        if value and _is_sensitive_value_key(key)
    ]


def _mask_obj(value, extra_secrets=()):
    if isinstance(value, dict):
        masked = {}
        for key, child in value.items():
            if _is_sensitive_value_key(key):
                masked[key] = "<set>" if child else child
            else:
                masked[key] = _mask_obj(child, extra_secrets)
        return masked
    if isinstance(value, list):
        return [_mask_obj(item, extra_secrets) for item in value]
    if isinstance(value, str):
        return _mask_string(value, extra_secrets)
    return value


def _secret_values(value):
    secrets = []
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_sensitive_value_key(key) and child:
                secrets.append(str(child))
            secrets.extend(_secret_values(child))
    elif isinstance(value, list):
        for item in value:
            secrets.extend(_secret_values(item))
    return secrets


def _sanitize_response_result(result, extra_secrets=()):
    """Mask public response fields before main returns them to a caller."""
    sanitized = dict(result)
    response_json = sanitized.get("response_json")
    response_secrets = _normalized_secret_values(
        [*_secret_values(response_json), *extra_secrets]
    )
    if "response_text" in sanitized:
        sanitized["response_text"] = _mask_string(
            sanitized.get("response_text") or "",
            response_secrets,
        )
    if "response_json" in sanitized:
        sanitized["response_json"] = _mask_obj(response_json, response_secrets)
    return sanitized


def _write_env_temp_file(path, content):
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _write_env_value(key, value, path=DEFAULT_ENV_PATH):
    """原子写回 .env；只有替换成功后才更新当前进程状态。"""
    global ENV
    if not isinstance(key, str) or not ENV_KEY_PATTERN.fullmatch(key):
        raise ValueError("invalid environment key")
    if not isinstance(value, str) or any(
        char in value for char in ("\r", "\n", "\x00")
    ):
        raise ValueError("invalid environment value")

    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for index, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[index] = "%s=%s" % (key, value)
            break
    else:
        lines.append("%s=%s" % (key, value))
    content = "\n".join(lines) + "\n"

    file_descriptor = None
    temp_path = None
    try:
        file_descriptor, temp_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=".%s." % path.name,
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        os.close(file_descriptor)
        file_descriptor = None
        _write_env_temp_file(temp_path, content)
        os.replace(temp_path, path)
        temp_path = None
    except Exception:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        raise

    ENV[key] = value
    os.environ[key] = value


def _normalized_token_candidate(value):
    if not isinstance(value, str) or any(
        not char.isprintable() for char in value
    ):
        return ""
    candidate = value.strip()
    if not MIN_REFRESH_TOKEN_LENGTH <= len(candidate) <= MAX_REFRESH_TOKEN_LENGTH:
        return ""
    if any(char.isspace() for char in candidate):
        return ""
    return candidate


def _trusted_token_containers(value):
    if not isinstance(value, dict):
        return []
    containers = [value]
    current = value
    for _ in range(2):
        current = current.get("data")
        if not isinstance(current, dict):
            break
        containers.append(current)
    return containers


def _find_token(value):
    """只信任根对象和 data.data 链；候选冲突时拒绝刷新。"""
    containers = _trusted_token_containers(value)
    distinct = []
    for key in REFRESH_TOKEN_KEYS:
        for container in containers:
            token = _normalized_token_candidate(container.get(key))
            if token and token not in distinct:
                distinct.append(token)
    return distinct[0] if len(distinct) == 1 else ""


def _captcha_required(api_base, headers, timeout):
    try:
        result = get_payload(
            api_base,
            DEFAULT_CAPTCHA_ENABLED_ENDPOINT,
            headers,
            timeout,
        )
    except Exception:
        return False
    parsed = result.get("response_json")
    if not isinstance(parsed, dict):
        return False
    enabled = parsed.get("data")
    if isinstance(enabled, dict):
        enabled = enabled.get("enabled")
    return enabled is True


def refresh_authorization(write_env=True, timeout=30):
    """登录 61.172 并刷新 DSVLM_ACCESS_TOKEN；不创建、不修改算法配置。"""
    api_base = _setting("DSVLM_API_BASE", DEFAULT_API_BASE).rstrip("/")
    endpoint = _setting("DSVLM_LOGIN_ENDPOINT", "/s/sys/auth/login")
    username = _setting("DSVLM_LOGIN_USERNAME")
    raw_password = _setting("DSVLM_LOGIN_PASSWORD")
    if not username or not raw_password:
        return {
            "success": False,
            "status": "AUTH_CONFIG_REQUIRED",
            "message": "请先在私有 .env 中配置 DSVLM 登录账号和密码。",
        }
    payload = {
        "username": username,
        "password": "04" + sm2_encrypt(raw_password),
        "key": "",
        "captcha": "",
    }
    headers = {
        "Accept": _setting("DSVLM_ACCEPT", "application/json, text/plain, */*"),
        "Accept-Language": _setting("DSVLM_ACCEPT_LANGUAGE", "zh-CN"),
        "Content-Type": _setting("DSVLM_CONTENT_TYPE", "application/json;charset=UTF-8"),
        "Origin": _setting("DSVLM_ORIGIN", api_base),
        "Referer": _setting("DSVLM_REFERER", api_base + "/"),
        "User-Agent": _setting("DSVLM_USER_AGENT", "Mozilla/5.0"),
    }
    proxy_connection = _setting("DSVLM_PROXY_CONNECTION")
    if proxy_connection:
        headers["Proxy-Connection"] = proxy_connection
    request_secrets = [
        *_credential_header_values(headers),
        raw_password,
        *(value for value in payload.values() if value),
    ]

    url = "%s%s?t=%d" % (api_base, endpoint, int(time.time() * 1000))
    response_secrets = []
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with _open_platform_request(request, timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            response_secrets = _secret_values(parsed)
            business_success = _platform_response_succeeded(response.status, parsed)
            token = _find_token(parsed) if business_success else ""
            if token and write_env:
                _write_env_value("DSVLM_ACCESS_TOKEN", token)
            captcha_required = bool(
                not business_success
                and _captcha_required(api_base, headers, timeout)
            )
            return _sanitize_response_result(
                {
                    "success": bool(business_success and token),
                    "status": "CAPTCHA_REQUIRED" if captcha_required else "",
                    "status_code": response.status,
                    "url": url,
                    "headers": {
                        key: ("<set>" if _is_sensitive_value_key(key) else value)
                        for key, value in headers.items()
                    },
                    "wrote_access_token": bool(token and write_env),
                    "response_text": text,
                    "response_json": parsed,
                },
                extra_secrets=request_secrets,
            )
    except PlatformTransportError as error:
        raise PlatformTransportError(
            _mask_string(str(error), [*request_secrets, *response_secrets]),
            status_code=error.status_code,
        ) from None
    except Exception as error:
        raise RuntimeError(
            _mask_string(str(error), [*request_secrets, *response_secrets])
        ) from None


def fetch_theme_data_page(**kwargs):
    """只读当前主题下的算法列表，用于验证主题 id 和鉴权是否正确。"""
    theme_type_id = _resolve_theme_type_aliases(kwargs, required=True)
    kwargs = dict(kwargs, theme_type_id=theme_type_id)
    api_base = kwargs.get("api_base") or _setting("DSVLM_API_BASE", DEFAULT_API_BASE)
    endpoint = kwargs.get("endpoint") or _setting("DSVLM_DATA_PAGE_ENDPOINT", DEFAULT_DATA_PAGE_ENDPOINT)
    timeout = _as_int(kwargs.get("timeout") or _setting("DSVLM_TIMEOUT"), 30)
    if _as_bool(kwargs.get("ensure_auth"), True):
        auth_result = ensure_authorization(
            api_base,
            timeout,
            theme_type_id=theme_type_id,
        )
        if not auth_result.get("success"):
            return auth_result
    payload = build_data_page_payload(**kwargs)
    result = post_payload(api_base, endpoint, payload, _base_headers(api_base), timeout)
    result["response_text"] = _mask_text(result["response_text"])
    result["response_json"] = _mask_obj(result["response_json"])
    return result


def fetch_theme_data_detail(**kwargs):
    """只读单条算法详情，用于 update 前拿完整原配置。"""
    api_base = kwargs.get("api_base") or _setting("DSVLM_API_BASE", DEFAULT_API_BASE)
    timeout = _as_int(kwargs.get("timeout") or _setting("DSVLM_TIMEOUT"), 30)
    if _as_bool(kwargs.get("ensure_auth"), True):
        detail_theme_type_id = _resolve_theme_type_aliases(kwargs)
        auth_result = ensure_authorization(
            api_base,
            timeout,
            theme_type_id=detail_theme_type_id or None,
        )
        if not auth_result.get("success"):
            return auth_result
    result = fetch_theme_detail(api_base, timeout, kwargs["theme_id"])
    result["response_text"] = _mask_text(result["response_text"])
    result["response_json"] = _mask_obj(result["response_json"])
    return result


def main(**kwargs):
    """默认 dry-run；只有 dry_run=False 时才提交 /s/theme/data。"""
    api_base = kwargs.get("api_base") or _setting("DSVLM_API_BASE", DEFAULT_API_BASE)
    endpoint = kwargs.get("endpoint") or _setting("DSVLM_ENDPOINT", DEFAULT_ENDPOINT)
    authorization = (
        _normalized_authorization(kwargs.get("authorization"))
        or _normalized_authorization(_setting("DSVLM_AUTHORIZATION"))
    )
    dry_run = _as_bool(kwargs.get("dry_run"), True)
    provided_payload = kwargs.get("payload")
    payload_theme_type_id = _normalized_theme_type_id(
        provided_payload.get("themeTypeId")
        if isinstance(provided_payload, dict)
        else None
    )
    try:
        top_level_theme_type_id = _resolve_theme_type_aliases(kwargs)
    except ValueError:
        return {
            "api_result": [{
                "success": False,
                "status": "THEME_MISMATCH_NOT_POSTED",
                "posted": False,
                "message": "theme_type_id 与 themeTypeId 不一致，已停止上传。",
            }]
        }
    explicit_theme_type_id = (
        top_level_theme_type_id
        or payload_theme_type_id
    )
    theme_name = str(kwargs.get("theme_name") or "").strip()
    theme_catalog_verified = False
    if theme_name:
        theme_result = resolve_theme_name(theme_name)
        if not theme_result.get("success"):
            return {"api_result": [dict(theme_result, posted=False)]}
        resolved_theme_type_id = theme_result["theme_type_id"]
        if explicit_theme_type_id and explicit_theme_type_id != resolved_theme_type_id:
            return {
                "api_result": [{
                    "success": False,
                    "status": "THEME_MISMATCH_NOT_POSTED",
                    "posted": False,
                    "message": "主题名匹配结果与显式 themeTypeId 不一致，已停止上传。",
                }]
            }
        explicit_theme_type_id = resolved_theme_type_id
        theme_catalog_verified = True
    update_existing = _as_bool(
        kwargs.get("update_existing", kwargs.get("_update_existing")),
        False,
    )
    if update_existing and not explicit_theme_type_id:
        return {
            "api_result": [{
                "success": False,
                "status": "THEME_REQUIRED_NOT_POSTED",
                "posted": False,
                "message": "优化已有算法必须填写主题名。",
            }]
        }
    if (
        not dry_run
        and top_level_theme_type_id
        and payload_theme_type_id
        and top_level_theme_type_id != payload_theme_type_id
    ):
        return {
            "api_result": [{
                "success": False,
                "status": "THEME_MISMATCH_NOT_POSTED",
                "posted": False,
                "message": "顶层 themeTypeId 与 payload.themeTypeId 不一致，已停止上传。",
            }]
        }
    if not dry_run and not explicit_theme_type_id:
        return {
            "api_result": [{
                "success": False,
                "status": "THEME_REQUIRED_NOT_POSTED",
                "posted": False,
                "message": "真实上传必须显式指定 themeTypeId，禁止默认主题。",
            }]
        }
    timeout = _as_int(kwargs.get("timeout") or _setting("DSVLM_TIMEOUT"), 30)
    if provided_payload is None and "sort" not in kwargs and "_auto_sort" not in kwargs:
        kwargs["_auto_sort"] = True
    if provided_payload is not None:
        payload = dict(provided_payload)
    else:
        payload = build_payload(**kwargs)
    if explicit_theme_type_id:
        payload["themeTypeId"] = explicit_theme_type_id
    headers = {
        "Accept": kwargs.get("accept") or _setting("DSVLM_ACCEPT", "application/json, text/plain, */*"),
        "Accept-Language": kwargs.get("accept_language") or _setting("DSVLM_ACCEPT_LANGUAGE", "zh-CN"),
        "Content-Type": kwargs.get("content_type") or _setting("DSVLM_CONTENT_TYPE", "application/json;charset=UTF-8"),
        "Origin": kwargs.get("origin") or _setting("DSVLM_ORIGIN", api_base.rstrip("/")),
        "Referer": kwargs.get("referer") or _setting("DSVLM_REFERER", api_base.rstrip("/") + "/"),
        "User-Agent": kwargs.get("user_agent") or _setting("DSVLM_USER_AGENT", "Mozilla/5.0"),
    }
    if authorization:
        headers["Authorization"] = authorization
    cookie = kwargs.get("cookie") or _setting("DSVLM_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    csrf_token = kwargs.get("csrf_token") or _setting("DSVLM_CSRF_TOKEN")
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
    proxy_connection = kwargs.get("proxy_connection") or _setting("DSVLM_PROXY_CONNECTION")
    if proxy_connection:
        headers["Proxy-Connection"] = proxy_connection
    request_secrets = _credential_header_values(headers)

    url = "%s%s?t=<timestamp>" % (api_base.rstrip("/"), endpoint)
    if dry_run:
        return {
            "api_result": [{
                "success": True,
                "status": "DRY_RUN_ONLY_NOT_POSTED",
                "posted": False,
                "dry_run": True,
                "message": "dry-run 只生成 payload，没有写入平台；确认无误后再 post。",
                "url": url,
                "headers": {key: ("<set>" if key in SENSITIVE_HEADER_NAMES else value) for key, value in headers.items()},
                "payload": payload,
            }]
        }

    skip_existing = _as_bool(kwargs.get("skip_existing", _setting("DSVLM_SKIP_EXISTING", "true")), True)
    force_post = _as_bool(kwargs.get("force_post"), False)
    has_dynamic_auth = (
        _as_bool(_setting("DSVLM_DYNAMIC_AUTH", "true"), True)
        and bool(_setting("DSVLM_ACCESS_TOKEN"))
    )
    if (
        _as_bool(_setting("DSVLM_DYNAMIC_AUTH", "true"), True)
        and not theme_catalog_verified
    ):
        auth_result = ensure_authorization(
            api_base,
            timeout,
            theme_type_id=payload.get("themeTypeId"),
        )
        has_dynamic_auth = bool(_setting("DSVLM_ACCESS_TOKEN"))
        if not auth_result.get("success") and (has_dynamic_auth or not authorization):
            return {
                "api_result": [{
                    "success": False,
                    "status": auth_result.get("status", "AUTH_REFRESH_FAILED"),
                    "posted": False,
                    "error": auth_result.get("error", "鉴权探活或刷新失败"),
                    "auth_result": auth_result,
                    "url": url,
                    "payload": payload,
                }]
            }
    if not authorization and not has_dynamic_auth:
        return {
            "api_result": [{
                "success": False,
                "status": "AUTH_MISSING_NOT_POSTED",
                "posted": False,
                "error": "missing auth; set DSVLM_ACCESS_TOKEN with DSVLM_DYNAMIC_AUTH=true, or set DSVLM_AUTHORIZATION",
                "url": url,
                "payload": payload,
            }]
        }

    try:
        auto_sort = _as_bool(kwargs.get("_auto_sort"), False)
        need_page = bool(
            update_existing
            or (skip_existing and not force_post and payload.get("themeLabel"))
            or (auto_sort and not update_existing)
        )
        page = (
            fetch_existing_theme_page(
                api_base,
                timeout,
                limit=200,
                theme_type_id=payload["themeTypeId"],
            )
            if need_page
            else None
        )
        items = _theme_list(page) if page else []
        existing = next(
            (
                item
                for item in items
                if item.get("themeLabel") == payload.get("themeLabel")
            ),
            None,
        )
        if update_existing and payload.get("themeLabel"):
            if not existing:
                return {"api_result": [_update_target_not_found_result(payload)]}
            detail = _theme_detail(fetch_theme_detail(api_base, timeout, existing["id"]))
            detail = dict(existing, **detail)
            payload = _apply_existing_for_update(
                payload,
                detail,
                kwargs.get("_provided_fields", set(payload)),
                auto_sort,
            )
        elif skip_existing and not force_post and payload.get("themeLabel"):
            if existing:
                return {"api_result": [_already_exists_result(payload, existing)]}
        if auto_sort and not update_existing:
            # ponytail: one list read; page through only if the platform proves 200 is too small.
            sorts = [_as_int(item.get("sort"), 0) for item in items]
            payload["sort"] = max([_theme_total(page)] + sorts) + 1
        result = _sanitize_response_result(
            post_payload(
                api_base,
                endpoint,
                payload,
                headers,
                timeout,
                method="PUT" if update_existing else "POST",
            ),
            extra_secrets=request_secrets,
        )
        if result.get("success"):
            result["status"] = "UPDATE_SUCCEEDED_DO_NOT_RETRY" if update_existing else "POST_SUCCEEDED_DO_NOT_RETRY"
            result["posted"] = True
            result["message"] = "平台已返回 success；不要再次 post。"
        else:
            result["status"] = "POST_FAILED"
            result["posted"] = False
        return {"api_result": [result]}
    except PlatformTransportError as error:
        return {
            "api_result": [{
                "success": False,
                "status": "POST_HTTP_ERROR",
                "posted": False,
                "status_code": error.status_code,
                "error": _mask_string(str(error), request_secrets),
            }]
        }
    except Exception as error:
        return {
            "api_result": [{
                "success": False,
                "status": "POST_EXCEPTION",
                "posted": False,
                "error": _mask_string("执行失败：%s" % error, request_secrets),
            }]
        }


def cli():
    parser = argparse.ArgumentParser(description="构造或提交华鲲元启视频算法配置 payload。")
    parser.add_argument("--refresh-auth", action="store_true", help="登录 61.172 并刷新 DSVLM_ACCESS_TOKEN。")
    parser.add_argument("--theme-data-page", action="store_true", help="只读取当前主题算法列表。")
    parser.add_argument("--theme-data-detail", default="", help="只读取单条算法详情，传算法 id。")
    parser.add_argument("--theme-label", default="", help="按算法名称过滤列表。")
    parser.add_argument("--theme-name", default="", help="用户选择的主题名；运行时精确匹配主题 ID。")
    parser.add_argument("--payload", choices=["-"], help="从 stdin 读取结构化 JSON，只接受 -。")
    parser.add_argument("--user-request", default="", help="原始用户请求，用于提取新建、优化、主题和 --post。")
    args = parser.parse_args()

    if args.refresh_auth:
        print(json.dumps(refresh_authorization(), ensure_ascii=False, indent=2))
        return
    if args.theme_data_page:
        theme_type_id = None
        if args.theme_name:
            theme_result = resolve_theme_name(args.theme_name)
            if not theme_result.get("success"):
                print(json.dumps(theme_result, ensure_ascii=False, indent=2))
                return
            theme_type_id = theme_result["theme_type_id"]
        print(json.dumps(fetch_theme_data_page(
            theme_label=args.theme_label,
            theme_type_id=theme_type_id,
        ), ensure_ascii=False, indent=2))
        return
    if args.theme_data_detail:
        print(json.dumps(fetch_theme_data_detail(theme_id=args.theme_data_detail), ensure_ascii=False, indent=2))
        return
    if not args.payload:
        parser.error("--payload - is required")
    try:
        config = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        parser.error("invalid payload JSON: %s" % error)
    kwargs = parse_structured_payload(config, args.user_request)
    request_args = parse_user_request(args.user_request)
    if args.theme_name:
        kwargs["theme_name"] = args.theme_name
    kwargs["dry_run"] = not request_args["post"]
    print(json.dumps(main(**kwargs), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
