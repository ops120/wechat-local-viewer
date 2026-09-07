from typing import Iterator
from .base import LLMClient
import openai


class OpenAICompatClient(LLMClient):
    """OpenAI 兼容协议客户端"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

        if not base_url:
            raise ValueError("base_url 不能为空")
        if not api_key:
            raise ValueError("api_key 不能为空")
        if not model:
            raise ValueError("model 不能为空")

        self.client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=60.0
        )

    def stream(self, messages: list[dict]) -> Iterator[str]:
        """流式返回响应"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=2000
            )

            for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content
        except Exception as e:
            raise Exception(f"LLM 调用失败: {str(e)}")

    def chat(self, messages: list[dict]) -> str:
        """非流式返回响应"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise Exception(f"LLM 调用失败: {str(e)}")