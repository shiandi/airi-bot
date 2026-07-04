from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="airi_repeat",
    description="群消息复读：同一条文字消息被复读超过 5 次后，bot 跟上复读",
    usage="群聊中自动触发，无需指令",
    config=Config,
)

REPEAT_THRESHOLD = 5

# 每个群当前接收到的上一条消息内容 { group_id: text }
_last_message: dict[int, str] = {}
# 每个群上一次复读的消息内容 { group_id: text }
_last_repeated: dict[int, str] = {}
# 每个群当前复读计数 { group_id: count }
_repeat_count: dict[int, int] = {}


repeat_matcher = on_message()


@repeat_matcher.handle()
async def handle_repeat(event: GroupMessageEvent) -> None:
    # 忽略 bot 自己发的消息
    if event.user_id == event.self_id:
        return

    group_id = event.group_id
    text = str(event.get_message())

    # 过滤 CQ 码消息（图片、语音等）
    if "[CQ:" in text:
        return

    # 第一步：判断是否和上一次复读的相同，相同则跳过
    if text == _last_repeated.get(group_id):
        return

    # 记录当前消息
    prev_message = _last_message.get(group_id)
    _last_message[group_id] = text

    # 第二步：判断和上一条消息是否相同
    if text != prev_message:
        _repeat_count[group_id] = 1
        _last_repeated.pop(group_id, None)
        return

    # 相同，count+1
    count = _repeat_count.get(group_id, 0) + 1
    _repeat_count[group_id] = count

    if count >= REPEAT_THRESHOLD:
        # 复读，记录本次复读内容，清空计数
        _last_repeated[group_id] = text
        _repeat_count[group_id] = 0
        await repeat_matcher.finish(text)
