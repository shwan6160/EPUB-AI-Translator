from abc import ABC, abstractmethod

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
