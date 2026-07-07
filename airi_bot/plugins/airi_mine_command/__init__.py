import asyncio
from pathlib import Path

from nonebot import get_plugin_config, on_command
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.matcher import Matcher

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="airi_mine_command",
    description="零散指令合集",
    usage="/电脑开机",
    config=Config,
)

config = get_plugin_config(Config)

# ===== /电脑开机 =====
wake_pc = on_command("电脑开机", block=True, permission=SUPERUSER)


@wake_pc.handle()
async def handle_wake_pc(matcher: Matcher) -> None:
    mac_file = Path(__file__).parent / "mac.txt"
    if not mac_file.exists():
        await matcher.finish("未找到 mac.txt，请在插件目录下创建并写入目标 MAC 地址")

    mac = mac_file.read_text().strip()
    if not mac:
        await matcher.finish("mac.txt 内容为空")

    await matcher.send(f"正在向 {mac} 发送唤醒包...")

    proc = await asyncio.create_subprocess_exec(
        "wakeonlan", mac,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode().strip()
        await matcher.finish(f"唤醒失败 (exit={proc.returncode}):\n{err}")

    await matcher.finish(f"唤醒包已发送:\n{stdout.decode().strip()}")

