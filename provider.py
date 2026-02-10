from typing import Optional
from abc import ABC, abstractmethod

from google import genai

class ModelConfig:
    system_prompt: Optional[str] = None
    temperature: float
    top_p: float
    top_k: int
    api_key: Optional[str] = None


class ModelProvider(ABC):
    def __init__(self, config: ModelConfig):
        self.config = config
    
    @abstractmethod
    def generate_content(self, user_prompt: str) -> str:
        """
        실제 텍스트 생성 로직. 
        """
        return str()

    @property
    def api_key(self) -> Optional[str]:
        return self.config.api_key


class GoogleGenai(ModelProvider):

    @staticmethod
    def list_available_models(api_key: str) -> list[str]:
        client = genai.Client(api_key=api_key)
        models = []
        for m in client.models.list():
            models.append(m.name)
        return models


    def __init__(self, config: ModelConfig, model_name: str = "gemini-3-flash"):
        super().__init__(config)

        if not self.config.api_key:
            raise ValueError("API 키가 설정되지 않았습니다.")

        self.model_name = model_name
        
    
    def generate_content(self, user_prompt: str) -> str:
        prompt = ""

        if not self.config.system_prompt:
            prompt = user_prompt
        else:
            prompt = f"{self.config.system_prompt}\n\n{user_prompt}\n"

        client = genai.Client(api_key=self.config.api_key)

        response = client.models.generate_content(
            model = self.model_name,
            contents = genai.types.Part.from_text(text = prompt),
            config = genai.types.GenerateContentConfig(
                temperature = self.config.temperature,
                top_p = self.config.top_p,
                top_k = self.config.top_k
            )
        )
        if not response or not response.text:
            raise ValueError("모델로부터 유효한 응답을 받지 못했습니다.")

        return response.text
