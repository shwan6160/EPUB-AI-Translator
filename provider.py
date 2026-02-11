from typing import Optional, Any, Protocol
from dataclasses import dataclass
from abc import ABC, abstractmethod

from google import genai


class ModelConfigLike(Protocol):
    temperature: float | None
    top_p: float | None
    top_k: int | float | None


@dataclass
class ModelConfig:
    temperature: float
    top_p: float
    top_k: int
    system_prompt: Optional[str] = None


class ModelProvider(ABC):
    def __init__(self, config: ModelConfigLike):
        self.config = config
    
    @abstractmethod
    def generate_content(self, user_prompt: str) -> str:
        """
        Text Generation Function. 
        """
        return str()


class GoogleGenai(ModelProvider):

    @staticmethod
    def list_available_models(api_key: str) -> list[str]:
        client = genai.Client(api_key=api_key)
        models = []
        for m in client.models.list():
            models.append(m.name)
        return models

    def __init__(self, config: genai.types.GenerateContentConfig, api_key: str, model_name: str = "gemini-3-flash"):
        super().__init__(config)

        if not api_key:
            raise ValueError("API 키가 설정되지 않았습니다.")

        self.api_key = api_key
        self.model_name = model_name
    
    def generate_content(self, user_prompt: str) -> str:
        client = genai.Client(api_key=self.api_key)

        response = client.models.generate_content(
            model = self.model_name,
            contents = genai.types.Part.from_text(text = user_prompt),
            config = self.config
            )

        if not response or not response.text:
            raise ValueError("모델로부터 유효한 응답을 받지 못했습니다.")

        return response.text
