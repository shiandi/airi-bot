from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""

    database_url: str = "postgresql+asyncpg://airi:airi@192.168.1.101:23001/airi_bot"
    """PostgreSQL 连接地址，格式: postgresql+asyncpg://user:password@host:port/dbname"""

    dedup_hamming_threshold: int = 8
    """dHash 去重阈值：汉明距离 ≤ 该值时视为重复图片（0=完全相同，默认8可容忍小幅度裁剪和模糊）"""

    random_image_cooldown: int = 10
    """随机图片命令冷却时间（秒）"""
