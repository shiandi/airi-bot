from pydantic import BaseModel


class Config(BaseModel):
    cooldown: int = 10
