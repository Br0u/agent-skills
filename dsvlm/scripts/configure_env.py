#!/usr/bin/env python3
"""Configure direct DSVLM login with one private account."""

import argparse
import getpass
import json
import os
import sys
import tempfile
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = SKILL_DIR / ".env"


def values_from_credentials(username, password):
    username = str(username or "").strip()
    password = str(password or "")
    if not username or not password:
        raise ValueError("账号和密码不能为空")
    if any(char in username + password for char in ("\r", "\n", "\x00")):
        raise ValueError("账号或密码包含非法字符")
    return {
        "DSVLM_ALLOW_INSECURE_HTTP": "true",
        "DSVLM_LOGIN_USERNAME": username,
        "DSVLM_LOGIN_PASSWORD": password,
    }


def _format_env_value(value):
    if value != value.strip() or any(char in value for char in '#"\\'):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_env(path, values):
    path = Path(path)
    for value in values.values():
        if not isinstance(value, str) or any(char in value for char in ("\r", "\n", "\x00")):
            raise ValueError("invalid environment value")

    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = set()
    output = []
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if (
            key.startswith("DSVLM_")
            and not key.startswith("DSVLM_SERVICE_")
            and key not in values
        ):
            continue
        if key in values:
            output.append("%s=%s" % (key, _format_env_value(values[key])))
            seen.add(key)
        else:
            output.append(line)
    for key, value in values.items():
        if key not in seen:
            output.append("%s=%s" % (key, _format_env_value(value)))

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".%s." % path.name)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def masked(value, key):
    if not value:
        return "<empty>"
    return "<set>" if any(part in key for part in ("TOKEN", "PASSWORD", "AUTHORIZATION", "COOKIE")) else value


def self_test():
    values = values_from_credentials("admin", "password ")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / ".env"
        path.write_text(
            "DSVLM_THEME_TYPE_ID=old\nDSVLM_SERVICE_TOKEN=service\nKEEP=1\n",
            encoding="utf-8",
        )
        write_env(path, values)
        text = path.read_text(encoding="utf-8")
        assert 'DSVLM_LOGIN_PASSWORD="password "' in text
        assert "DSVLM_THEME_TYPE_ID" not in text
        assert "DSVLM_SERVICE_TOKEN=service" in text
        assert "KEEP=1" in text
    return {"success": True}


def main():
    parser = argparse.ArgumentParser(description="用一组管理员账号配置 DSVLM 直连登录。")
    parser.add_argument("--env", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--username", default="")
    parser.add_argument("--password-stdin", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False))
        return

    username = args.username or input("管理员账号：").strip()
    password = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("管理员密码（输入不显示）：")
    values = values_from_credentials(username, password)
    write_env(args.env, values)
    print("已更新 %s" % args.env)
    for key in sorted(values):
        print("%s=%s" % (key, masked(values[key], key)))


if __name__ == "__main__":
    main()
