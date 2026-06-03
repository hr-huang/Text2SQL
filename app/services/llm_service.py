# app/services/llm_service.py

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class LLMService:
    # 全局 token 统计
    _total_input_tokens = 0
    _total_output_tokens = 0
    _call_count = 0
    _total_prompt_chars = 0

    def __init__(self):
        # 读取当前激活的预设
        preset = os.getenv("LLM_PRESET", "deepseek_v4_flash").upper()
        api_key = os.getenv(f"{preset}_KEY", os.getenv("LLM_API_KEY"))
        base_url = os.getenv(f"{preset}_URL", os.getenv("LLM_BASE_URL"))
        self.model = os.getenv(f"{preset}_MODEL", os.getenv("LLM_MODEL", "deepseek-v4-flash"))

        if not api_key:
            raise RuntimeError("请先在 .env 文件中配置 API Key")

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=120.0,
        )

        # 思考模式配置（仅 DeepSeek V4 系列支持，Gemini/Kimi/MiMo 会报错）
        self.extra_body = {}
        if os.getenv("LLM_THINKING") == "enabled" and "deepseek" in self.model.lower():
            self.extra_body["thinking"] = {"type": "enabled"}
            self.extra_body["reasoning_effort"] = os.getenv("LLM_REASONING_EFFORT", "medium")

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        kwargs = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        response = self.client.chat.completions.create(**kwargs)

        # 累计 token
        if hasattr(response, "usage") and response.usage:
            LLMService._total_input_tokens += response.usage.prompt_tokens or 0
            LLMService._total_output_tokens += response.usage.completion_tokens or 0
        LLMService._call_count += 1
        LLMService._total_prompt_chars += len(system_prompt) + len(user_prompt)

        content = response.choices[0].message.content
        if not content:
            raise ValueError("大模型返回内容为空")
        return self._loads_json(content, context="chat completion")

    def generate_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict],
        tool_choice: str = "auto",
    ) -> dict[str, Any]:
        """Function Calling 模式：LLM 返回 tool_call 而非普通 JSON"""
        kwargs = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            tools=tools,
            tool_choice=tool_choice,
        )
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        response = self.client.chat.completions.create(**kwargs)

        if hasattr(response, "usage") and response.usage:
            LLMService._total_input_tokens += response.usage.prompt_tokens or 0
            LLMService._total_output_tokens += response.usage.completion_tokens or 0
        LLMService._call_count += 1
        LLMService._total_prompt_chars += len(system_prompt) + len(user_prompt)

        msg = response.choices[0].message
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            return {
                "tool_name": tc.function.name,
                "arguments": self._loads_json(
                    tc.function.arguments,
                    context=f"tool arguments for {tc.function.name}",
                ),
            }
        return {"tool_name": None, "content": msg.content or ""}

    @staticmethod
    def _loads_json(raw: str, context: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            snippet = raw[:500].replace("\n", "\\n")
            raise ValueError(
                f"Failed to parse {context} as JSON: {exc}. Raw prefix: {snippet}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected {context} to be a JSON object, got {type(parsed).__name__}")
        return parsed

    @classmethod
    def reset_stats(cls):
        cls._total_input_tokens = 0
        cls._total_output_tokens = 0
        cls._call_count = 0
        cls._total_prompt_chars = 0

    @classmethod
    def get_stats(cls) -> dict:
        return {
            "calls": cls._call_count,
            "input_tokens": cls._total_input_tokens,
            "output_tokens": cls._total_output_tokens,
            "total_tokens": cls._total_input_tokens + cls._total_output_tokens,
            "prompt_chars": cls._total_prompt_chars,
        }
