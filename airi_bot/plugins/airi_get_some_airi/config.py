from pydantic import BaseModel


class Config(BaseModel):
    database_url: str = ""
    dedup_hamming_threshold: int = 10
    enable_upload: bool = True
    random_image_cooldown: int = 10
    recent_exclude_ratio: float = 0.5


def resolve_database_url(raw_url: str) -> str:
    if raw_url:
        return raw_url
    return "postgresql+asyncpg://airi:airi@192.168.1.101:23001/airi_bot"
