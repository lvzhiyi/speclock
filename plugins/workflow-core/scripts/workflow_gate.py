#!/usr/bin/env python3
"""双宿主同步流程门禁；受支持前置路径遇到错误必须拒绝写入。"""
import json
import os
from pathlib import Path
import shlex
import sys

sys.path.insert(0, str(Path(__file__).parent))
from host_gate import context, pre_tool, project_root, record_hook_activity, safe_shell_input


def codex():
    return os.environ.get("WORKFLOW_HOST") == "codex"


def _persist_claude_env(session_id):
    if codex() or not isinstance(session_id, str) or not 0 < len(session_id) <= 512 or any(c in session_id for c in "\n\r\x00"):
        return
    raw_env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not raw_env_file:
        return
    try:
        env_path = Path(raw_env_file)
        if env_path.is_symlink() or not env_path.parent.is_dir():
            return
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(env_path), flags, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(f"export WORKFLOW_HOST=claude\nexport CLAUDE_SESSION_ID={shlex.quote(session_id)}\n")
    except OSError:
        pass


def emit_context(name, message):
    if codex() and name != "UserPromptSubmit":
        value = {"systemMessage": message}
    else:
        value = {"hookSpecificOutput": {"hookEventName": name, "additionalContext": message}}
    print(json.dumps(value, ensure_ascii=False))


def deny(reason):
    # 两宿主均支持 deny；Codex 不支持 ask，不输出不存在的权限值。
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                            "permissionDecisionReason": reason}}, ensure_ascii=False))


def handle(event, root=None):
    """旧 disabled 文件与 engine.enabled 均不再成为门禁绕过条件。"""
    if not isinstance(event, dict):
        raise ValueError("事件必须是 JSON 对象")
    if event.get("hook_event_name") == "SessionStart" and not codex():
        _persist_claude_env(event.get("session_id"))
    resolved_root = project_root(event.get("cwd"), event.get("session_id"))
    if resolved_root is None:
        return
    record_hook_activity(resolved_root, event)
    if event.get("hook_event_name") == "PreToolUse":
        reason = pre_tool(event)
        if reason:
            deny(reason)
        else:
            updated = safe_shell_input(event)
            if updated:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": updated}}, ensure_ascii=False))
        return
    if event.get("hook_event_name") in {"SessionStart", "Stop", "PostToolUse", "UserPromptSubmit"}:
        message = context(event)
        if event.get("hook_event_name") == "SessionStart" and not codex():
            session_id = event.get("session_id")
            if isinstance(session_id, str) and session_id.strip():
                cli = Path(__file__).with_name("workflow_engine_cli.py").resolve()
                header = f"Claude session_id: {session_id}\n引擎 CLI: {cli}"
                message = f"{header}\n{message}" if message else header
        if message:
            emit_context(event["hook_event_name"], message)


def main():
    """无法解析事件时用宿主阻断退出码，绝不能吞异常并成功放行。"""
    event = None
    try:
        event = json.load(sys.stdin)
        handle(event)
        return 0
    except Exception as exc:
        reason = "ENGINE_GATE_ERROR：门禁异常，受支持写入路径拒绝：" + str(exc)
        if isinstance(event, dict) and event.get("hook_event_name") == "PreToolUse":
            deny(reason)
            return 0
        print(reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
