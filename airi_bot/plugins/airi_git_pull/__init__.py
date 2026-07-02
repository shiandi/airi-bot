import asyncio

from nonebot import on_command
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.matcher import Matcher

__plugin_meta__ = PluginMetadata(
    name="airi_git_pull",
    description="git pull 指令：管理员发送「git pull」从远端拉取最新代码",
    usage="发送「git pull」执行 git pull",
)

git_pull = on_command("git pull", block=True, permission=SUPERUSER)


@git_pull.handle()
async def handle_git_pull(matcher: Matcher) -> None:
    project_root = "/home/pjsk/airi-bot"

    proc = await asyncio.create_subprocess_exec(
        "git", "-C", project_root, "pull",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    output = stdout.decode().strip() or stderr.decode().strip()
    if proc.returncode != 0:
        await matcher.finish(f"git pull 失败 (exit={proc.returncode}):\n{output}")
    await matcher.finish(f"git pull 成功:\n{output}" if output else "git pull 成功 (无输出)")
