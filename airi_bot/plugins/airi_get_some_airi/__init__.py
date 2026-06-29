import uuid
from io import BytesIO
from pathlib import Path
from time import time as _time

import aiofiles  # type: ignore[import-untyped]
from nonebot import get_bot, get_driver, get_plugin_config, on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.matcher import Matcher
from PIL import Image
from imagehash import dhash

from .config import Config
from .database import DatabaseManager, ImageRecord, Base

__plugin_meta__ = PluginMetadata(
    name="airi_get_some_airi",
    description="QQ 图片上传：发送「上传图片」指令进入上传模式，持续发送图片保存，输入「退出」结束",
    usage="发送「上传图片」进入模式，然后每次发送一张图片，发送「退出」结束",
    config=Config,
)

config = get_plugin_config(Config)

from nonebot import logger  # noqa: E402
logger.info(f"Database URL: {config.database_url}")

db_manager = DatabaseManager(config.database_url)
_image_dir: Path | None = None

_driver = get_driver()


@_driver.on_startup
async def _init_database() -> None:
    await db_manager.init_db()
    await _migrate_id_column_type()
    await _sync_images_with_db()


@_driver.on_shutdown
async def _shutdown_database() -> None:
    await db_manager.close()


async def _migrate_id_column_type() -> None:
    """对比模型与数据库表结构，不一致则删表重建。"""
    from sqlalchemy import text  # noqa: PLC0415
    from .database.model import ImageRecord  # noqa: PLC0415

    model_columns = {c.name for c in ImageRecord.__table__.columns}
    model_columns.discard("id")  # 跳过 id，只看普通列

    async with db_manager._engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'image_records'"
            )
        )
        db_columns = {row[0] for row in result}

    if model_columns.issubset(db_columns):
        return  # 模型列都在，结构匹配

    logger.info("迁移: 重建 image_records 表（结构与模型不匹配）")
    async with db_manager._engine.connect() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS image_records CASCADE"))
        await conn.commit()

    async with db_manager._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _sync_images_with_db() -> None:
    """确保 images 目录与数据库记录一致：库有盘无则删记录，盘有库无则删文件。"""
    from sqlalchemy import select, delete  # noqa: PLC0415

    image_dir = _ensure_image_dir()
    disk_files = {f.name for f in image_dir.iterdir() if f.is_file()}

    async with db_manager.session() as session:
        result = await session.execute(select(ImageRecord))
        db_names = {r.stored_name for r in result.scalars()}

    # 数据库有、磁盘没有 → 删记录
    orphan_records = db_names - disk_files
    if orphan_records:
        async with db_manager.session() as session:
            await session.execute(
                delete(ImageRecord).where(
                    ImageRecord.stored_name.in_(orphan_records)
                )
            )
            await session.commit()
        logger.info(f"清理 {len(orphan_records)} 条孤立记录（文件已不存在）")

    # 磁盘有、数据库没有 → 删文件
    orphan_files = disk_files - db_names
    for name in orphan_files:
        (image_dir / name).unlink()
    if orphan_files:
        logger.info(f"清理 {len(orphan_files)} 个孤立文件（无对应记录）")


def _ensure_image_dir() -> Path:
    global _image_dir
    if _image_dir is None:
        _image_dir = Path(__file__).parent / "images"
        _image_dir.mkdir(parents=True, exist_ok=True)
    return _image_dir


def _compute_dhash(image_bytes: bytes) -> str:
    """计算图片的16x16 dHash，返回十六进制字符串。"""
    img = Image.open(BytesIO(image_bytes)).convert("L")
    h = dhash(img, hash_size=16)
    return str(h)


async def _find_duplicate(session, new_dhash_str: str) -> ImageRecord | None:
    """遍历已有记录，查找汉明距离 ≤ 阈值的重复图片。"""
    from sqlalchemy import select  # noqa: PLC0415
    from imagehash import hex_to_hash  # noqa: PLC0415

    new_hash = hex_to_hash(new_dhash_str)
    result = await session.execute(select(ImageRecord))
    for record in result.scalars():
        if not record.dhash:
            continue
        distance = new_hash - hex_to_hash(record.dhash)
        if distance <= config.dedup_hamming_threshold:
            return record
    return None


