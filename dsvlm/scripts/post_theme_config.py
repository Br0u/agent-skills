#!/usr/bin/env python3
"""华鲲元启视频算法配置接口 demo。

默认只生成 payload，不写入平台。
用 --agent-output 时，只有原始用户请求末尾有 --post 才会提交；模型自己乱加 --post 会被忽略。
用 --config 时，只有 CLI 显式传 --post 或 main(dry_run=False) 时，才会提交到接口。
"""

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import urllib.error
import urllib.request


DEFAULT_API_BASE = "http://61.172.168.94:8898"
DEFAULT_ENDPOINT = "/s/theme/data"
DEFAULT_DATA_PAGE_ENDPOINT = "/s/theme/data/page"
DEFAULT_THEME_TYPE_ID = "8faeefc246be36d2db59558bed823122"
DEFAULT_SM2_PUBLIC_KEY = (
    "040a302b5e4b961afb3908a4ae191266ac5866be100fc52e3b8dba9707c8620e64ae790ceffc"
    "3bfbf262dc098d293dd3e303356cb91b54861c767997799d2f0060"
)
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = SKILL_DIR / ".env"
SENSITIVE_HEADER_NAMES = {"Authorization", "Cookie", "X-CSRF-Token", "access-token"}
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
        value = value.strip().strip('"').strip("'")
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


def _is_auto_sort(value):
    return str(value or "").strip().lower() in {"", "auto", "自动"}


def _user_requested_sort(user_request):
    return bool(re.search(r"(排序|sort|order)\s*[:：=]", user_request or "", re.IGNORECASE))


def _normalize_rule_list(value):
    if not value:
        return [{"parsingId": "1", "rule": ""}]
    if isinstance(value, str):
        value = json.loads(value)

    rules = []
    for item in value:
        parsing_id = item.get("parsingId", item.get("parsing_id", "1"))
        rules.append({
            "parsingId": str(parsing_id),
            "rule": item.get("rule", ""),
        })
    return rules or [{"parsingId": "1", "rule": ""}]


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
        "themeTypeId": kwargs.get("theme_type_id", kwargs.get("themeTypeId", DEFAULT_THEME_TYPE_ID)),
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
    return {
        "themeLabel": kwargs.get("theme_label", ""),
        "themeTypeId": kwargs.get("theme_type_id") or _setting("DSVLM_THEME_TYPE_ID", DEFAULT_THEME_TYPE_ID),
        "page": _as_int(kwargs.get("page"), 1),
        "limit": _as_int(kwargs.get("limit"), 20),
        "order": kwargs.get("order", "sort"),
        "asc": _as_bool(kwargs.get("asc"), True),
        "pageSizes": kwargs.get("page_sizes", [20, 50, 100, 200]),
    }


