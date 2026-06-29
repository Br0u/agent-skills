#!/usr/bin/env python3
"""Create/update dsvlm .env from three copied DevTools cURL commands."""

import argparse
import json
import shlex
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = SKILL_DIR / ".env"
SENSITIVE_PARTS = ("TOKEN", "PASSWORD", "AUTHORIZATION", "COOKIE")


def read_curl(label):
    print("\n请粘贴第 %s 段 cURL，粘贴完成后按一次空行结束：" % label)
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip() and lines:
            break
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def clean_token(value):
    # Chrome can emit bash $'...' strings; shlex leaves a leading '$'.
    return value[1:] if value.startswith("$") else value


def parse_curl(command):
    tokens = [clean_token(token) for token in shlex.split(command.replace("\\\n", " "))]
    if tokens and tokens[0] == "curl":
        tokens = tokens[1:]

    url = ""
    headers = {}
    data = ""
    skip_next = False
    one_arg_options = {"-X", "--request", "-A", "--user-agent", "-e", "--referer"}

    for index, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        if token in ("-H", "--header"):
            header = tokens[index + 1]
            skip_next = True
        elif token.startswith("--header="):
            header = token.split("=", 1)[1]
        else:
            header = ""

        if header:
            if ":" in header:
                name, value = header.split(":", 1)
                headers[name.strip().lower()] = value.strip()
            continue

        if token in ("--data", "--data-raw", "--data-binary", "--data-ascii", "-d"):
            data = tokens[index + 1]
            skip_next = True
            continue
        if token.startswith("--data-"):
            data = token.split("=", 1)[1] if "=" in token else data
            continue
        if token == "--url":
            url = tokens[index + 1]
            skip_next = True
            continue
        if token.startswith("--url="):
            url = token.split("=", 1)[1]
            continue
        if token in one_arg_options:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        if not url:
            url = token

    if not url:
        raise ValueError("missing URL in cURL")
    return {"url": url, "headers": headers, "data": data}


def parse_payload(data):
    if not data:
        return {}
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        parsed = parse_qs(data, keep_blank_values=True)
        return {key: values[-1] for key, values in parsed.items()}


def origin_and_path(url):
    parsed = urlparse(url)
    return "%s://%s" % (parsed.scheme, parsed.netloc), parsed.path


def apply_header_values(values, parsed):
    headers = parsed["headers"]
    mapping = {
        "accept": "DSVLM_ACCEPT",
        "accept-language": "DSVLM_ACCEPT_LANGUAGE",
        "content-type": "DSVLM_CONTENT_TYPE",
        "origin": "DSVLM_ORIGIN",
        "referer": "DSVLM_REFERER",
        "user-agent": "DSVLM_USER_AGENT",
        "proxy-connection": "DSVLM_PROXY_CONNECTION",
    }
    for header, env_key in mapping.items():
        if headers.get(header):
            values[env_key] = headers[header]


