import unittest
import urllib.error
from unittest.mock import Mock, patch

import app.config as config


class LLMConfigStatusTests(unittest.TestCase):
    def setUp(self):
        self.original = (
            config.LLM_API_KEY,
            config.LLM_BASE_URL,
            config.LLM_MODEL,
            config.LLM_TIMEOUT,
            config._LLM_CONFIG_STATUS_CACHE,
        )
        config._LLM_CONFIG_STATUS_CACHE = None

    def tearDown(self):
        (
            config.LLM_API_KEY,
            config.LLM_BASE_URL,
            config.LLM_MODEL,
            config.LLM_TIMEOUT,
            config._LLM_CONFIG_STATUS_CACHE,
        ) = self.original

    def test_missing_api_key_skips_probe(self):
        config.LLM_API_KEY = ""
        config.LLM_BASE_URL = "https://example.test/v1"
        config.LLM_MODEL = "demo-model"

        with patch("app.config.urllib.request.urlopen") as urlopen:
            status = config.get_llm_config_status()

        self.assertFalse(status["ready"])
        self.assertEqual(status["missing"], ["LLM_API_KEY"])
        urlopen.assert_not_called()

    def test_missing_base_url_and_model(self):
        config.LLM_API_KEY = "sk-test"
        config.LLM_BASE_URL = ""
        config.LLM_MODEL = ""

        status = config.get_llm_config_status()

        self.assertFalse(status["ready"])
        self.assertEqual(status["missing"], ["LLM_BASE_URL", "LLM_MODEL"])

    def test_probe_success_returns_ready(self):
        config.LLM_API_KEY = "sk-test"
        config.LLM_BASE_URL = "https://example.test/v1"
        config.LLM_MODEL = "demo-model"
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        response.read.return_value = b'{"choices":[{"message":{"content":"OK"}}]}'

        with patch("app.config.urllib.request.urlopen", return_value=response):
            status = config.get_llm_config_status()

        self.assertTrue(status["ready"])
        self.assertEqual(status["missing"], [])

    def test_probe_failure_reports_unavailable_without_missing(self):
        config.LLM_API_KEY = "sk-test"
        config.LLM_BASE_URL = "https://example.test/v1"
        config.LLM_MODEL = "demo-model"
        error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            401,
            "Unauthorized",
            hdrs=None,
            fp=None,
        )

        with patch("app.config.urllib.request.urlopen", side_effect=error):
            status = config.get_llm_config_status()

        self.assertFalse(status["ready"])
        self.assertEqual(status["missing"], [])
        self.assertIn("模型接口不可用", status["message"])

    def test_status_is_cached(self):
        config.LLM_API_KEY = "sk-test"
        config.LLM_BASE_URL = "https://example.test/v1"
        config.LLM_MODEL = "demo-model"
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        response.read.return_value = b'{"choices":[{"message":{"content":"OK"}}]}'

        with patch("app.config.urllib.request.urlopen", return_value=response) as urlopen:
            first = config.get_llm_config_status()
            second = config.get_llm_config_status()

        self.assertTrue(first["ready"])
        self.assertIs(first, second)
        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