def _first_match(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return match.group(1).strip().strip("`* ")
    return ""


def _field_value(label, text):
    value = _first_match(
        [r"^\s*%s\s*[:：]\s*(.+?)\s*$" % re.escape(label)],
        text,
    )
    if value:
        return value
    for key, cell_value in _simple_table_rows(text):
        if key == label:
            return cell_value
    return ""


def _simple_table_rows(text):
    rows = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2 or all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        if cells[0] in {"字段", "项目"}:
            continue
        rows.append((cells[0], cells[1]))
    return rows


def _as_percent_int(value, default=0):
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else default


def _parse_choice(value, choices, default):
    value = str(value or "").strip()
    if value.isdigit():
        return int(value)
    return choices.get(value, default)


def _parse_area_flag(value):
    value = str(value or "").strip()
    if value in {"关", "关闭", "false", "False", "0", "否"}:
        return False
    return True


def _confidence_value(parts):
    for part in parts:
        match = re.search(r"(?:阈值\s*)?(\d+(?:\.\d+)?)", part)
        if match:
            value = float(match.group(1))
            return str(value / 100 if value > 1 else value).rstrip("0").rstrip(".")
    return "0.5"


def _target_rule(component, parts):
    if len(parts) < 3:
        raise ValueError("invalid target rule: %s / %s" % (component, " / ".join(parts)))
    target = TARGET_NAME_MAP.get(parts[0], parts[0])
    operator = TARGET_OPERATOR_MAP.get(parts[1])
    if not operator:
        raise ValueError("unknown target operator: %s" % parts[1])
    if len(parts) == 3:
        count = 0
        confidence = _confidence_value([parts[2]])
    else:
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
        rule = ""
    else:
        rule = " / ".join(parts[2:]).strip()
        if not rule:
            raise ValueError("missing rule text: %s" % raw_rule)
    return {"parsingId": parsing_id, "rule": rule}


def _condition_rules(text):
    rules = []
    for match in re.finditer(r"^\s*思维条件\s*(\d*)\s*[:：]\s*(.+?)\s*$", text, re.MULTILINE):
        raw_rule = match.group(2).strip().strip("`")
        if raw_rule:
            rules.append(_platform_rule(raw_rule))
    for label, value in _simple_table_rows(text):
        if re.fullmatch(r"思维条件\s*\d*", label):
            raw_rule = value.strip().strip("`")
            if raw_rule:
                rules.append(_platform_rule(raw_rule))
    return rules


def parse_user_request(user_request):
    """解析默认调用格式：场景：xx --算法名 --post。"""
    match = re.search(
        r"场景\s*[:：]\s*(.+?)(?:\s+--\s*(.+?))?(?:\s+--\s*(post))?\s*$",
        user_request or "",
    )
    if not match:
        return {"scene": "", "algorithm_name": "", "post": False}
    return {
        "scene": (match.group(1) or "").strip(),
        "algorithm_name": (match.group(2) or "").strip(),
        "post": (match.group(3) or "").lower() == "post",
    }


def parse_agent_output(text, user_request="", algorithm_name=""):
    """从用户请求和 dsvlm 输出里提取可提交配置。"""
    request_args = parse_user_request(user_request)
    source = "\n".join(part for part in [user_request, text] if part)
    name = (
        algorithm_name
        or _first_match([r"--\s*算法名称\s*[:：]\s*([^\n\r]+)"], source)
        or request_args["algorithm_name"]
        or _field_value("算法名称", source)
        or _field_value("算法", source)
    )
    rules = _condition_rules(text)
    if not name:
        raise ValueError("missing algorithm name; use 场景：xx --算法名, or add 算法：xxx in output")
    if not rules:
        raise ValueError("missing 思维条件 lines in agent output")

    mode = _parse_choice(_field_value("解析模式", text), MODE_MAP, 1)
    level = _parse_choice(_field_value("预警等级", text), LEVEL_MAP, 1)
    area_flag = _parse_area_flag(_field_value("启用区域框", text))
    sort_field = _field_value("排序", text)
    auto_sort = _is_auto_sort(sort_field) or not _user_requested_sort(user_request)
    sort = 1 if auto_sort else _as_int(sort_field, 1)
    extension_ratio = _as_percent_int(_field_value("延伸比例", text), 0)

    return {
        "theme_label": name,
        "name": name,
        "mode": mode,
        "level": level,
        "area_flag": area_flag,
        "sort": sort,
        "_auto_sort": auto_sort,
        "extension_ratio": extension_ratio,
        "rules": rules,
        "remark": _field_value("备注", text),
    }


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


def post_payload(api_base, endpoint, payload, headers, timeout):
    """统一 POST 入口；写入和只读列表都走这里，避免鉴权逻辑分叉。"""
    timestamp_ms = int(time.time() * 1000)
    url = "%s%s?t=%d" % (api_base.rstrip("/"), endpoint, timestamp_ms)
    headers = _headers_for_timestamp(headers, timestamp_ms)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        return {
            "url": url,
            "status_code": response.status,
            "success": response.status == 200 and (not isinstance(parsed, dict) or parsed.get("code") == 0),
            "response_text": text,
            "response_json": parsed,
        }


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


def find_existing_theme(api_base, theme_label, timeout):
    """只读查同名算法；用于避免低性能模型重复提交。"""
    for item in fetch_existing_themes(api_base, timeout, theme_label=theme_label, limit=100):
        if item.get("themeLabel") == theme_label:
            return item
    return None


def fetch_existing_themes(api_base, timeout, theme_label="", limit=200):
    return _theme_list(fetch_existing_theme_page(api_base, timeout, theme_label, limit))


def fetch_existing_theme_page(api_base, timeout, theme_label="", limit=200):
    endpoint = _setting("DSVLM_DATA_PAGE_ENDPOINT", DEFAULT_DATA_PAGE_ENDPOINT)
    payload = build_data_page_payload(theme_label=theme_label, limit=limit)
    result = post_payload(api_base, endpoint, payload, _base_headers(api_base), timeout)
    if not result.get("success"):
        raise RuntimeError("读取现有算法列表失败，已停止提交")
    return result


def next_sort_after_existing(api_base, timeout):
    page = fetch_existing_theme_page(api_base, timeout)
    sorts = [
        _as_int(item.get("sort"), 0)
        for item in _theme_list(page)
    ]
    return max([_theme_total(page)] + sorts) + 1


def ensure_authorization(api_base, timeout):
    """复用可用 token；只在缺失或探活失败时刷新一次。"""
    if not _as_bool(_setting("DSVLM_DYNAMIC_AUTH", "true"), True):
        return {"success": True, "status": "DYNAMIC_AUTH_DISABLED"}
    if _setting("DSVLM_ACCESS_TOKEN"):
        try:
            probe = fetch_theme_data_page(api_base=api_base, timeout=timeout, limit=1, ensure_auth=False)
        except urllib.error.HTTPError as error:
            if error.code not in (401, 403):
                return {"success": False, "status": "AUTH_PROBE_HTTP_ERROR", "status_code": error.code}
        except Exception as error:
            return {"success": False, "status": "AUTH_PROBE_EXCEPTION", "error": "探活失败：%s" % error}
        else:
            if probe.get("success"):
                return {"success": True, "status": "AUTH_REUSED"}
    result = refresh_authorization(timeout=timeout)
    result["status"] = "AUTH_REFRESHED" if result.get("success") else "AUTH_REFRESH_FAILED"
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
        "message": "同名算法已存在，脚本已跳过写入；不要再次 post。需要强制写入时才使用 --force-post。",
        "themeLabel": label,
        "existing": _theme_summary(existing),
    }


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
        _setting("DSVLM_PORTAL_ACCESS_TOKEN"),
        _setting("DSVLM_PORTAL_COOKIE"),
        _setting("DSVLM_LOGIN_AUTHORIZATION"),
        _setting("DSVLM_LOGIN_PASSWORD"),
        _setting("DSVLM_COOKIE"),
    ):
        if secret:
            text = text.replace(secret, "<set>")
    return text