def values_from_curls(auto_login_curl, login_curl, theme_page_curl):
    auto_login = parse_curl(auto_login_curl)
    login = parse_curl(login_curl)
    theme_page = parse_curl(theme_page_curl)
    login_payload = parse_payload(login["data"])
    theme_payload = parse_payload(theme_page["data"])
    api_base, login_path = origin_and_path(login["url"])
    theme_api_base, theme_path = origin_and_path(theme_page["url"])

    values = {
        "DSVLM_API_BASE": theme_api_base or api_base,
        "DSVLM_DYNAMIC_AUTH": "true",
        "DSVLM_AUTHORIZATION": "",
        "DSVLM_ACCESS_TOKEN": "",
        "DSVLM_LOGIN_ENDPOINT": login_path,
        "DSVLM_LOGIN_AUTHORIZATION": login["headers"].get("authorization", ""),
        "DSVLM_LOGIN_USERNAME": str(login_payload.get("username", "")),
        "DSVLM_LOGIN_PASSWORD": str(login_payload.get("password", "")),
        "DSVLM_LOGIN_KEY": str(login_payload.get("key", "")),
        "DSVLM_LOGIN_CAPTCHA": str(login_payload.get("captcha", "")),
        "DSVLM_DATA_PAGE_ENDPOINT": theme_path,
        "DSVLM_ENDPOINT": theme_path[:-5] if theme_path.endswith("/page") else "/s/theme/data",
        "DSVLM_THEME_TYPE_ID": str(theme_payload.get("themeTypeId", "")),
        "DSVLM_PORTAL_AUTO_LOGIN_URL": auto_login["url"],
        "DSVLM_PORTAL_ACCESS_TOKEN": auto_login["headers"].get("access-token", ""),
        "DSVLM_PORTAL_COOKIE": auto_login["headers"].get("cookie", ""),
        "DSVLM_PORTAL_REFERER": auto_login["headers"].get("referer", ""),
    }
    apply_header_values(values, theme_page)
    missing = [key for key in (
        "DSVLM_LOGIN_AUTHORIZATION",
        "DSVLM_LOGIN_USERNAME",
        "DSVLM_LOGIN_PASSWORD",
        "DSVLM_THEME_TYPE_ID",
    ) if not values.get(key)]
    if missing:
        raise ValueError("missing required fields: %s" % ", ".join(missing))
    return values


def write_env(path, values):
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = set()
    output = []
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in values:
            output.append("%s=%s" % (key, values[key]))
            seen.add(key)
        else:
            output.append(line)
    for key, value in values.items():
        if key not in seen:
            output.append("%s=%s" % (key, value))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def masked(value, key):
    if not value:
        return "<empty>"
    return "<set>" if any(part in key for part in SENSITIVE_PARTS) else value


def self_test():
    auto = "curl 'http://portal/api/video/algorithm-center/auto-login-url' -H 'access-token: portal-token' -H 'Cookie: a=b' -H 'Referer: http://portal/page'"
    login = "curl 'http://61.172.168.94:8898/s/sys/auth/login?t=1' -H 'Authorization: login-auth' --data-raw '{\"username\":\"u\",\"password\":\"p\",\"key\":\"\",\"captcha\":\"\"}'"
    theme = "curl 'http://61.172.168.94:8898/s/theme/data/page?t=2' -H 'Origin: http://61.172.168.94:8898' -H 'Referer: http://61.172.168.94:8898/' --data-raw '{\"themeTypeId\":\"theme-id\",\"page\":1}'"
    values = values_from_curls(auto, login, theme)
    assert values["DSVLM_LOGIN_AUTHORIZATION"] == "login-auth"
    assert values["DSVLM_LOGIN_USERNAME"] == "u"
    assert values["DSVLM_THEME_TYPE_ID"] == "theme-id"
    assert values["DSVLM_ENDPOINT"] == "/s/theme/data"
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text("DSVLM_DYNAMIC_AUTH=false\nKEEP=1\n", encoding="utf-8")
        write_env(env_path, values)
        text = env_path.read_text(encoding="utf-8")
        assert "DSVLM_DYNAMIC_AUTH=true" in text
        assert "KEEP=1" in text
    return {"success": True}


def main():
    parser = argparse.ArgumentParser(description="用 DevTools 复制的 cURL 自动配置 dsvlm .env。")
    parser.add_argument("--env", default=str(DEFAULT_ENV_PATH), help="默认写入 skill 目录下的 .env。")
    parser.add_argument("--self-test", action="store_true", help="本地自检，不读取输入、不访问网络。")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return

    values = values_from_curls(
        read_curl("1/3：auto-login-url"),
        read_curl("2/3：login"),
        read_curl("3/3：theme data page"),
    )
    write_env(args.env, values)
    print("\n已更新 %s" % args.env)
    for key in sorted(values):
        print("%s=%s" % (key, masked(values[key], key)))


if __name__ == "__main__":
    main()
