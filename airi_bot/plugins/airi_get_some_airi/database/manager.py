from nonebot import logger
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from .model import Base


class DatabaseManager:
    def __init__(self, database_url: str) -> None:
        logger.info("[DB] 正在创建数据库引擎")
        self._database_url = database_url
        self._engine = create_async_engine(database_url, echo=False)
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False
        )
        logger.info("[DB] 数据库引擎创建完成")

    async def init_db(self) -> None:
        logger.info("[DB] 正在初始化数据库表结构...")
        try:
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("[DB] 数据库表结构初始化完成")
        except Exception:
            logger.exception("[DB ERROR] 数据库表结构初始化失败")
            raise

    def session(self) -> AsyncSession:
        return self._sessionmaker()

    async def close(self) -> None:
        logger.info("[DB] 正在关闭数据库连接...")
        await self._engine.dispose()
        logger.info("[DB] 数据库连接已关闭")
