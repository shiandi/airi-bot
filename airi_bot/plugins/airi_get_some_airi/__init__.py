import json
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from time import time as _time

import aiofiles  # type: ignore[import-untyped]
from nonebot import get_bot, get_driver, get_plugin_config, on_command, on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.matcher import Matcher
from nonebot.rule import fullmatch
from PIL import Image
from imagehash import dhash

from .config import Config, resolve_database_url
from .database import DatabaseManager, ImageRecord, Base

__plugin_meta__ = PluginMetadata(
    name="airi_get_some_airi",
    description="QQ 图片上传：发送「上传图片」指令进入上传模式，持续发送图片保存，输入「退出」结束",
    usage="发送「上传图片」进入模式，发送图片即可上传，发送「退出」结束",
    config=Config,
)

config = get_plugin_config(Config)
_database_url = resolve_database_url(config.database_url)

from nonebot import logger  # noqa: E402
logger.info("airi_get_some_airi 插件已加载")

db_manager = DatabaseManager(_database_url)
_image_dir: Path | None = None

_driver = get_driver()


@_driver.on_startup
async def _init_database() -> None:
    table_name = f"image_records_{_driver.env}"
    ImageRecord.__tablename__ = table_name
    ImageRecord.__table__.name = table_name
    async with db_manager._engine.begin() as conn:
        await conn.run_sync(ImageRecord.__table__.create, checkfirst=True)
    await _migrate_id_column_type()
    await _sync_images_with_db()


@_driver.on_shutdown
async def _shutdown_database() -> None:
    await db_manager.close()


async def _migrate_id_column_type() -> None:
    from sqlalchemy import text  # noqa: PLC0415
    from .database.model import ImageRecord  # noqa: PLC0415

    model_columns = {c.name for c in ImageRecord.__table__.columns}
    model_columns.discard("id")
    table_name = ImageRecord.__tablename__

    async with db_manager._engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = :tn"
            ),
            {"tn": table_name},
        )
        db_columns = {row[0] for row in result}

    if model_columns.issubset(db_columns):
        return

    logger.info(f"迁移: 重建 {table_name} 表（结构与模型不匹配）")
    async with db_manager._engine.connect() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
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


def _ensure_logs_dir() -> Path:
    """确保 logs 目录存在并返回路径。"""
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


async def _log_random_image(qq: int, img_id: int) -> None:
    """记录一次「来点桃」触发，按天写入日志文件。"""
    now = datetime.now()
    log_name = now.strftime("%Y-%m-%d") + ".log"
    log_path = _ensure_logs_dir() / log_name
    line = f"{now.isoformat()}\t{qq}\t{img_id}\n"
    async with aiofiles.open(str(log_path), "a", encoding="utf-8") as f:
        await f.write(line)


_BLACKLIST_FILE = Path(__file__).parent / "blacklist.json"
_blacklist: set[int] = set()


def _load_blacklist() -> set[int]:
    global _blacklist
    if _BLACKLIST_FILE.exists():
        _blacklist = set(json.loads(_BLACKLIST_FILE.read_text(encoding="utf-8")))
    return _blacklist


async def _save_blacklist() -> None:
    async with aiofiles.open(str(_BLACKLIST_FILE), "w", encoding="utf-8") as f:
        await f.write(json.dumps(sorted(_blacklist)))


_load_blacklist()


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
) -> tuple[int, str]:
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
                f"与 id={dup.id} 重复（汉明距离 ≤ {config.dedup_hamming_threshold}）"
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
        await session.refresh(record)

    return record.id, new_name


upload_image = on_command("上传图片", block=True)


@upload_image.handle()
async def handle_command(matcher: Matcher, event: MessageEvent) -> None:
    if not config.enable_upload:
        await matcher.finish("图片上传功能未开启")
    if event.message_type != "private":
        await matcher.finish("请私聊发送此指令")
    await matcher.send("已进入图片上传模式，发送图片即可上传，输入「退出」结束。")


@upload_image.got("img")
async def got_image(matcher: Matcher, event: MessageEvent) -> None:
    raw_msg = event.message.extract_plain_text().strip()
    if raw_msg in ("退出", "exit", "quit"):
        await matcher.finish("已退出图片上传模式")

    image_segments = event.message["image"]
    if not image_segments:
        await matcher.reject("请发送图片，或输入「退出」结束")

    saved: list[str] = []
    skipped: list[str] = []
    for seg in image_segments:
        file_name = seg.data["file"]
        url = seg.data.get("url")
        try:
            img_id, _ = await _save_image(file_name, url, event.user_id)
            saved.append(str(img_id))
        except ValueError as e:
            skipped.append(str(e))

    lines: list[str] = []
    if saved:
        lines.append(f"已保存: {', '.join(saved)}")
    if skipped:
        lines.extend(skipped)
    if not saved and not skipped:
        lines.append("未保存任何图片")

    await matcher.reject("\n".join(lines) + "\n继续发送图片，或输入「退出」结束")


toggle_upload = on_command("开关上传", block=True, permission=SUPERUSER)


@toggle_upload.handle()
async def handle_toggle_upload(matcher: Matcher) -> None:
    config.enable_upload = not config.enable_upload
    status = "已开启" if config.enable_upload else "已关闭"
    await matcher.finish(f"图片上传功能{status}")


count_image = on_command("有多少桃", block=True, permission=SUPERUSER)


