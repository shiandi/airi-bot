import asyncio
from pathlib import Path

from nonebot import get_plugin_config, on_command
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.matcher import Matcher

__plugin_meta__ = PluginMetadata(
    name="airi_git_pull",
    description="git pull 指令：管理员发送「git pull」从远端拉取最新代码",
    usage="发送「git pull」执行 git pull",
)

GIT_PULL_TIMEOUT = 60  # 秒


def _find_project_root() -> str:
    """向上查找包含 .git 的目录作为项目根目录。"""
    current = Path(__file__).resolve().parent
    for parent in current.parents:
        if (parent / ".git").exists():
            return str(parent)
    return str(Path(__file__).resolve().parent.parent.parent.parent)


git_pull = on_command("git pull", block=True, permission=SUPERUSER)


@git_pull.handle()
async def handle_git_pull(matcher: Matcher) -> None:
    project_root = _find_project_root()

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", project_root, "pull",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=GIT_PULL_TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        await matcher.finish("git pull 超时（超过 60 秒）")

    output = stdout.decode().strip() or stderr.decode().strip()
    if proc.returncode != 0:
        await matcher.finish(f"git pull 失败 (exit={proc.returncode}):\n{output}")
    await matcher.finish(f"git pull 成功:\n{output}" if output else "git pull 成功 (无输出)")
