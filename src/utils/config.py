from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    bot_token: str
    database_url: str
    openai_api_key: str
    admin_ids: str = ""

    class Config:
        env_file = ".env"

    @property
    def admin_ids_list(self) -> List[int]:
        if not self.admin_ids:
            return []
        return [int(x.strip()) for x in self.admin_ids.split(",")]

settings = Settings()
