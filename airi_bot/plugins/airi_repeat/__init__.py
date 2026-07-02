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

REPEAT_THRESHOLD = 5

# 每个群当前正在复读的文字及次数 { group_id: (text, count) }
_current_repeat: dict[int, tuple[str, int]] = {}
# 记录 bot 已经复读过的消息 { group_id: set(text) }
_repeated_by_bot: dict[int, set[str]] = {}


async def _is_text_group_message(event: GroupMessageEvent) -> bool:
    """仅限群聊中的纯文本消息，排除含图片、表情、@ 等的消息"""
    msg = str(event.get_message())
    # 空消息或纯空格不算
    if not msg.strip():
        return False
    # 排除 CQ 码（图片、表情、@、回复、戳一戳等）
    if "[" in msg and "CQ:" in msg:
        return False
    return True


repeat_matcher = on_message(Rule(_is_text_group_message))


@repeat_matcher.handle()
async def handle_repeat(event: GroupMessageEvent) -> None:
    group_id = event.group_id
    text = str(event.get_message()).strip()

    # 忽略 bot 自己发的消息
    if event.user_id == event.self_id:
        return

    # 如果 bot 已经复读过这条消息，跳过
    if group_id in _repeated_by_bot and text in _repeated_by_bot[group_id]:
        return

    prev = _current_repeat.get(group_id)

    if prev is None or prev[0] != text:
        # 新文字，清掉旧的，从 1 开始计数
        _current_repeat[group_id] = (text, 1)
        return

    # 同一条文字，计数 +1
    count = prev[1] + 1
    _current_repeat[group_id] = (text, count)

    if count > REPEAT_THRESHOLD:
        _repeated_by_bot.setdefault(group_id, set()).add(text)
        del _current_repeat[group_id]
        await repeat_matcher.finish(text)
