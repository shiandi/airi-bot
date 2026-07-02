from pathlib import Path
from time import time as _time

from nonebot import get_plugin_config, on_keyword
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="airi_keyword_send_image",
    description="关键字触发发送图片：收到「到底有多强」「ddydq」时发送 ddydq.jpg",
    usage="群聊/私聊中发送指定关键词即可触发",
    config=Config,
)

config = get_plugin_config(Config)

_imgs_dir = Path(__file__).parent / "imgs"

# 关键词到图片文件名的映射
_KEYWORD_IMAGE_MAP = {
    "到底有多强": "ddydq.jpg",
    "ddydq": "ddydq.jpg",
}

_last_trigger_time = 0.0

keyword_matcher = on_keyword(_KEYWORD_IMAGE_MAP.keys(), block=True)


@keyword_matcher.handle()
async def handle_keyword(event: MessageEvent) -> None:
    global _last_trigger_time

    now = _time()
    if now - _last_trigger_time < config.cooldown:
        return

    _last_trigger_time = now

    text = event.get_plaintext().strip()
    img_name = _KEYWORD_IMAGE_MAP.get(text)
    if img_name is None:
        return

    img_path = _imgs_dir / img_name
    if not img_path.is_file():
        return

    await keyword_matcher.finish(MessageSegment.image(img_path))
