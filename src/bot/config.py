from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict



class PostgresConfig(BaseModel):
    """
    Configuration settings for connecting to a PostgreSQL database.

    Attributes:
        db: The name of the PostgreSQL database.
        user: The username for connecting to the database.
        password: The password for the database user.
        host: The hostname or IP address of the PostgreSQL server. Defaults to "db".
        port: The port number for the PostgreSQL server. Defaults to 5432.
    """
    db: SecretStr
    user: SecretStr
    password: SecretStr
    host: str = "db"
    port: int = 5432

class DjangoConfig(BaseModel):
    """
    Configuration settings specific to a Django application.

    Attributes:
        key: The Django secret key.
        debug: A boolean indicating whether Django's debug mode should be enabled.
               Defaults to True.
    """
    key: SecretStr
    debug: bool = True

class BotConfig(BaseModel):
    """
    Configuration settings for a Telegram bot.

    Attributes:
        token: The Telegram Bot API token.
    """
    token: SecretStr

class Settings(BaseSettings):
    """
    Main application settings class, aggregating configurations for different components.

    It uses `pydantic-settings` to load values from environment variables
    and/or a .env file. Nested configurations (like `postgres_db`) are
    expected to be defined with an underscore as a delimiter in the environment
    (e.g., `POSTGRES_DB`, `POSTGRES_USER`).

    Attributes:
        postgres: An instance of `PostgresConfig` holding database connection details.
        django: An instance of `DjangoConfig` holding Django-specific settings.
        bot: An instance of `BotConfig` holding Telegram bot settings.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="_"
    )

    postgres: PostgresConfig
    django: DjangoConfig
    bot: BotConfig

settings = Settings()
