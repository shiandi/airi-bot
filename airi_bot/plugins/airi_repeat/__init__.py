import re

from nonebot import on_message, logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="airi_repeat",
    description="群消息复读：同一条消息被复读超过 5 次后，bot 跟上复读",
    usage="群聊中自动触发，无需指令",
    config=Config,
)

REPEAT_THRESHOLD = 5

# 每个群上一次复读的消息（归一化后），用于防止同一条反复复读
_last_repeated: dict[int, str] = {}
# 每个群上一条消息（归一化后），用于判断是否连续相同
_last_message: dict[int, str] = {}
# 每个群当前连续相同计数
_repeat_count: dict[int, int] = {}

# CQ 码中每次会变化的动态字段，匹配时忽略
_DYNAMIC_CQ_KEYS = {"url", "fileid", "rkey", "file_size"}


def _normalize(text: str) -> str:
    """去掉 CQ 码中动态参数和 HTML 转义，保留稳定字段用于比较"""
    text = text.replace("&amp;", "&")

    def _clean(m: re.Match) -> str:
        args = m.group(1)
        parts = args.split(",")
        stable = [p for p in parts if p.split("=", 1)[0] not in _DYNAMIC_CQ_KEYS]
        return f"[{','.join(stable)}]"

    return re.sub(r"\[([^\[\]]+)\]", _clean, text)


repeat_matcher = on_message()


@repeat_matcher.handle()
async def handle_repeat(event: GroupMessageEvent) -> None:
    if event.user_id == event.self_id:
        return

    group_id = event.group_id
    message = event.get_message()
    text = _normalize(str(message))

    # 检查 1：防止同一条消息反复复读
    if _last_repeated.get(group_id) == text:
        return

    # 检查 2：和上一条不同 → 重置计数
    prev = _last_message.get(group_id)
    _last_message[group_id] = text

    if text != prev:
        _repeat_count[group_id] = 1
        _last_repeated.pop(group_id, None)
        return

    # 连续相同 → 计数 +1
    count = _repeat_count.get(group_id, 0) + 1

    if count >= REPEAT_THRESHOLD:
        _last_repeated[group_id] = text
        _repeat_count[group_id] = 0
        await repeat_matcher.finish(message)
    else:
        _repeat_count[group_id] = count
