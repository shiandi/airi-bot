from datetime import datetime

from sqlalchemy import String, DateTime, BigInteger, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ImageRecord(Base):
    __tablename__ = "image_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stored_name: Mapped[str] = mapped_column(String(256))
    upload_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    uploader_qq: Mapped[int] = mapped_column(BigInteger)
    dhash: Mapped[str] = mapped_column(String(64))
