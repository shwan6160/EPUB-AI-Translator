from abc import ABC, abstractmethod
from typing import Any
import time

import httpx
from pydantic import BaseModel, ConfigDict
from google import genai


class ModelConfig(BaseModel):
    """프로바이더 공통 설정"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    api_key: str
    model_name: str


class ModelProvider(ABC):
    def __init__(self, config: ModelConfig):
        self.config = config

    @abstractmethod
    def generate_content(self, user_prompt: str) -> str:
        """
        Text Generation Function.
        """
        return str()


class GoogleGenaiConfig(ModelConfig):
    """Google GenAI 전용 설정"""
    model_name: str = "gemini-3-flash"
    generation_config: genai.types.GenerateContentConfig


class GoogleGenai(ModelProvider):

    @staticmethod
    def list_available_models(api_key: str) -> list[str]:
        client = genai.Client(api_key=api_key)
        return [m.name for m in client.models.list()]

    def __init__(self, config: GoogleGenaiConfig):
        super().__init__(config)
        self.config: GoogleGenaiConfig = config

    def generate_content(self, user_prompt: str) -> str:
        client = genai.Client(api_key=self.config.api_key)

        response = client.models.generate_content(
            model=self.config.model_name,
            contents=genai.types.Part.from_text(text=user_prompt),
            config=self.config.generation_config,
        )

        if not response or not response.text:
            raise ValueError("모델로부터 유효한 응답을 받지 못했습니다.")

        return response.text


class OpenRouterConfig(ModelConfig):
    """OpenRouter 전용 설정"""
    model_name: str = "moonshotai/kimi-k2.5"
    base_url: str = "https://openrouter.ai/api/v1"
    system_prompt: str | None = None
    temperature: float = 0.2
    top_p: float = 0.8
    max_tokens: int | None = None
    timeout: float = 120.0
    connect_timeout: float = 15.0
    write_timeout: float = 60.0
    read_timeout: float = 120.0
    retry_count: int = 2
    retry_backoff_seconds: float = 1.5
    app_name: str | None = "EPUB-AI-Translator"
    app_url: str | None = None
    response_format: dict[str, Any] | None = None


class OpenRouter(ModelProvider):

    @staticmethod
    def list_available_models(api_key: str, base_url: str = "https://openrouter.ai/api/v1") -> list[str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{base_url}/models", headers=headers)
            response.raise_for_status()
            data = response.json()

        models = data.get("data", []) if isinstance(data, dict) else []
        return [m.get("id", "") for m in models if isinstance(m, dict) and m.get("id")]

    def __init__(self, config: OpenRouterConfig):
        super().__init__(config)
        self.config: OpenRouterConfig = config

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        if self.config.app_url:
            headers["HTTP-Referer"] = self.config.app_url
        if self.config.app_name:
            headers["X-Title"] = self.config.app_name
        return headers

    def _build_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            timeout=self.config.timeout,
            connect=self.config.connect_timeout,
            write=self.config.write_timeout,
            read=self.config.read_timeout,
        )

    def generate_content(self, user_prompt: str) -> str:
        messages: list[dict[str, str]] = []
        if self.config.system_prompt:
            messages.append({"role": "system", "content": self.config.system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
        }
        if self.config.max_tokens is not None:
            payload["max_tokens"] = self.config.max_tokens
        if self.config.response_format is not None:
            payload["response_format"] = self.config.response_format

        last_error: Exception | None = None
        max_attempts = self.config.retry_count + 1

        for attempt in range(1, max_attempts + 1):
            try:
                with httpx.Client(timeout=self._build_timeout()) as client:
                    response = client.post(
                        f"{self.config.base_url}/chat/completions",
                        headers=self._build_headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                break
            except httpx.TimeoutException as e:
                last_error = e
                if attempt >= max_attempts:
                    raise TimeoutError(
                        "OpenRouter 응답 대기 시간이 초과되었습니다. "
                        f"read_timeout={self.config.read_timeout}s, 시도={max_attempts}"
                    ) from e
                time.sleep(self.config.retry_backoff_seconds * attempt)
            except httpx.HTTPError as e:
                last_error = e
                if attempt >= max_attempts:
                    raise ConnectionError(
                        "OpenRouter 요청에 실패했습니다. "
                        f"{type(e).__name__}: {e}"
                    ) from e
                time.sleep(self.config.retry_backoff_seconds * attempt)
        else:
            raise RuntimeError(f"OpenRouter 요청 실패: {last_error}")

        try:
            choices = data.get("choices", [])
            first_choice = choices[0]
            message = first_choice.get("message", {})
            content = message.get("content", "")
        except (IndexError, AttributeError, TypeError) as e:
            raise ValueError(f"OpenRouter 응답 파싱에 실패했습니다: {e}") from e

        if isinstance(content, list):
            text_parts = [c.get("text", "") for c in content if isinstance(c, dict)]
            content = "".join(text_parts)

        if not isinstance(content, str) or not content.strip():
            raise ValueError("OpenRouter 모델로부터 유효한 텍스트 응답을 받지 못했습니다.")

        return content
