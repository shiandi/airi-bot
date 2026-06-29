from datetime import datetime

from sqlalchemy import String, DateTime, BigInteger, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ImageRecord(Base):
    __tablename__ = "image_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    stored_name: Mapped[str] = mapped_column(String(256))
    """磁盘存储文件名（UUID+扩展名），用于定位文件和显示"""

    upload_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    """上传时间"""

    uploader_qq: Mapped[int] = mapped_column(BigInteger)
    """上传人QQ号"""

    dhash: Mapped[str] = mapped_column(String(64))
    """dHash 感知哈希值（16x16 差异哈希，256位，64字符十六进制）"""
