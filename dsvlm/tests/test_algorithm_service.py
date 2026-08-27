import json
import io
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "algorithm_service.py"
SPEC = importlib.util.spec_from_file_location("dsvlm_algorithm_service", SCRIPT)
algorithm_service = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(algorithm_service)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class FakeOpener:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        if callable(self.result):
            return self.result(request, timeout)
        return self.result


def opener_patch(result):
    return mock.patch(
        "urllib.request.build_opener",
        return_value=FakeOpener(result),
    )


def make_http_error(status, body=b""):
    return algorithm_service.urllib.error.HTTPError(
        "https://origin.invalid",
        status,
        "test status",
        {},
        io.BytesIO(body),
    )


class AlgorithmServiceTests(unittest.TestCase):
    def test_no_redirect_handler_never_creates_a_redirect_request(self):
        original = algorithm_service.urllib.request.Request(
            "https://origin.invalid",
            headers={"Authorization": "fake-redirect-secret"},
        )

        redirected = algorithm_service.NoRedirectHandler().redirect_request(
            original,
            None,
            302,
            "Found",
            {},
            "https://redirect.invalid",
        )

        self.assertIsNone(redirected)

    def test_request_json_uses_no_redirect_opener(self):
        response = FakeResponse({"code": 0, "data": []})
        opener = FakeOpener(response)
        captured_handlers = []

        def fake_build_opener(*handlers):
            captured_handlers.extend(handlers)
            return opener

        def unexpected_urlopen(*args, **kwargs):
            self.fail("request_json must use the no-redirect opener")

        with (
            mock.patch("urllib.request.build_opener", side_effect=fake_build_opener),
            mock.patch("urllib.request.urlopen", side_effect=unexpected_urlopen),
        ):
            result = algorithm_service.request_json(
                "GET",
                "https://example.invalid",
                token="fake-test-token",
                timeout=13,
            )

        self.assertEqual(result["data"], [])
        self.assertTrue(
            any(
                isinstance(handler, algorithm_service.NoRedirectHandler)
                for handler in captured_handlers
            )
        )
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(opener.requests[0][1], 13)

    def test_request_json_rejects_plain_http_before_opening(self):
        fake_token = "fake-direct-http-secret"
        opener_factory = mock.Mock(
            side_effect=AssertionError("plain HTTP must fail before opener creation")
        )

        with (
            mock.patch.dict(algorithm_service.os.environ, {}, clear=True),
            mock.patch("urllib.request.build_opener", new=opener_factory),
        ):
            with self.assertRaises(algorithm_service.ServiceError) as error:
                algorithm_service.request_json(
                    "GET",
                    "http://example.invalid",
                    token=fake_token,
                )

        opener_factory.assert_not_called()
        self.assertNotIn(fake_token, str(error.exception))

    def test_request_json_explicit_http_opt_in_calls_opener(self):
        captured = {}

        def fake_open(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            return FakeResponse({"code": 0, "data": ["ok"]})

        with (
            mock.patch.dict(algorithm_service.os.environ, {}, clear=True),
            opener_patch(fake_open),
        ):
            result = algorithm_service.request_json(
                "GET",
                "http://example.invalid",
                token="fake-opt-in-token",
                allow_insecure_http=True,
            )

        self.assertEqual(captured["url"], "http://example.invalid")
        self.assertEqual(captured["authorization"], "fake-opt-in-token")
        self.assertEqual(result["data"], ["ok"])

    def test_redirect_is_service_error_with_status_only(self):
        fake_token = "fake-redirect-secret"

        with opener_patch(make_http_error(302, fake_token.encode("utf-8"))):
            with self.assertRaises(algorithm_service.ServiceError) as error:
                algorithm_service.request_json(
                    "GET",
                    "https://origin.invalid",
                    token=fake_token,
                )

        self.assertEqual(str(error.exception), "HTTP 302")
        self.assertEqual(error.exception.http_status, 302)
        self.assertNotIn(fake_token, str(error.exception))

    def test_missing_token_fails_closed_without_local_env(self):
        with tempfile.TemporaryDirectory() as directory:
            missing_env = Path(directory) / ".env"

            with self.assertRaises(algorithm_service.AuthError):
                algorithm_service.resolve_token(env={}, env_path=missing_env)

    def test_explicit_environment_token_takes_precedence_over_private_env(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "DSVLM_SERVICE_TOKEN=fake-file-token\n",
                encoding="utf-8",
            )

            token = algorithm_service.resolve_token(
                env={"DSVLM_SERVICE_TOKEN": "fake-explicit-token"},
                env_path=env_path,
            )

        self.assertEqual(token, "fake-explicit-token")

    def test_compatible_token_alias_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("HKVLM_API_TOKEN=fake-alias-token\n", encoding="utf-8")

            token = algorithm_service.resolve_token(env={}, env_path=env_path)

        self.assertEqual(token, "fake-alias-token")

    def test_business_code_401_is_masked_auth_error(self):
        fake_token = "fake-secret-token"
        response = FakeResponse({"code": 401, "msg": "token错误"})

        with opener_patch(response):
            with self.assertRaises(algorithm_service.AuthError) as error:
                algorithm_service.request_json(
                    "GET",
                    "https://example.invalid",
                    token=fake_token,
                )

        self.assertNotIn(fake_token, str(error.exception))

    def test_other_business_error_is_service_error(self):
        fake_token = "fake-business-secret"
        response = FakeResponse({"code": 999, "msg": fake_token})

        with opener_patch(response):
            with self.assertRaises(algorithm_service.ServiceError) as error:
                algorithm_service.request_json(
                    "GET",
                    "https://example.invalid",
                    token=fake_token,
                )

        self.assertEqual(str(error.exception), "business code 999")
        self.assertEqual(error.exception.business_code, 999)
        self.assertNotIn(fake_token, str(error.exception))

    def test_business_code_matching_token_is_not_exposed(self):
        fake_token = "999"
        response = FakeResponse({"code": 999, "msg": "failed"})

        with opener_patch(response):
            with self.assertRaises(algorithm_service.ServiceError) as error:
                algorithm_service.request_json(
                    "GET",
                    "https://example.invalid",
                    token=fake_token,
                )

        self.assertEqual(str(error.exception), "business error")
        self.assertIsNone(error.exception.business_code)
        self.assertNotIn(fake_token, str(error.exception))

    def test_malformed_json_is_service_error(self):
        response = FakeResponse(b"not-json")

        with opener_patch(response):
            with self.assertRaises(algorithm_service.ServiceError):
                algorithm_service.request_json(
                    "GET",
                    "https://example.invalid",
                    token="fake-test-token",
                )

    def test_non_object_json_is_service_error(self):
        response = FakeResponse([])

        with opener_patch(response):
            with self.assertRaises(algorithm_service.ServiceError):
                algorithm_service.request_json(
                    "GET",
                    "https://example.invalid",
                    token="fake-test-token",
                )

    def test_http_401_is_masked_auth_error(self):
        fake_token = "fake-http-secret"

        with opener_patch(make_http_error(401, fake_token.encode("utf-8"))):
            with self.assertRaises(algorithm_service.AuthError) as error:
                algorithm_service.request_json(
                    "GET",
                    "https://example.invalid",
                    token=fake_token,
                )

        self.assertEqual(str(error.exception), "HTTP 401")
        self.assertNotIn(fake_token, str(error.exception))

    def test_other_http_error_is_service_error(self):
        fake_token = "fake-http-secret"

        with opener_patch(make_http_error(503, fake_token.encode("utf-8"))):
            with self.assertRaises(algorithm_service.ServiceError) as error:
                algorithm_service.request_json(
                    "GET",
                    "https://example.invalid",
                    token=fake_token,
                )

        self.assertEqual(str(error.exception), "HTTP 503")
        self.assertEqual(error.exception.http_status, 503)
        self.assertNotIn(fake_token, str(error.exception))

    def test_http_error_response_is_closed(self):
        http_error = make_http_error(503, b"fake-response-body")
        response_stream = http_error.fp

        with opener_patch(http_error):
            with self.assertRaises(algorithm_service.ServiceError):
                algorithm_service.request_json(
                    "GET",
                    "https://example.invalid",
                    token="fake-test-token",
                )

        self.assertTrue(response_stream.closed)

    def test_type_99_requires_nonblank_description(self):
        with self.assertRaises(ValueError):
            algorithm_service.add_algorithm(
                "测试算法",
                "识别测试目标",
                99,
                "   ",
                token="fake-test-token",
            )

    def test_type_99_requires_at_least_one_chinese_character(self):
        for description in ("fire extinguisher", "type-123", "テスト"):
            with self.subTest(description=description):
                with self.assertRaises(ValueError):
                    algorithm_service.add_algorithm(
                        "测试算法",
                        "识别测试目标",
                        99,
                        description,
                        token="fake-test-token",
                    )

    def test_add_sends_exact_payload_and_authorization_header(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["authorization"] = request.get_header("Authorization")
            captured["content_type"] = request.get_header("Content-type")
            captured["timeout"] = timeout
            return FakeResponse({"code": 0, "msg": "success", "data": {"id": 7}})

        with (
            mock.patch.dict(
                algorithm_service.os.environ,
                {"DSVLM_SERVICE_API_BASE": "https://example.invalid:9079/"},
                clear=True,
            ),
            opener_patch(fake_urlopen),
        ):
            result = algorithm_service.add_algorithm(
                "自定义算法",
                "识别自定义事件",
                99,
                "中文类型说明",
                token="fake-test-token",
                timeout=12,
            )

        self.assertEqual(captured["url"], "https://example.invalid:9079/v1/api/themeData/add")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            captured["payload"],
            {
                "themeDataName": "自定义算法",
                "text": "识别自定义事件",
                "type": 99,
                "typeDescription": "中文类型说明",
            },
        )
        self.assertEqual(captured["authorization"], "fake-test-token")
        self.assertEqual(captured["content_type"], "application/json")
        self.assertEqual(captured["timeout"], 12)
        self.assertEqual(result["data"], {"id": 7})

    def test_add_omits_unsupplied_type_description(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            return FakeResponse({"code": 0, "data": {}})

        with (
            mock.patch.dict(
                algorithm_service.os.environ,
                {"DSVLM_SERVICE_API_BASE": "https://example.invalid:9079"},
                clear=True,
            ),
            opener_patch(fake_urlopen),
        ):
            algorithm_service.add_algorithm(
                "普通算法",
                "识别普通事件",
                1,
                token="fake-test-token",
            )

        self.assertEqual(
            captured,
            {
                "themeDataName": "普通算法",
                "text": "识别普通事件",
                "type": 1,
            },
        )

    def test_add_validates_required_fields_and_type(self):
        cases = [
            ("", "text", 1),
            ("name", "   ", 1),
            ("name", "text", 3),
        ]
        for name, text, algorithm_type in cases:
            with self.subTest(name=name, text=text, algorithm_type=algorithm_type):
                with self.assertRaises(ValueError):
                    algorithm_service.add_algorithm(
                        name,
                        text,
                        algorithm_type,
                        token="fake-test-token",
                    )

    def test_list_uses_get_path_without_request_body(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = request.data
            captured["authorization"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return FakeResponse({"code": 0, "msg": "success", "data": [1, 2]})

        with (
            mock.patch.dict(
                algorithm_service.os.environ,
                {
                    "DSVLM_SERVICE_API_BASE": "https://example.invalid:9079/",
                    "DSVLM_SERVICE_TOKEN": "fake-list-token",
                    "DSVLM_SERVICE_TIMEOUT": "9",
                },
                clear=True,
            ),
            opener_patch(fake_urlopen),
        ):
            result = algorithm_service.get_all_algorithms()

        self.assertEqual(captured["url"], "https://example.invalid:9079/v1/api/themeData/all")
        self.assertEqual(captured["method"], "GET")
        self.assertIsNone(captured["body"])
        self.assertEqual(captured["authorization"], "fake-list-token")
        self.assertEqual(captured["timeout"], 9)
        self.assertEqual(result["data"], [1, 2])

    def test_explicit_timeout_takes_precedence_over_environment_default(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["timeout"] = timeout
            return FakeResponse({"code": 0, "data": []})

        with (
            mock.patch.dict(
                algorithm_service.os.environ,
                {
                    "DSVLM_SERVICE_API_BASE": "https://example.invalid:9079",
                    "DSVLM_SERVICE_TIMEOUT": "99",
                },
                clear=True,
            ),
            opener_patch(fake_urlopen),
        ):
            algorithm_service.get_all_algorithms(
                token="fake-test-token",
                timeout=7,
            )

        self.assertEqual(captured["timeout"], 7)

    def test_timeout_rejects_nonfinite_and_nonpositive_values(self):
        def unexpected_network(*args, **kwargs):
            self.fail("invalid timeout must fail before network access")

        with (
            mock.patch.dict(
                algorithm_service.os.environ,
                {"DSVLM_SERVICE_API_BASE": "https://example.invalid:9079"},
                clear=True,
            ),
            opener_patch(unexpected_network),
        ):
            for timeout in ("nan", "inf", 0, -1):
                with self.subTest(timeout=timeout):
                    with self.assertRaises(algorithm_service.ServiceError):
                        algorithm_service.get_all_algorithms(
                            token="fake-test-token",
                            timeout=timeout,
                        )

    def test_plain_http_is_rejected_without_explicit_opt_in(self):
        fake_token = "fake-insecure-secret"

        def unexpected_network(*args, **kwargs):
            self.fail("plain HTTP must fail before network access")

        with (
            mock.patch.dict(
                algorithm_service.os.environ,
                {"DSVLM_SERVICE_API_BASE": "http://example.invalid:9079"},
                clear=True,
            ),
            opener_patch(unexpected_network),
        ):
            with self.assertRaises(algorithm_service.ServiceError) as error:
                algorithm_service.get_all_algorithms(token=fake_token)

        self.assertNotIn(fake_token, str(error.exception))

    def test_private_env_can_override_service_base_and_timeout(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return FakeResponse({"code": 0, "data": []})

        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "DSVLM_SERVICE_API_BASE=http://private.invalid:9079/",
                        "DSVLM_SERVICE_TOKEN=fake-private-token",
                        "DSVLM_SERVICE_TIMEOUT=17",
                        "DSVLM_SERVICE_ALLOW_INSECURE_HTTP=true",
                    ]
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.dict(algorithm_service.os.environ, {}, clear=True),
                mock.patch.object(algorithm_service, "DEFAULT_ENV_PATH", env_path),
                opener_patch(fake_urlopen),
            ):
                algorithm_service.get_all_algorithms()

        self.assertEqual(captured["url"], "http://private.invalid:9079/v1/api/themeData/all")
        self.assertEqual(captured["timeout"], 17)

    def test_cli_list_outputs_json(self):
        response = FakeResponse({"code": 0, "msg": "success", "data": ["algorithm"]})
        output = io.StringIO()

        with (
            mock.patch.dict(
                algorithm_service.os.environ,
                {
                    "DSVLM_SERVICE_API_BASE": "https://example.invalid:9079",
                    "DSVLM_SERVICE_TOKEN": "fake-cli-token",
                },
                clear=True,
            ),
            opener_patch(response),
            redirect_stdout(output),
        ):
            exit_code = algorithm_service.cli(["--list"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"code": 0, "msg": "success", "data": ["algorithm"]},
        )

    def test_cli_error_is_nonzero_and_masks_token(self):
        fake_token = "fake-cli-secret"
        error_output = io.StringIO()
        response = FakeResponse({"code": 401, "msg": fake_token})

        with (
            mock.patch.dict(
                algorithm_service.os.environ,
                {
                    "DSVLM_SERVICE_API_BASE": "https://example.invalid:9079",
                    "DSVLM_SERVICE_TOKEN": fake_token,
                },
                clear=True,
            ),
            opener_patch(response),
            redirect_stderr(error_output),
        ):
            exit_code = algorithm_service.cli(["--list"])

        self.assertNotEqual(exit_code, 0)
        self.assertNotIn(fake_token, error_output.getvalue())
        self.assertFalse(json.loads(error_output.getvalue())["ok"])

    def test_cli_add_accepts_required_flags(self):
        captured = {}
        output = io.StringIO()

        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            return FakeResponse({"code": 0, "data": {"id": 8}})

        with (
            mock.patch.dict(
                algorithm_service.os.environ,
                {
                    "DSVLM_SERVICE_API_BASE": "https://example.invalid:9079",
                    "DSVLM_SERVICE_TOKEN": "fake-cli-token",
                },
                clear=True,
            ),
            opener_patch(fake_urlopen),
            redirect_stdout(output),
        ):
            exit_code = algorithm_service.cli(
                [
                    "--add",
                    "--name",
                    "CLI 算法",
                    "--text",
                    "CLI 描述",
                    "--type",
                    "2",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            captured,
            {"themeDataName": "CLI 算法", "text": "CLI 描述", "type": 2},
        )
        self.assertEqual(json.loads(output.getvalue())["data"], {"id": 8})


if __name__ == "__main__":
    unittest.main()
