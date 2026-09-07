from abc import ABC, abstractmethod
from typing import Iterator


class LLMClient(ABC):
    """LLM 客户端接口"""

    @abstractmethod
    def stream(self, messages: list[dict]) -> Iterator[str]:
        """流式返回响应"""
        pass

    @abstractmethod
    def chat(self, messages: list[dict]) -> str:
        """非流式返回响应"""
        pass