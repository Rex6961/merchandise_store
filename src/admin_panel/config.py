from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict



class PostgresConfig(BaseModel):
    db: SecretStr
    user: SecretStr
    password: SecretStr
    host: str = "db"
    port: int = 5432

class DjangoConfig(BaseModel):
    key: SecretStr
    debug: bool = True

class BotConfig(BaseModel):
    token: SecretStr

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="_"
    )

    postgres: PostgresConfig
    django: DjangoConfig
    bot: BotConfig

settings = Settings()