def _mask_obj(value):
    if isinstance(value, dict):
        masked = {}
        for key, child in value.items():
            if key in {"access_token", "refresh_token", "token", "authorization", "accessToken", "refreshToken"}:
                masked[key] = "<set>" if child else child
            else:
                masked[key] = _mask_obj(child)
        return masked
    if isinstance(value, list):
        return [_mask_obj(item) for item in value]
    if isinstance(value, str):
        return _mask_text(value)
    return value


def _secret_values(value):
    secrets = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"access_token", "refresh_token", "token", "authorization", "accessToken", "refreshToken"} and child:
                secrets.append(str(child))
            secrets.extend(_secret_values(child))
    elif isinstance(value, list):
        for item in value:
            secrets.extend(_secret_values(item))
    return secrets


def fetch_auto_login_url(timeout=30):
    """读取主平台返回的 61.172 自动登录地址；不修改算法配置。"""
    url = _setting("DSVLM_PORTAL_AUTO_LOGIN_URL")
    if not url:
        return {"success": False, "error": "missing DSVLM_PORTAL_AUTO_LOGIN_URL"}
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": _setting("DSVLM_PORTAL_ACCEPT_LANGUAGE", "zh-CN,zh;q=0.9"),
        "Referer": _setting("DSVLM_PORTAL_REFERER"),
        "User-Agent": _setting("DSVLM_USER_AGENT", "Mozilla/5.0"),
    }
    access_token = _setting("DSVLM_PORTAL_ACCESS_TOKEN")
    if access_token:
        headers["access-token"] = access_token
    cookie = _setting("DSVLM_PORTAL_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    proxy_connection = _setting("DSVLM_PROXY_CONNECTION")
    if proxy_connection:
        headers["Proxy-Connection"] = proxy_connection

    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        masked_text = _mask_text(text)
        for secret in _secret_values(parsed):
            masked_text = masked_text.replace(secret, "<set>")
        return {
            "success": response.status == 200,
            "status_code": response.status,
            "headers": {key: ("<set>" if key in SENSITIVE_HEADER_NAMES else value) for key, value in headers.items()},
            "response_text": masked_text,
            "response_json": _mask_obj(parsed),
        }


def _write_env_value(key, value, path=DEFAULT_ENV_PATH):
    """把刷新到的 token 写回 .env，保留其他配置行。"""
    global ENV
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for index, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[index] = "%s=%s" % (key, value)
            break
    else:
        lines.append("%s=%s" % (key, value))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ENV[key] = value
    os.environ[key] = value


def _find_token(value):
    """从登录响应里递归找 token，兼容 access_token/accessToken 等字段名。"""
    if isinstance(value, str):
        return value if len(value) >= 16 else ""
    if isinstance(value, dict):
        for key in ("access_token", "accessToken", "token", "authorization"):
            token = _find_token(value.get(key))
            if token:
                return token
        for child in value.values():
            token = _find_token(child)
            if token:
                return token
    return ""


def refresh_authorization(write_env=True, timeout=30):
    """登录 61.172 并刷新 DSVLM_ACCESS_TOKEN；不创建、不修改算法配置。"""
    api_base = _setting("DSVLM_API_BASE", DEFAULT_API_BASE).rstrip("/")
    endpoint = _setting("DSVLM_LOGIN_ENDPOINT", "/s/sys/auth/login")
    authorization = _setting("DSVLM_LOGIN_AUTHORIZATION") or _setting("DSVLM_AUTHORIZATION")
    payload = {
        "username": _setting("DSVLM_LOGIN_USERNAME"),
        "password": _setting("DSVLM_LOGIN_PASSWORD"),
        "key": _setting("DSVLM_LOGIN_KEY"),
        "captcha": _setting("DSVLM_LOGIN_CAPTCHA"),
    }
    headers = {
        "Accept": _setting("DSVLM_ACCEPT", "application/json, text/plain, */*"),
        "Accept-Language": _setting("DSVLM_ACCEPT_LANGUAGE", "zh-CN"),
        "Authorization": authorization,
        "Content-Type": _setting("DSVLM_CONTENT_TYPE", "application/json;charset=UTF-8"),
        "Origin": _setting("DSVLM_ORIGIN", api_base),
        "Referer": _setting("DSVLM_REFERER", api_base + "/"),
        "User-Agent": _setting("DSVLM_USER_AGENT", "Mozilla/5.0"),
    }
    proxy_connection = _setting("DSVLM_PROXY_CONNECTION")
    if proxy_connection:
        headers["Proxy-Connection"] = proxy_connection

    url = "%s%s?t=%d" % (api_base, endpoint, int(time.time() * 1000))
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        token = _find_token(parsed)
        if token and write_env:
            _write_env_value("DSVLM_ACCESS_TOKEN", token)
        masked_text = _mask_text(text)
        for secret in _secret_values(parsed):
            masked_text = masked_text.replace(secret, "<set>")
        return {
            "success": response.status == 200 and bool(token),
            "status_code": response.status,
            "url": url,
            "headers": {key: ("<set>" if key in SENSITIVE_HEADER_NAMES else value) for key, value in headers.items()},
            "wrote_access_token": bool(token and write_env),
            "response_text": masked_text,
            "response_json": _mask_obj(parsed),
        }


def fetch_theme_data_page(**kwargs):
    """只读当前主题下的算法列表，用于验证主题 id 和鉴权是否正确。"""
    api_base = kwargs.get("api_base") or _setting("DSVLM_API_BASE", DEFAULT_API_BASE)
    endpoint = kwargs.get("endpoint") or _setting("DSVLM_DATA_PAGE_ENDPOINT", DEFAULT_DATA_PAGE_ENDPOINT)
    timeout = _as_int(kwargs.get("timeout") or _setting("DSVLM_TIMEOUT"), 30)
    if _as_bool(kwargs.get("ensure_auth"), True):
        auth_result = ensure_authorization(api_base, timeout)
        if not auth_result.get("success"):
            return auth_result
    payload = build_data_page_payload(**kwargs)
    result = post_payload(api_base, endpoint, payload, _base_headers(api_base), timeout)
    result["response_text"] = _mask_text(result["response_text"])
    result["response_json"] = _mask_obj(result["response_json"])
    return result


def main(**kwargs):
    """默认 dry-run；只有 dry_run=False 时才提交 /s/theme/data。"""
    api_base = kwargs.get("api_base") or _setting("DSVLM_API_BASE", DEFAULT_API_BASE)
    endpoint = kwargs.get("endpoint") or _setting("DSVLM_ENDPOINT", DEFAULT_ENDPOINT)
    authorization = kwargs.get("authorization") or _setting("DSVLM_AUTHORIZATION")
    dry_run = _as_bool(kwargs.get("dry_run"), True)
    timeout = _as_int(kwargs.get("timeout") or _setting("DSVLM_TIMEOUT"), 30)
    if not kwargs.get("payload") and "sort" not in kwargs:
        kwargs["_auto_sort"] = True
    payload = kwargs.get("payload") or build_payload(**kwargs)
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
    if _as_bool(_setting("DSVLM_DYNAMIC_AUTH", "true"), True):
        auth_result = ensure_authorization(api_base, timeout)
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
        if skip_existing and not force_post and payload.get("themeLabel"):
            existing = find_existing_theme(api_base, payload["themeLabel"], timeout)
            if existing:
                return {"api_result": [_already_exists_result(payload, existing)]}
        if _as_bool(kwargs.get("_auto_sort"), False):
            # ponytail: one list read; page through only if the platform proves 200 is too small.
            payload["sort"] = next_sort_after_existing(api_base, timeout)
        result = post_payload(api_base, endpoint, payload, headers, timeout)
        if result.get("success"):
            result["status"] = "POST_SUCCEEDED_DO_NOT_RETRY"
            result["posted"] = True
            result["message"] = "平台已返回 success；不要再次 post。"
        else:
            result["status"] = "POST_FAILED"
            result["posted"] = False
        return {"api_result": [result]}
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        return {
            "api_result": [{
                "success": False,
                "status": "POST_HTTP_ERROR",
                "posted": False,
                "status_code": error.code,
                "error": text,
            }]
        }
    except Exception as error:
        return {
            "api_result": [{
                "success": False,
                "status": "POST_EXCEPTION",
                "posted": False,
                "error": "执行失败：%s" % error,
            }]
        }


def sample_kwargs():
    """CLI 无 config 时的最小样例；真实新建建议用 agent-output 自动排序。"""
    return {
        "name": "demo-算法",
        "theme_label": "demo-算法",
        "theme_type_id": DEFAULT_THEME_TYPE_ID,
        "mode": 1,
        "level": 1,
        "area_flag": True,
        "sort": 1,
        "extension_type": 2,
        "extension_ratio": 0,
        "rules": [{"parsingId": "1", "rule": ""}],
    }


def _read_text_arg(value):
    if value == "-":
        return sys.stdin.read()
    return Path(value).read_text(encoding="utf-8")


def _load_config(path):
    if not path:
        return sample_kwargs()
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _self_test():
    sample_request = "/dsvlm 场景：识别垃圾车 --垃圾车识别 --post"
    sample_output = """
算法: 临时名称
解析模式: 通用模式
预警等级: 二级预警
启用区域框: 开
排序: 自动
思维条件1: 目标理解 / 多模态目标理解 / garbage truck / 大于 / 0 / 阈值 60
思维条件2: 内容理解 / 正向思维1 / 图中出现垃圾车正在停靠、行驶或进行垃圾清运作业
备注: 自动解析测试
"""
    parsed = parse_agent_output(sample_output, user_request=sample_request)
    assert parsed["theme_label"] == "垃圾车识别"
    assert parsed["mode"] == 1
    assert parsed["level"] == 2
    assert parsed["area_flag"] is True
    assert parsed["_auto_sort"] is True
    assert len(parsed["rules"]) == 2
    assert parsed["rules"][0] == {"parsingId": "dmt_counter", "rule": "garbage truck|gt|0|0.6"}
    assert parsed["rules"][1]["parsingId"] == "1"
    assert _platform_rule("目标理解 / 通用目标理解 / 人 / 大于 / 80") == {
        "parsingId": "counter",
        "rule": "person|gt|0|0.8",
    }
    assert _platform_rule("文字理解 / OCR / 1") == {"parsingId": "ocr", "rule": "1"}
    assert _platform_rule("内容理解 / 正向思维2 / 正向思维2") == {"parsingId": "11", "rule": "正向思维2"}
    assert _platform_rule("内容理解 / 正向思维20 / 正向思维20") == {"parsingId": "21", "rule": "正向思维20"}
    assert _platform_rule("内容理解 / 反向思维2 / 反向思维2") == {"parsingId": "12", "rule": "反向思维2"}
    assert _platform_rule("内容理解 / 反向思维20 / 反向思维20") == {"parsingId": "22", "rule": "反向思维20"}
    assert _platform_rule("深度内容理解 / 正向深度思维2 / 正向深度思维2") == {
        "parsingId": "103",
        "rule": "正向深度思维2",
    }
    assert _platform_rule("深度内容理解 / 反向深度思维2 / 反向深度思维2") == {
        "parsingId": "104",
        "rule": "反向深度思维2",
    }
    assert _platform_rule("深度内容理解 / 正向深度思维20 / 正向深度思维20") == {
        "parsingId": "121",
        "rule": "正向深度思维20",
    }
    assert _platform_rule("深度内容理解 / 反向深度思维20 / 反向深度思维20") == {
        "parsingId": "122",
        "rule": "反向深度思维20",
    }
    assert build_payload(**parsed)["themeLabel"] == "垃圾车识别"
    fixed_sort = parse_agent_output(
        sample_output.replace("排序: 自动", "排序: 7"),
        user_request=sample_request + " 排序:7",
    )
    assert fixed_sort["sort"] == 7
    assert fixed_sort["_auto_sort"] is False
    legacy_sort = parse_agent_output(sample_output.replace("排序: 自动", "排序: 1"), user_request=sample_request)
    assert legacy_sort["sort"] == 1
    assert legacy_sort["_auto_sort"] is True
    table_output = """
| 字段 | 内容 |
| --- | --- |
| 算法 | 临时名称 |
| 解析模式 | 通用模式 |
| 预警等级 | 二级预警 |
| 启用区域框 | 开 |
| 排序 | 自动 |
| 思维条件1 | 目标理解 / 多模态目标理解 / garbage truck / 大于 / 0 / 阈值 60 |
| 思维条件2 | 内容理解 / 正向思维1 / 图中出现垃圾车正在停靠、行驶或进行垃圾清运作业 |
| 备注 | 自动解析测试 |
"""
    parsed_table = parse_agent_output(table_output, user_request=sample_request)
    assert parsed_table["theme_label"] == "垃圾车识别"
    assert parsed_table["rules"][0] == {"parsingId": "dmt_counter", "rule": "garbage truck|gt|0|0.6"}
    original_fetch_existing_theme_page = fetch_existing_theme_page
    try:
        globals()["fetch_existing_theme_page"] = lambda api_base, timeout, theme_label="", limit=200: {
            "success": True,
            "response_json": {"data": {"total": 34, "list": [{"sort": 1}, {"sort": "7"}, {"sort": None}]}},
        }
        assert next_sort_after_existing("http://example.invalid", 1) == 35
        globals()["fetch_existing_theme_page"] = lambda api_base, timeout, theme_label="", limit=200: {
            "success": True,
            "response_json": {"data": {"total": 3, "list": [{"sort": 1}, {"sort": "7"}, {"sort": None}]}},
        }
        assert next_sort_after_existing("http://example.invalid", 1) == 8
    finally:
        globals()["fetch_existing_theme_page"] = original_fetch_existing_theme_page
    existing_result = _already_exists_result(
        build_payload(**parsed),
        {"id": "abc", "themeLabel": "垃圾车识别", "sort": 1, "level": 2, "mode": 1, "updateTime": "now"},
    )
    assert existing_result["success"] is True
    assert existing_result["posted"] is False
    assert existing_result["status"] == "ALREADY_EXISTS_DO_NOT_RETRY"
    assert parse_user_request(sample_request)["post"] is True
    assert parse_user_request("/dsvlm 场景：识别垃圾车 --垃圾车识别") == {
        "scene": "识别垃圾车",
        "algorithm_name": "垃圾车识别",
        "post": False,
    }
    assert parse_user_request("/dsvlm 场景：流浪猫狗 测猫狗") == {
        "scene": "流浪猫狗 测猫狗",
        "algorithm_name": "",
        "post": False,
    }
    assert parse_user_request("/dsvlm 场景：流浪猫狗 --测猫狗") == {
        "scene": "流浪猫狗",
        "algorithm_name": "测猫狗",
        "post": False,
    }
    return {"success": True}


def cli():
    parser = argparse.ArgumentParser(description="构造或提交华鲲元启视频算法配置 payload。")
    parser.add_argument("--auto-login", action="store_true", help="只读取算法中心自动登录地址。")
    parser.add_argument("--refresh-auth", action="store_true", help="登录 61.172 并刷新 DSVLM_ACCESS_TOKEN。")
    parser.add_argument("--theme-data-page", action="store_true", help="只读取当前主题算法列表。")
    parser.add_argument("--self-test", action="store_true", help="运行本地解析自检，不访问平台。")
    parser.add_argument("--theme-label", default="", help="按算法名称过滤列表。")
    parser.add_argument("--theme-type-id", default=None, help="主题 ID；默认读取 DSVLM_THEME_TYPE_ID。")
    parser.add_argument("--page", type=int, default=1, help="列表页码。")
    parser.add_argument("--limit", type=int, default=20, help="每页数量。")
    parser.add_argument("--config", help="JSON 配置文件，可传 kwargs 或原始 payload 字段。")
    parser.add_argument("--agent-output", help="dsvlm 输出文件；传 - 从 stdin 读取。")
    parser.add_argument("--user-request", default="", help="原始用户请求，用于提取 场景：xx --算法名 --post。")
    parser.add_argument("--algorithm-name", default="", help="手动覆盖算法名称。")
    parser.add_argument("--post", action="store_true", help="真正提交到接口；--agent-output 模式下还要求 user-request 里有 post。")
    parser.add_argument("--force-post", action="store_true", help="跳过同名算法防重复检查，强制写入。")
    parser.add_argument("--authorization", help="手动指定 Authorization；优先使用动态鉴权。")
    parser.add_argument("--api-base", default=None, help="接口根地址。")
    parser.add_argument("--endpoint", default=None, help="接口路径。")
    args = parser.parse_args()

    if args.auto_login:
        print(json.dumps(fetch_auto_login_url(), ensure_ascii=False, indent=2))
        return
    if args.refresh_auth:
        print(json.dumps(refresh_authorization(), ensure_ascii=False, indent=2))
        return
    if args.theme_data_page:
        print(json.dumps(fetch_theme_data_page(
            theme_label=args.theme_label,
            theme_type_id=args.theme_type_id,
            page=args.page,
            limit=args.limit,
        ), ensure_ascii=False, indent=2))
        return
    if args.self_test:
        print(json.dumps(_self_test(), ensure_ascii=False, indent=2))
        return

    if args.agent_output:
        kwargs = parse_agent_output(
            _read_text_arg(args.agent_output),
            user_request=args.user_request,
            algorithm_name=args.algorithm_name,
        )
    else:
        kwargs = _load_config(args.config)
    request_args = parse_user_request(args.user_request)
    if args.agent_output:
        # ponytail: agent-output trusts the original user request, not model-added --post.
        should_post = request_args["post"] or args.force_post
    else:
        should_post = args.post or args.force_post
    kwargs["dry_run"] = not should_post
    kwargs["force_post"] = args.force_post
    if args.authorization:
        kwargs["authorization"] = args.authorization
    if args.api_base:
        kwargs["api_base"] = args.api_base
    if args.endpoint:
        kwargs["endpoint"] = args.endpoint
    print(json.dumps(main(**kwargs), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
