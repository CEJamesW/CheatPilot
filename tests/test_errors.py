import unittest

from cheatpilot.errors import is_llm_malformed_response_error, is_llm_rate_limit_error, user_facing_error


class ErrorFormattingTest(unittest.TestCase):
    def test_llm_error_says_no_local_fallback(self) -> None:
        message = user_facing_error(RuntimeError("LLM tool-use request failed: timed out"))

        self.assertIn("LLM 请求失败", message)
        self.assertIn("没有执行本地规则兜底", message)

    def test_llm_rate_limit_error_is_detected(self) -> None:
        error = RuntimeError("LLM tool-use request failed: HTTP Error 429: Too Many Requests")

        self.assertTrue(is_llm_rate_limit_error(error))

    def test_llm_malformed_response_error_is_user_facing(self) -> None:
        error = RuntimeError("LLM 返回格式无效：缺少 choices[0].message")

        self.assertTrue(is_llm_malformed_response_error(error))
        message = user_facing_error(error)
        self.assertIn("LLM 响应格式异常", message)
        self.assertIn("choices[0].message", message)


if __name__ == "__main__":
    unittest.main()
