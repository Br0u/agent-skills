#!/usr/bin/env python3
"""Client for the dsvlm algorithm service."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = SKILL_DIR / ".env"
DEFAULT_API_BASE = "http://61.172.168.94:9079"


class AuthError(RuntimeError):
    """Authentication is missing or rejected."""


class ServiceError(RuntimeError):
    """The algorithm service returned an invalid or failed response."""

    def __init__(self, message, *, http_status=None, business_code=None):
        super().__init__(message)
        self.http_status = http_status
        self.business_code = business_code


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject every redirect so credentials cannot reach another target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _safe_business_code(value, token):
    if type(value) is int:
        return None if str(value) == str(token) else value
    if isinstance(value, str):
        value = value.strip()
        if (
            value
            and len(value) <= 10
            and value.lstrip("-").isdigit()
            and value != str(token)
        ):
            return int(value)
    return None


def load_env_file(path):
    """Read simple KEY=VALUE settings from a local environment file."""
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
        if not key:
            continue
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        values[key] = value
    return values


def resolve_token(env=None, env_path=None):
    """Resolve service credentials, preferring the supplied environment."""
    environment = os.environ if env is None else env
    file_values = load_env_file(env_path or DEFAULT_ENV_PATH)
    token = (
        environment.get("DSVLM_SERVICE_TOKEN")
        or environment.get("HKVLM_API_TOKEN")
        or file_values.get("DSVLM_SERVICE_TOKEN")
        or file_values.get("HKVLM_API_TOKEN")
    )
    if not token or not str(token).strip():
        raise AuthError("9079 服务凭据缺失")
    return str(token).strip()


def _resolve_allow_insecure_http(value=None):
    if value is None:
        value = _setting("DSVLM_SERVICE_ALLOW_INSECURE_HTTP", "false")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _validate_transport_url(url, allow_insecure_http=None):
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    allow_insecure = _resolve_allow_insecure_http(allow_insecure_http)
    if scheme == "https" or (scheme == "http" and allow_insecure):
        return allow_insecure
    if scheme == "http":
        raise ServiceError("plain HTTP is disabled")
    raise ServiceError("unsupported service URL scheme")


def request_json(
    method,
    url,
    *,
    token,
    payload=None,
    timeout=30,
    allow_insecure_http=None,
):
    """Send an authenticated request and validate the service envelope."""
    _validate_transport_url(url, allow_insecure_http)
    if not token or not str(token).strip():
        raise AuthError("9079 服务凭据缺失")

    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": str(token),
            "Content-Type": "application/json",
        },
        method=method.upper(),
    )

    try:
        opener = urllib.request.build_opener(NoRedirectHandler())
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            raw_body = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        if status == 401:
            raise AuthError("HTTP 401") from None
        raise ServiceError(f"HTTP {status}", http_status=status) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ServiceError("9079 服务请求失败") from None

    if status == 401:
        raise AuthError("HTTP 401")
    if status is not None and not 200 <= status < 300:
        raise ServiceError(f"HTTP {status}", http_status=status)

    try:
        result = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, AttributeError):
        raise ServiceError("9079 服务响应不是有效 JSON") from None
    if not isinstance(result, dict):
        raise ServiceError("9079 服务响应格式错误")

    code = result.get("code")
    if code in (401, "401"):
        raise AuthError("business code 401")
    if code not in (0, "0"):
        safe_code = _safe_business_code(code, token)
        if safe_code is None:
            raise ServiceError("business error")
        raise ServiceError(
            f"business code {safe_code}",
            business_code=safe_code,
        )
    return result


def _setting(name, default=None):
    return os.environ.get(name) or load_env_file(DEFAULT_ENV_PATH).get(name) or default


def _service_api_base(allow_insecure=None):
    base = _setting("DSVLM_SERVICE_API_BASE", DEFAULT_API_BASE).rstrip("/")
    _validate_transport_url(base, allow_insecure)
    return base


def _service_timeout(timeout, default):
    value = timeout
    if value is None:
        value = _setting("DSVLM_SERVICE_TIMEOUT", default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ServiceError("DSVLM_SERVICE_TIMEOUT 必须是正数") from None
    if not math.isfinite(parsed) or parsed <= 0:
        raise ServiceError("DSVLM_SERVICE_TIMEOUT 必须是正数")
    return parsed


def get_all_algorithms(*, token=None, timeout=None):
    """Return all algorithms visible to the configured service account."""
    allow_insecure_http = _resolve_allow_insecure_http()
    api_base = _service_api_base(allow_insecure_http)
    service_token = resolve_token() if token is None else token
    return request_json(
        "GET",
        f"{api_base}/v1/api/themeData/all",
        token=service_token,
        timeout=_service_timeout(timeout, 30),
        allow_insecure_http=allow_insecure_http,
    )


def add_algorithm(
    theme_data_name,
    text,
    algorithm_type,
    type_description="",
    *,
    token=None,
    timeout=None,
):
    """Add an algorithm definition to the 9079 service."""
    if not str(theme_data_name or "").strip():
        raise ValueError("theme_data_name is required")
    if not str(text or "").strip():
        raise ValueError("text is required")
    if algorithm_type not in (1, 2, 99):
        raise ValueError("algorithm_type must be 1, 2, or 99")
    normalized_type_description = str(type_description or "").strip()
    if algorithm_type == 99 and not re.search(
        r"[\u3400-\u4dbf\u4e00-\u9fff]",
        normalized_type_description,
    ):
        raise ValueError(
            "type_description must contain Chinese when algorithm_type is 99"
        )

    payload = {
        "themeDataName": theme_data_name,
        "text": text,
        "type": algorithm_type,
    }
    if normalized_type_description:
        payload["typeDescription"] = normalized_type_description

    allow_insecure_http = _resolve_allow_insecure_http()
    api_base = _service_api_base(allow_insecure_http)
    service_token = resolve_token() if token is None else token
    return request_json(
        "POST",
        f"{api_base}/v1/api/themeData/add",
        token=service_token,
        payload=payload,
        timeout=_service_timeout(timeout, 300),
        allow_insecure_http=allow_insecure_http,
    )


def cli(argv=None):
    """Run the algorithm-service command-line client."""
    parser = argparse.ArgumentParser(description="华鲲元启 9079 算法服务客户端")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--list", action="store_true", help="列出全部算法")
    operation.add_argument("--add", action="store_true", help="新增算法")
    parser.add_argument("--name", help="算法名称")
    parser.add_argument("--text", help="算法描述文本")
    parser.add_argument("--type", dest="algorithm_type", type=int, choices=(1, 2, 99))
    parser.add_argument("--type-description", default="", help="type=99 时必填")
    args = parser.parse_args(argv)

    if args.add:
        missing = [
            flag
            for flag, value in (
                ("--name", args.name),
                ("--text", args.text),
                ("--type", args.algorithm_type),
            )
            if value is None
        ]
        if missing:
            parser.error(f"--add requires {', '.join(missing)}")

    try:
        if args.list:
            result = get_all_algorithms()
        else:
            result = add_algorithm(
                args.name,
                args.text,
                args.algorithm_type,
                args.type_description,
            )
    except (AuthError, ServiceError, ValueError) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