async def _save_image(
    file_name: str, url: str | None, uploader_qq: int
) -> str:
    bot = get_bot()
    resp = await bot.get_image(file=file_name)

    image_bytes = resp.get("file") or resp.get("data")
    if isinstance(image_bytes, str):
        if image_bytes.startswith("base64://"):
            import base64  # noqa: PLC0415
            image_bytes = base64.b64decode(image_bytes[8:])
        elif (p := Path(image_bytes)).is_file():
            image_bytes = p.read_bytes()
        else:
            image_bytes = None

    if not image_bytes:
        if url:
            import httpx  # noqa: PLC0415
            async with httpx.AsyncClient() as client:
                r = await client.get(url)
                if r.status_code != 200:
                    msg = f"URL下载失败，状态码: {r.status_code}"
                    raise ValueError(msg)
                image_bytes = r.content
        else:
            msg = f"获取图片失败: {file_name}"
            raise ValueError(msg)

    if isinstance(image_bytes, str):
        image_bytes = image_bytes.encode()

    dhash_str = _compute_dhash(image_bytes)

    async with db_manager.session() as session:
        dup = await _find_duplicate(session, dhash_str)
        if dup is not None:
            msg = (
                f"图片与已上传的图片重复（汉明距离 ≤ {config.dedup_hamming_threshold}）\n"
                f"重复文件: {dup.stored_name}"
            )
            raise ValueError(msg)

        ext = Path(file_name).suffix or ".jpg"
        new_name = uuid.uuid4().hex + ext
        dest = _ensure_image_dir() / new_name

        async with aiofiles.open(str(dest), "wb") as dst:
            await dst.write(image_bytes)

        record = ImageRecord(
            stored_name=new_name,
            uploader_qq=uploader_qq,
            dhash=dhash_str,
        )
        session.add(record)
        await session.commit()

    return new_name


upload_image = on_command("上传图片", block=True)


@upload_image.handle()
async def handle_command(matcher: Matcher, event: MessageEvent) -> None:
    if event.message_type != "private":
        await matcher.finish("请私聊发送此指令")
    await matcher.send("已进入图片上传模式，请一次发送一张图片。输入「退出」结束。")


@upload_image.got("img")
async def got_image(matcher: Matcher, event: MessageEvent) -> None:
    raw_msg = event.message.extract_plain_text().strip()
    if raw_msg in ("退出", "exit", "quit"):
        await matcher.finish("已退出图片上传模式")

    image_segments = event.message["image"]
    if not image_segments:
        await matcher.reject("请发送一张图片，或输入「退出」结束")

    file_name = image_segments[0].data["file"]
    url = image_segments[0].data.get("url")

    try:
        new_name = await _save_image(file_name, url, event.user_id)
    except ValueError as e:
        await matcher.reject(f"{e}\n请重试，或输入「退出」结束")

    await matcher.reject(f"已保存: {new_name}\n继续发送图片，或输入「退出」结束")


_last_random_time = 0.0

random_image = on_command("来点桃", block=True)


@random_image.handle()
async def handle_random_image(matcher: Matcher) -> None:
    global _last_random_time
    now = _time()
    if now - _last_random_time < config.random_image_cooldown:
        remaining = int(config.random_image_cooldown - (now - _last_random_time))
        await matcher.finish(f"冷却中，请 {remaining} 秒后再试")

    from sqlalchemy import select, func  # noqa: PLC0415

    async with db_manager.session() as session:
        count = (await session.execute(select(func.count(ImageRecord.id)))).scalar()
        if count == 0:
            await matcher.finish("暂无图片")

        offset = int((await session.execute(func.random())).scalar() * count)
        record = (
            await session.execute(
                select(ImageRecord).offset(offset).limit(1)
            )
        ).scalar()

    _last_random_time = now

    from nonebot.adapters.onebot.v11 import MessageSegment  # noqa: PLC0415
    img_path = _ensure_image_dir() / record.stored_name
    await matcher.finish(MessageSegment.image(img_path))
