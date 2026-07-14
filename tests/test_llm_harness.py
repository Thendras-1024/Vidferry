import json
import unittest
import urllib.error

from app.core import llm_harness, llm_prompts


def _response(content, prompt_tokens=10, completion_tokens=5):
    return {
        "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


class LLMHarnessTests(unittest.TestCase):
    def setUp(self):
        self.original_request = llm_harness._request_completion

    def tearDown(self):
        llm_harness._request_completion = self.original_request

    def _call_reply_contract(self):
        return llm_harness.call_json_contract(
            messages=[{"role": "system", "content": "test"}],
            contract_id="agent_reply",
            validator=llm_harness.validate_agent_reply,
            model="test-model",
            api_key="test-key",
            base_url="https://example.test/v1",
            timeout=1,
            temperature=0,
            max_tokens=100,
            prompt_version="test-v1",
        )

    def test_retries_once_when_visible_text_is_english(self):
        responses = iter([
            _response({"answer": "This response is only English."}),
            _response({"answer": "这是修正后的中文回答。"}),
        ])
        payloads = []

        def request(base_url, api_key, timeout, payload):
            payloads.append(payload)
            return next(responses)

        llm_harness._request_completion = request
        result, usage, metadata = self._call_reply_contract()

        self.assertEqual(result["answer"], "这是修正后的中文回答。")
        self.assertEqual(metadata["attemptCount"], 2)
        self.assertEqual(metadata["validationRetries"], 1)
        self.assertEqual(usage["totalTokens"], 30)
        self.assertIn("answer 必须使用简体中文", payloads[1]["messages"][-1]["content"])

    def test_raises_after_second_invalid_result(self):
        llm_harness._request_completion = lambda *args: _response({"answer": "English only."})

        with self.assertRaises(llm_harness.LLMContractError) as context:
            self._call_reply_contract()

        self.assertIn("answer 必须使用简体中文", context.exception.detail)

    def test_falls_back_when_provider_rejects_json_mode(self):
        payloads = []

        def request(base_url, api_key, timeout, payload):
            payloads.append(payload)
            if len(payloads) == 1:
                raise urllib.error.HTTPError("https://example.test", 400, "bad request", {}, None)
            return _response({"answer": "兼容模式下仍可输出中文。"})

        llm_harness._request_completion = request
        result, _, metadata = self._call_reply_contract()

        self.assertEqual(result["answer"], "兼容模式下仍可输出中文。")
        self.assertEqual(metadata["attemptCount"], 1)
        self.assertIn("response_format", payloads[0])
        self.assertNotIn("response_format", payloads[1])

    def _editing_plan(self):
        return {
            "summary": "游客被重庆夜景震撼。",
            "china_view_angle": "外国游客感受到中国城市的立体活力。",
            "title_options": ["老外第一次看到重庆夜景，直接看呆了"],
            "publish_copy": "重庆的夜晚让第一次到访的外国游客惊叹不已。",
            "tags": ["#重庆旅行", "老外看中国"],
            "highlight_segments": [{
                "start": 44,
                "end": 52,
                "type": "visual_awe",
                "reason": "游客的惊叹反应非常直接。",
                "suggested_caption": "他看到重庆夜景后直接愣住",
            }],
            "risk_notes": ["避免使用未经证实的绝对化表述。"],
            "editing_focus": "优先保留游客的表情和城市全景切换。",
        }

    def _editing_plan_with_starts(self, *starts):
        plan = self._editing_plan()
        template = plan["highlight_segments"][0]
        plan["highlight_segments"] = [
            {**template, "start": start, "end": start + 8}
            for start in starts
        ]
        return plan

    def test_editing_contract_normalizes_tags(self):
        result = llm_harness.validate_editing_plan(self._editing_plan(), max_timestamp=60)

        self.assertEqual(result["tags"], ["重庆旅行", "老外看中国"])

    def test_rejects_unknown_fields_but_filters_disallowed_highlight_range(self):
        with_unknown_field = self._editing_plan()
        with_unknown_field["unexpected"] = "额外内容"
        with self.assertRaises(llm_harness.LLMContractError):
            llm_harness.validate_editing_plan(with_unknown_field, max_timestamp=60)

        plan = self._editing_plan()
        plan["risk_notes"].append("注意 fucking 口语")
        result = llm_harness.validate_editing_plan(plan, max_timestamp=60, blocked_ranges=[(44, 52)])

        self.assertEqual(result["highlight_segments"], [])
        self.assertNotIn("注意 fucking 口语", result["risk_notes"])
        self.assertIn("检测到明确粗口，中文字幕将以 * 替换；英文原文字幕与原声保留，请人工审核。", result["risk_notes"])

    def test_editing_contract_filters_bad_candidates_and_keeps_up_to_eight(self):
        plan = self._editing_plan_with_starts(70, 30, 40, 50, 60, 80, 90, 100, 110, 120)
        plan["highlight_segments"][2]["reason"] = "这是 fucking 原话"

        result = llm_harness.validate_editing_plan(
            plan,
            max_timestamp=128,
            blocked_ranges=[(68, 78)],
            minimum_highlights=6,
        )

        self.assertEqual([item["start"] for item in result["highlight_segments"]], [30, 50, 60, 80, 90, 100, 110, 120])

    def test_editing_contract_retries_when_safe_highlights_are_insufficient(self):
        responses = iter([
            _response(self._editing_plan_with_starts(44)),
            _response(self._editing_plan_with_starts(30, 44, 58, 70, 82, 94, 106)),
        ])
        payloads = []

        def request(base_url, api_key, timeout, payload):
            payloads.append(payload)
            return next(responses)

        llm_harness._request_completion = request
        result, _, metadata = llm_harness.call_json_contract(
            messages=[{"role": "system", "content": "test"}],
            contract_id="editing_plan",
            validator=lambda value: llm_harness.validate_editing_plan(value, max_timestamp=120, minimum_highlights=6),
            model="test-model",
            api_key="test-key",
            base_url="https://example.test/v1",
            timeout=1,
            temperature=0,
            max_tokens=1000,
            prompt_version="test-v1",
        )

        self.assertGreaterEqual(len(result["highlight_segments"]), 6)
        self.assertLessEqual(len(result["highlight_segments"]), 8)
        self.assertEqual(metadata["attemptCount"], 2)
        self.assertIn("可用安全高光不足 6 条", payloads[1]["messages"][-1]["content"])

    def test_profanity_redaction_does_not_mask_ordinary_negative_words(self):
        text = "This is fucking terrible, shit. 这也太他妈的糟糕了。"

        self.assertEqual(llm_harness.redact_profanity(text), "This is * terrible, *. 这也太*糟糕了。")
        self.assertFalse(llm_harness.contains_profanity("I hate this terrible traffic，体验很糟糕。"))
        self.assertFalse(llm_harness.contains_profanity("这是妈妈的旅行记录。"))

    def test_guard_requires_neutral_chinese_evidence(self):
        result = llm_harness.validate_guard_result({
            "issues": [{
                "category": "profanity",
                "severity": "medium",
                "evidence": "检测到粗俗表达",
                "reason": "原文包含粗口，可能影响平台审核。",
                "suggestion": "使用打码字幕或替换为中性表达。",
                "blocking": False,
            }],
            "suggestedEdits": {"title": "", "description": "", "tags": []},
        })

        self.assertEqual(result["issues"][0]["evidence"], "检测到粗俗表达")

        with self.assertRaises(llm_harness.LLMContractError):
            llm_harness.validate_guard_result({
                "issues": [{
                    "category": "profanity", "severity": "medium", "evidence": "Fucking big",
                    "reason": "原文包含粗口，可能影响平台审核。", "suggestion": "使用中性表达。", "blocking": False,
                }],
                "suggestedEdits": {"title": "", "description": "", "tags": []},
            })

    def test_rejects_mixed_language_and_profanity_in_display_text(self):
        with self.assertRaises(llm_harness.LLMContractError):
            llm_harness.validate_agent_reply({"answer": "他看到重庆后说 This is wild"})
        with self.assertRaises(llm_harness.LLMContractError):
            llm_harness.validate_agent_reply({"answer": "这是 Fucking big 的原话"})

    def test_prompts_include_chinese_and_first_thirty_seconds_rules(self):
        prompt = llm_prompts.editing_analysis_system_prompt()
        user_prompt = llm_prompts.build_editing_analysis_prompt({}, "[00:30-00:38] test")
        self.assertIn("角色与职责", prompt)
        self.assertIn("简体中文", prompt)
        self.assertIn("30 秒", prompt)
        self.assertIn("明确脏话", prompt)
        self.assertIn("目标生成 6-8 个", user_prompt)


if __name__ == "__main__":
    unittest.main()