@count_image.handle()
async def handle_count_image(matcher: Matcher) -> None:
    from sqlalchemy import select, func  # noqa: PLC0415

    async with db_manager.session() as session:
        count = (await session.execute(select(func.count(ImageRecord.id)))).scalar()
    await matcher.finish(f"共 {count} 张图片")


import random  # noqa: E402

_recent_ids: list[int] = []
_reply_id_map: dict[int, int] = {}  # message_id → img_id
_last_random_time = 0.0

random_image = on_message(fullmatch("来点桃"), block=True)


@random_image.handle()
async def handle_random_image(matcher: Matcher, event: MessageEvent) -> None:
    if event.user_id in _blacklist:
        await matcher.finish("你已被拉黑，无法使用此功能")

    global _last_random_time, _recent_ids
    now = _time()
    if now - _last_random_time < config.random_image_cooldown:
        remaining = int(config.random_image_cooldown - (now - _last_random_time))
        await matcher.finish(f"冷却中，请 {remaining} 秒后再试")

    from sqlalchemy import select  # noqa: PLC0415

    async with db_manager.session() as session:
        result = await session.execute(select(ImageRecord.id))
        all_ids = [row[0] for row in result]

    # 从最近队列中清理已不存在的 id（被删除的图片）
    _recent_ids = [i for i in _recent_ids if i in all_ids]

    max_exclude = int(len(all_ids) * config.recent_exclude_ratio)
    excluded = set(_recent_ids[-max_exclude:]) if max_exclude else set()
    candidates = [i for i in all_ids if i not in excluded]

    if not candidates:
        # 全部被排除，重置队列，全部可选
        candidates = all_ids
        _recent_ids.clear()

    img_id = random.choice(candidates)
    _recent_ids.append(img_id)
    # 保持队列大小不超过所有图片的总数
    while len(_recent_ids) > len(all_ids):
        _recent_ids.pop(0)

    _last_random_time = now

    async with db_manager.session() as session:
        record = (
            await session.execute(select(ImageRecord).where(ImageRecord.id == img_id))
        ).scalar_one()

    await _log_random_image(event.user_id, record.id)

    from nonebot.adapters.onebot.v11 import MessageSegment  # noqa: PLC0415
    img_path = _ensure_image_dir() / record.stored_name
    msg_id_data = await matcher.send(MessageSegment.image(img_path))
    _reply_id_map[msg_id_data["message_id"]] = img_id
    await matcher.finish()


from nonebot.rule import Rule  # noqa: E402


def _blacklist_rule(event: MessageEvent) -> bool:
    return event.get_plaintext().strip().startswith(("/黑名单添加", "/黑名单删除"))


def _delete_image_rule(event: MessageEvent) -> bool:
    return event.get_plaintext().strip() == "/删除图片"


blacklist_mgr = on_message(Rule(_blacklist_rule), block=True, permission=SUPERUSER)


def _parse_at_targets(event: MessageEvent) -> list[int]:
    return [int(seg.data["qq"]) for seg in event.message["at"]]


@blacklist_mgr.handle()
async def handle_blacklist(matcher: Matcher, event: MessageEvent) -> None:
    plain = event.message.extract_plain_text().strip()

    if plain.startswith("/黑名单添加"):
        targets = _parse_at_targets(event)
        if not targets:
            await matcher.finish("请 @ 要拉黑的成员，例如：/黑名单添加 @成员")
        for qq in targets:
            if qq in _blacklist:
                await matcher.send(f"{qq} 已在黑名单中")
                continue
            _blacklist.add(qq)
            await _save_blacklist()
            await matcher.send(f"已将 {qq} 加入黑名单")

    elif plain.startswith("/黑名单删除"):
        targets = _parse_at_targets(event)
        if not targets:
            await matcher.finish("请 @ 要移出的成员，例如：/黑名单删除 @成员")
        for qq in targets:
            if qq not in _blacklist:
                await matcher.send(f"{qq} 不在黑名单中")
                continue
            _blacklist.discard(qq)
            await _save_blacklist()
            await matcher.send(f"已将 {qq} 移出黑名单")


delete_image = on_message(Rule(_delete_image_rule), block=True, permission=SUPERUSER)


@delete_image.handle()
async def handle_delete_image(matcher: Matcher, event: MessageEvent) -> None:
    reply = event.reply
    if reply is None:
        await matcher.finish("请回复要删除的那张图片消息，再发送 /删除图片")

    global _reply_id_map

    # 清理无效映射，同时查找目标
    img_id = _reply_id_map.pop(reply.message_id, None)
    if img_id is None:
        await matcher.finish("未找到该消息对应的图片，可能已过期或不是机器人发送的图片")

    # 顺便清理映射表，移除可能已失效的条目（上限 5000 条）
    if len(_reply_id_map) > 5000:
        _reply_id_map.clear()

    from sqlalchemy import delete, select  # noqa: PLC0415

    async with db_manager.session() as session:
        record = (
            await session.execute(
                select(ImageRecord).where(ImageRecord.id == img_id)
            )
        ).scalar()

        if record is None:
            await matcher.finish("图片记录已不存在，可能已被删除")

        img_path = _ensure_image_dir() / record.stored_name
        if img_path.exists():
            img_path.unlink()

        await session.execute(delete(ImageRecord).where(ImageRecord.id == img_id))
        await session.commit()

    # 从最近队列中清理已删除的 id
    global _recent_ids
    if img_id in _recent_ids:
        _recent_ids = [i for i in _recent_ids if i != img_id]

    await matcher.finish(f"已删除图片 id={img_id}")
