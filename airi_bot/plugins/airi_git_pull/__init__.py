import asyncio
from datetime import datetime
from pathlib import Path

from nonebot import on_command
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.matcher import Matcher

__plugin_meta__ = PluginMetadata(
    name="airi_git_pull",
    description="git pull 指令：管理员发送「git pull」从远端拉取最新代码",
    usage="发送「git pull」执行 git pull",
)


def _find_project_root() -> str:
    """向上查找包含 .git 的目录作为项目根目录。"""
    current = Path(__file__).resolve().parent
    for parent in current.parents:
        if (parent / ".git").exists():
            return str(parent)
    return str(Path(__file__).resolve().parent.parent.parent.parent)


def _log_git_pull(message: str) -> None:
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_name = datetime.now().strftime("%Y-%m-%d") + ".log"
    log_path = log_dir / log_name
    line = f"{datetime.now().isoformat()}\t{message}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


git_pull = on_command("git pull", block=True, permission=SUPERUSER)


@git_pull.handle()
async def handle_git_pull(matcher: Matcher) -> None:
    project_root = _find_project_root()

    await matcher.send("正在执行 git pull...")

    proc = await asyncio.create_subprocess_exec(
        "git", "-C", project_root, "pull",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    output = stdout.decode().strip() or stderr.decode().strip()
    if proc.returncode != 0:
        await matcher.finish(f"git pull 失败 (exit={proc.returncode}):\n{output}")

    if "Already up to date" in output:
        await matcher.finish(f"git pull 成功:\n{output}")

    # 拉取了新代码，即将触发重载，不尝试发送结果消息
    _log_git_pull(f"git pull 成功:\n{output}")
    await asyncio.sleep(0.5)
    await matcher.finish()
