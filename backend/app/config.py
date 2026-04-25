from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    database_url: str = "sqlite+aiosqlite:///./trace911.db"
    db_echo: bool = False

    ai_coustics_api_key: str = ""
    aic_sdk_license: str = ""          # AIC_SDK_LICENSE — direct SDK path
    gradium_api_key: str = ""          # Gradium STT WebSocket API key
    gladia_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    aic_model: str = "QUAIL_VF_L"
    aic_model_id: str = "quail-vf-2.1-l-16khz"   # direct SDK model ID
    aic_model_dir: str = "./models"               # where the SDK caches the model
    aic_enhancement_level: float = 0.8
    aic_vad_sensitivity: float = 6.0
    aic_vad_speech_hold: float = 0.03
    aic_vad_min_speech: float = 0.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
