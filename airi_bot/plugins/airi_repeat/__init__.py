from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="airi_repeat",
    description="群消息复读：同一条文字消息被复读超过 5 次后，bot 跟上复读",
    usage="群聊中自动触发，无需指令",
    config=Config,
)

REPEAT_THRESHOLD = 4

# 每个群当前正在复读的文字及次数 { group_id: (text, count) }
_current_repeat: dict[int, tuple[str, int]] = {}


async def _is_text_group_message(event: GroupMessageEvent) -> bool:
    """仅限群聊中的纯文本消息，排除含图片、表情、@ 等的消息"""
    msg = str(event.get_message())
    if not msg.strip():
        return False
    if "[" in msg and "CQ:" in msg:
        return False
    return True


repeat_matcher = on_message(Rule(_is_text_group_message))


@repeat_matcher.handle()
async def handle_repeat(event: GroupMessageEvent) -> None:
    text = str(event.get_message()).strip()

    # 忽略 bot 自己发的消息
    if event.user_id == event.self_id:
        return

    group_id = event.group_id
    prev = _current_repeat.get(group_id)

    if prev is None:
        _current_repeat[group_id] = (text, 1)
        return

    if prev[0] != text:
        _current_repeat[group_id] = (text, 1)
        return

    # bot 已经复读过了（count == 0 表示已复读），跳过
    if prev[1] == 0:
        return

    count = prev[1] + 1

    if count >= REPEAT_THRESHOLD:
        # 标记已复读，count 置 0，直到下一条不同文字到来才清除
        _current_repeat[group_id] = (text, 0)
        await repeat_matcher.finish(text)
    else:
        _current_repeat[group_id] = (text, count)
