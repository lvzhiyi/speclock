"""宿主共享同步门禁：流程防护栏，不是可信签署或系统写入沙箱。"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
import time
import uuid
from contextvars import ContextVar

CURRENT_EVENT = ContextVar("workflow_gate_event", default={})

from baseline_config import resolve_baselines
from workflow_config import load

# 原生进度更新只改变宿主展示，不构成引擎通过证据或产品文件写入。
READ_TOOLS = {
    "TodoWrite", "update_plan", "Read", "ReadFile", "Glob", "Grep", "rg", "LS",
    "WebSearch", "WebFetch", "Skill", "AskUserQuestion", "ExitPlanMode",
    "clocksleep", "clock.sleep", "clock:sleep", "clock__sleep", "sleep", "wait",
}
SHELL_TOOLS = {"Bash", "shell", "exec_command", "run_shell_command", "Shell"}
PLANNING_EDIT_TOOLS = {"Write", "Edit", "apply_patch"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
TIER_LABELS = {"轻量档": "light", "标准档": "standard", "完整档": "full"}
APPROVAL_ACCEPT_LABEL = "批准方案"
CODEX_CONFIRM_TOOLS = {"request_user_input", "request_user_input_async"}
CHAT_REPLY_WRAPPERS = (
    ("**", "**"),
    ("__", "__"),
    ("*", "*"),
    ("_", "_"),
    ("`", "`"),
    ("「", "」"),
    ("『", "』"),
    ("“", "”"),
    ("‘", "’"),
    ('"', '"'),
    ("'", "'"),
    ("【", "】"),
)
CHAT_STRIP_CHARS = " \t\r\n\u3000\u200b\ufeff"
HOOK_SESSION_PREFIX = "hook-session-"
HOOK_HEARTBEAT_INTERVAL = 15.0
CONFIRM_HELP = ("ENGINE_CONFIRMATION_UNSUPPORTED：当前宿主回调没有匹配的用户确认。"
                "请用 request-confirmation 准备聊天确认，并在 Agent 窗口展示回复选项。"
                "确认绑定当前任务、轮次、版本及控制摘要。")
ASYNC_PENDING_MSG = (
    "ENGINE_CONFIRMATION_PENDING：原生单选弹窗已展示，等待用户点选。"
    "请调用 clock.sleep（如 30000 毫秒）保持当前回合活跃等待用户点击，不要立刻发送 final_answer 结束回合（结束回合会关闭 Codex 异步弹窗）；"
    "收到用户点击回执后请重新读取 status 核实。"
)


def project_root(cwd, session_id=None):
    """最近配置为边界，禁止借用父项目状态；未接入的 .git 仓库仅在活跃规划登记时纳入。"""
    path = Path(cwd or ".").resolve()
    session = session_id if session_id is not None else CURRENT_EVENT.get().get("session_id")
    for folder in (path, *path.parents):
        if (folder / "ai-workflow.yaml").is_file():
            return folder
        if (folder / ".git").exists():
            if isinstance(session, str) and 0 < len(session) <= 512:
                from workflow_planning_cli import read_record
                if read_record(folder, session):
                    return folder
            break
    return None


def readonly_segments(command):
    """只拆分引号外的 &&；每段仍走严格解析，拒绝其他控制流和空段。"""
    if not isinstance(command, str):
        return None
    quote, escaped, start = None, False, 0
    segments = []
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
        elif quote is None and command[index:index + 2] == "&&":
            segments.append(command[start:index])
            index += 1
            start = index + 1
        index += 1
    segments.append(command[start:])
    return segments if all(shell_tokens(part) for part in segments) else None


def safe_shell_input(event):
    """对每段 Git 调查禁用外部 diff/textconv，保留宿主原输入字段。"""
    data = event.get("tool_input") or {}
    segments = readonly_segments(shell_command(data))
    if not segments:
        return None
    # 组合只开放纯只读查询；不能借此串联规划登记或引擎修改。
    if len(segments) > 1 and not all(readonly_single(part) for part in segments):
        return None
    commands, changed = [], False
    for part in segments:
        args = shell_tokens(part)
        index = 2 if args[:2] == ["git", "--no-pager"] else 1
        if args[0] == "git" and len(args) > index and args[index] in {"diff", "log", "show"}:
            if any(a.startswith(("--ext-diff", "--textconv", "--output")) for a in args):
                return None
            args[index + 1:index + 1] = ["--no-ext-diff", "--no-textconv"]
            changed = True
        commands.append(shlex.join(args))
    if not changed:
        return None
    result = dict(data)
    key = "command" if "command" in data else "cmd"
    original = data.get(key)
    normalized = " && ".join(commands)
    result[key] = [*original[:2], normalized] if isinstance(original, list) else normalized
    return result


def readonly_shell(command):
    """组合中的全部命令必须独立只读，不因首段合法就开放后续写入。"""
    segments = readonly_segments(command)
    return bool(segments) and all(readonly_single(part) for part in segments)


def readonly_single(command):
    """有限调查命令白名单；拒绝重定向、子命令和隐式执行。"""
    args = shell_tokens(command)
    if not args:
        return False
    if args[0] == "git" and len(args) > 1 and args[1] == "--no-pager":
        args.pop(1)
    if args[0] == "git":
        if args[1:] in (["remote", "-v"], ["remote", "--verbose"], ["remote"]):
            return True
        if len(args) >= 3 and args[1] == "symbolic-ref":
            rest = args[2:]
            if rest[0] == "--short":
                rest = rest[1:]
            return len(rest) == 1 and not rest[0].startswith("-")
        return len(args) >= 2 and args[1] in {"status", "diff", "log", "show", "ls-files", "rev-parse"} and all(
            not a.startswith(("--output", "--ext-diff", "--textconv", "--exec", "--config", "--upload-pack", "--open-files-in-pager", "--paginate")) for a in args[2:])
    if args[0] in {"pwd", "ls", "cat", "head", "tail", "wc", "stat"}:
        return not any(a.startswith(("--files0-from", "--output")) for a in args[1:])
    if args[0] == "rg":
        return not any(a.startswith(("--pre", "--hostname-bin", "--search-zip", "--open-files-in-pager")) or a.startswith("-z") for a in args[1:])
    return False


def engine_command(command):
    """仅允许本插件固定 CLI 入口，不能用任意 Python 或 shell 包装绕过门禁。"""
    args = shell_tokens(command)
    if not args:
        return False
    # hook 子进程不修改 Shell 父环境，只认可三宿主固定前缀。
    if args[0] in {"WORKFLOW_HOST=cursor", "WORKFLOW_HOST=codex", "WORKFLOW_HOST=claude"}:
        args = args[1:]
    if len(args) < 3 or args[0] not in {"python", "python3"}:
        return False
    script = Path(args[1])
    return script.is_absolute() and script.resolve() == Path(__file__).with_name("workflow_engine_cli.py").resolve()


def fixed_command(command, filename):
    """固定绝对入口与宿主前缀，不接受任意脚本或 shell 拼接。"""
    args = shell_tokens(command)
    if args and args[0] in {"WORKFLOW_HOST=cursor", "WORKFLOW_HOST=codex", "WORKFLOW_HOST=claude"}:
        args = args[1:]
    if not args or len(args) < 3 or args[0] not in {"python", "python3"}:
        return None
    script = Path(args[1])
    if not script.is_absolute() or script != Path(__file__).with_name(filename).absolute() or script.is_symlink():
        return None
    return args[2:]


def command_options(args, actions, options, repeated=()):
    """按 argv 消费键值，动作可以位于任意合法位置，重复标量一律拒绝。"""
    if not args:
        return None
    action, values = None, {}
    index = 0
    while index < len(args):
        token = args[index]
        if token in actions and action is None:
            action = token
            index += 1
        elif token in options and index + 1 < len(args):
            value = args[index + 1]
            if not value or value.startswith("-") or token in values and token not in repeated:
                return None
            values.setdefault(token, []).append(value)
            index += 2
        else:
            return None
    return (action, values) if action else None


def dashboard_command(command):
    """服务管理不需要实施任务，但必须明确动作且参数不能扩展或重复。"""
    return command_options(fixed_command(command, "dashboard_server.py"), {"on", "off", "status"}, {"--root", "--task"}) is not None


def archive_command(command, event):
    """归档已完成变更的固定入口，严格限定当前项目根与白名单选项。"""
    args = fixed_command(command, "archive_change.py")
    if args is None:
        return False
    if args in (["--help"], ["-h"]):
        return True
    root = project_root(event.get("cwd"))
    if root is None:
        return False
    values, flags, index = {}, set(), 0
    while index < len(args):
        token = args[index]
        if token in {"--dry-run", "--skip-check"}:
            if token in flags:
                return False
            flags.add(token)
            index += 1
        elif token in {"--root", "--task", "--changes-dir", "--month"} and index + 1 < len(args):
            value = args[index + 1]
            if not value or value.startswith("-") or token in values and token != "--task":
                return False
            values.setdefault(token, []).append(value)
            index += 2
        else:
            return False
    if "--root" not in values or not values.get("--task"):
        return False
    raw_root = values["--root"][0]
    target_root = Path(raw_root if Path(raw_root).is_absolute() else Path(event.get("cwd") or ".") / raw_root).resolve()
    if target_root != root:
        return False
    return "--month" not in values or bool(re.fullmatch(r"\d{4}-\d{2}", values["--month"][0]))


def planning_command(command, event):
    """仅当前项目和宿主会话可登记；不将登记视为真人身份认证。"""
    args = fixed_command(command, "workflow_planning_cli.py")
    # 帮助在 argparse 处理时即退出，不登记授权，也不要求会话绑定。
    if args in (["--help"], ["-h"]) or (args and len(args) == 2 and args[0] in {"open", "close", "status"} and args[1] in {"--help", "-h"}):
        return True
    parsed = command_options(args, {"open", "close", "status"},
                             {"--root", "--session", "--operation", "--path", "--ttl", "--config-json"}, {"--path"})
    if not parsed:
        return False
    action, values = parsed
    if (values.get("--session") != [event.get("session_id")] or "--root" not in values or
            Path(values["--root"][0]).resolve() != project_root(event.get("cwd"))):
        return False
    if action != "open":
        return set(values) == {"--root", "--session"}
    return (values.get("--operation") in (["init"], ["prd-breakdown"]) and bool(values.get("--path")) and
            ("--ttl" not in values or values["--ttl"][0].isdigit() and 1 <= int(values["--ttl"][0]) <= 3600) and
            ("--config-json" not in values or values["--operation"] == ["init"]))


def init_read_command(command, event):
    """初始化只读探测与文档校验的固定入口，不开放任意解释器执行。"""
    args = shell_tokens(command)
    if args and args[0] in {"WORKFLOW_HOST=cursor", "WORKFLOW_HOST=codex", "WORKFLOW_HOST=claude"}:
        args = args[1:]
    if not args:
        return False
    root = project_root(event.get("cwd"))
    def same_root(value):
        return Path(value if Path(value).is_absolute() else Path(event.get("cwd") or ".") / value).resolve() == root
    plugin = Path(__file__).absolute().parent.parent
    if args[0] == "bash" and len(args) == 3:
        return args[1] == str(plugin / "skills/init/detect.sh") and not Path(args[1]).is_symlink() and same_root(args[2])
    if args[:3] == ["git", "check-ignore", "-v"]:
        try:
            from workflow_planning_cli import safe_path
            return bool(args[3:]) and all(not p.startswith("-") and safe_path(root, p) for p in args[3:])
        except (ValueError, TypeError):
            return False
    remaining = fixed_command(command, "check_docs.py")
    if remaining is None or remaining.count("--check-config") != 1:
        return False
    remaining = [a for a in remaining if a != "--check-config"]
    return len(remaining) == 2 and remaining[0] == "--root" and same_root(remaining[1])


def pending_path(root, session, channel=""):
    from workflow_engine_cli import default_db
    name = hashlib.sha256((channel + str(session)).encode()).hexdigest()
    return default_db(root).parent / ("confirmation-" + name + ".json")


def save_pending(path, pending, root=None):
    if root is not None:
        from workflow_engine.state_dir import STATE_DIRNAME, ensure_internal_state_dir, is_internal_state
        resolved_root = Path(root).resolve()
        if (resolved_root / STATE_DIRNAME).is_symlink() or is_internal_state(resolved_root, path):
            ensure_internal_state_dir(resolved_root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(pending, handle, ensure_ascii=False)
            handle.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def confirmation_target(task, action):
    return dict(task=task["id"], round=task["current_round"], digest=task["control_digest"],
                version=task["version"], action=action)


def matches_confirmation(event, task, pending):
    return not binding_error(event, task) and all(
        value == pending.get(key) for key, value in confirmation_target(task, pending["action"]).items())


def hook_activity_path(root, session):
    from workflow_engine_cli import default_db
    name = hashlib.sha256(str(session).encode()).hexdigest()
    return default_db(root).parent / (HOOK_SESSION_PREFIX + name + ".json")


def read_hook_activity(root, session):
    if not isinstance(session, str) or not 0 < len(session) <= 512:
        return None
    path = hook_activity_path(root, session)
    if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def record_hook_activity(root, event):
    """最佳努力记录当前会话已触发的宿主钩子事件与节流心跳，绝不阻断门禁主路径。"""
    try:
        if not isinstance(event, dict):
            return
        session = event.get("session_id")
        event_name = event.get("hook_event_name")
        if not isinstance(session, str) or not 0 < len(session) <= 512:
            return
        if not isinstance(event_name, str) or not event_name.strip():
            return
        host = os.environ.get("WORKFLOW_HOST") or "claude"
        raw_tool = event.get("tool_name")
        tool_name = raw_tool.strip()[:64] if isinstance(raw_tool, str) and raw_tool.strip() else ""
        now = time.time()
        path = hook_activity_path(root, session)
        existing = read_hook_activity(root, session) or {}
        raw_events = existing.get("events") if isinstance(existing.get("events"), list) else []
        events = [item for item in raw_events if isinstance(item, str) and item]
        raw_prev_updated = existing.get("updated_at")
        prev_updated = float(raw_prev_updated) if isinstance(raw_prev_updated, (int, float)) else 0.0
        prev_event = existing.get("last_event") if isinstance(existing.get("last_event"), str) else ""
        stop_transition = (event_name == "Stop") != (prev_event == "Stop")
        if existing.get("host") == host and event_name in events and not stop_transition and (now - prev_updated) < HOOK_HEARTBEAT_INTERVAL:
            return
        if event_name not in events:
            events.append(event_name)
        payload = {
            "session_id": session,
            "host": host,
            "events": events,
            "last_event": event_name,
            "last_tool": tool_name,
            "updated_at": round(now, 3),
        }
        save_pending(path, payload, root=root)
    except Exception:
        return


def detect_host():
    """仅从显式宿主或会话级环境变量推断宿主，避免误读全局目录变量。"""
    explicit = os.environ.get("WORKFLOW_HOST")
    if explicit:
        return explicit
    if os.environ.get("CODEX_THREAD_ID"):
        return "codex"
    if os.environ.get("CURSOR_PROJECT_DIR") or os.environ.get("CURSOR_PLUGIN_ROOT"):
        return "cursor"
    if os.environ.get("CLAUDE_PLUGIN_ROOT") or os.environ.get("CLAUDECODE"):
        return "claude"
    return None


def _inactive_hook_warning(host_hint):
    if host_hint == "codex":
        guide = "请先在 Codex 的 Settings → Hooks（或 CLI /hooks）中授权、信任并启用 workflow-core@speclock 的全部钩子，然后新开/重启会话重试；"
    elif host_hint == "cursor":
        guide = "请先确认已在 Cursor 中启用 workflow-core 插件与 hooks/cursor.json 钩子并重新加载会话；"
    elif host_hint == "claude":
        guide = "请先确认已在 Claude Code 中启用 workflow-core 插件与 UserPromptSubmit 钩子；"
    else:
        guide = "请先在宿主中启用并信任 workflow-core 的插件钩子（如 Codex 的 Settings → Hooks 或 /hooks）；"
    return (
        "ENGINE_HOOK_INACTIVE：当前会话未检测到 SpecLock Hook 运行，原生单选卡片与聊天定档/批准回复均不会被自动登记。"
        + guide
        + "或改用交互终端执行 confirm-tier / approve-proposal，不要调用原生单选工具或让用户反复发送聊天口令。"
    )


def hook_confirmation_status(root, session):
    activity = read_hook_activity(root, session)
    if not activity:
        return {
            "hook_active": False,
            "hook_events": [],
            "hook_warning": _inactive_hook_warning(detect_host()),
        }
    raw_events = activity.get("events")
    events = [item for item in raw_events if isinstance(item, str) and item] if isinstance(raw_events, list) else []
    hook_host = activity.get("host") if isinstance(activity.get("host"), str) and activity.get("host") else None
    hook_active = "UserPromptSubmit" in events
    result = {"hook_active": hook_active, "hook_events": events}
    if hook_host:
        result["hook_host"] = hook_host
    if not hook_active:
        observed = ", ".join(events) if events else "无"
        result["hook_warning"] = (
            f"ENGINE_HOOK_INACTIVE：当前会话仅检测到部分钩子（{observed}），尚未检测到 UserPromptSubmit / beforeSubmitPrompt 回调，原生单选卡片（含异步回执）与聊天定档/批准回复可能无法被自动登记。"
            "请在宿主中确认已信任并启用 UserPromptSubmit / beforeSubmitPrompt 钩子，或改用交互终端执行 confirm-tier / approve-proposal。"
        )
    return result


def resolve_cli_session(session=None, task=None):
    """按显式参数、当前宿主会话环境变量、任务当前轮次绑定的优先级解析会话 ID。"""
    if isinstance(session, str) and session.strip():
        return session.strip()
    for env_key in ("CODEX_THREAD_ID", "CLAUDE_SESSION_ID"):
        value = os.environ.get(env_key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(task, dict):
        rounds = task.get("rounds")
        if isinstance(rounds, list) and rounds and isinstance(rounds[-1], dict):
            bound = rounds[-1].get("session_id")
            if isinstance(bound, str) and bound.strip():
                return bound.strip()
    return None


def _scan_hook_activities(root):
    """只读扫描状态目录下已记录的钩子会话文件，绝不创建目录或写入任何文件。"""
    from workflow_engine_cli import default_db
    state = default_db(root).parent
    if state.is_symlink() or not state.is_dir():
        return []
    activities = []
    try:
        entries = list(state.glob(HOOK_SESSION_PREFIX + "*.json"))
    except OSError:
        return []
    for entry in entries:
        try:
            if entry.is_symlink() or not entry.is_file():
                continue
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            activities.append(data)
    return activities


def hook_precheck_status(root, session=None, task=None, max_recent_age=600.0):
    """只读前置检查当前会话 SpecLock Hook 状态；支持缺省会话及错配排查。"""
    resolved = resolve_cli_session(session=session, task=task)
    if resolved:
        result = hook_confirmation_status(root, resolved)
        result["session_id"] = resolved
        if not result["hook_active"] and not result["hook_events"]:
            now = time.time()
            has_recent_other = any(
                entry.get("session_id") != resolved
                and isinstance(entry.get("updated_at"), (int, float))
                and not isinstance(entry.get("updated_at"), bool)
                and now - float(entry["updated_at"]) <= max_recent_age
                for entry in _scan_hook_activities(root)
            )
            if has_recent_other:
                result["other_active_sessions"] = True
                result["hook_warning"] += "（另检测到本项目存在其他会话的近期钩子记录，若确认已授权，请核对 --session 是否与当前宿主真实会话 ID 一致。）"
        return result
    activities = _scan_hook_activities(root)
    if not activities:
        return {
            "hook_active": False,
            "hook_events": [],
            "hook_warning": _inactive_hook_warning(detect_host()),
        }
    return {
        "hook_active": None,
        "hook_events": [],
        "hook_warning": "ENGINE_HOOK_SESSION_UNKNOWN：未能确定当前会话 ID，请传入 --session（Codex 为 CODEX_THREAD_ID，Cursor 为 conversation_id）以精确核对当前会话的 SpecLock Hook 状态。",
    }


def normalize_chat_reply(prompt):
    """剥离首尾成对 Markdown 标记和常见引号，同时保留内部结构。"""
    text = prompt.strip(CHAT_STRIP_CHARS)
    while text:
        stripped = False
        for left, right in CHAT_REPLY_WRAPPERS:
            if len(text) > len(left) + len(right) and text.startswith(left) and text.endswith(right):
                text = text[len(left):len(text) - len(right)].strip(CHAT_STRIP_CHARS)
                stripped = True
                break
        if not stripped:
            break
    return text


def parse_chat_confirmation_reply(prompt):
    """严格匹配纯确认口令（兼容首尾成对包裹），拒绝自然语言句子。"""
    if not isinstance(prompt, str):
        return None, None
    reply = normalize_chat_reply(prompt)
    if reply == APPROVAL_ACCEPT_LABEL:
        return "approval", None
    tier = normalize_tier_label(reply)
    if tier:
        return "tier_confirmation", tier
    return None, None


def request_chat_confirmation(root, task, version, session, action, request):
    """登记待回应的版本；CLI 不写入任何人工确认凭据。"""
    from workflow_engine.model import EngineError
    explicit_host = os.environ.get("WORKFLOW_HOST") or None
    if (explicit_host is not None and explicit_host not in {"cursor", "codex", "claude"}) or binding_error({"session_id": session}, task) or task["version"] != version:
        raise EngineError("CONFIRMATION_INVALID", "确认请求须使用当前任务版本和绑定会话")
    missing = set(task["missing"])
    if (task["state"] != "created" or action not in {"tier_confirmation", "approval"} or action not in missing or
            (action == "approval" and {"tier_confirmation", "proposal", "steps", "verify_config"} & missing)):
        raise EngineError("CONFIRMATION_INVALID", "当前任务未等待此确认，或方案尚未就绪")
    pending = dict(confirmation_target(task, action), request=request)
    save_pending(pending_path(root, session, "chat:"), pending, root=root)
    replies = ["选" + label for label in TIER_LABELS] if action == "tier_confirmation" else ["批准方案"]
    return dict(pending, replies=replies, **hook_confirmation_status(root, session))


def _parse_async_question_reply(prompt):
    if not isinstance(prompt, str):
        return None
    match = re.fullmatch(
        r"\s*<send_user_message_question_reply>\s*(.*?)\s*</send_user_message_question_reply>\s*",
        prompt,
        flags=re.DOTALL,
    )
    if not match:
        return None
    try:
        items = json.loads(match.group(1))
    except ValueError:
        return None
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        return None
    item = items[0]
    raw_id = item.get("questionItemId")
    item_id = raw_id
    if isinstance(raw_id, str):
        try:
            item_id = json.loads(raw_id)
        except ValueError:
            return None
    if not (
        isinstance(item_id, list)
        and len(item_id) == 3
        and item_id[0] == "request_user_input_async"
        and isinstance(item_id[1], str)
        and item_id[1]
        and item_id[2] == 0
    ):
        return None
    question = item.get("question")
    answer = item.get("answer")
    if not isinstance(question, str) or not isinstance(answer, str) or not answer.strip():
        return None
    return {"call": item_id[1], "question": question, "answer": answer.strip()}


def _async_question_confirmation(event, root, reply):
    from workflow_engine.model import EngineError

    session = event.get("session_id")
    path = pending_path(root, session)
    if path.is_symlink() or not path.is_file():
        if "workflow-confirm:" in reply["question"]:
            return "ENGINE_CONFIRMATION_REJECTED：未找到当前会话的待确认弹窗记录，请重新发起确认。"
        return None
    try:
        pending = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(pending, dict)
        or pending.get("host") != "codex"
        or pending.get("tool") != "request_user_input_async"
        or pending.get("call") != reply["call"]
    ):
        if "workflow-confirm:" in reply["question"]:
            return "ENGINE_CONFIRMATION_REJECTED：异步弹窗回执与当前待确认调用不匹配，请重新发起确认。"
        return None
    expected_marker = "workflow-confirm:" + pending["task"] + ":" + pending["round"] + ":" + pending["digest"] + ":" + pending["action"]
    markers = re.findall(r"workflow-confirm:[^\s\"<>]+", reply["question"])
    marker_ok = markers == [expected_marker] and reply["question"].count("workflow-confirm:") == 1
    question = native_question(pending.get("input") or {})
    tier = None
    if pending["action"] == "tier_confirmation":
        if offered_tiers(question) and not question.get("multiSelect"):
            tier = normalize_tier_label(reply["answer"], allow_recommended=True)
        accepted = marker_ok and tier is not None
    elif pending["action"] == "approval":
        accepted = (
            marker_ok
            and is_approval_accept_label(reply["answer"], allow_recommended=True)
            and offered_approval(question)
            and not question.get("multiSelect")
        )
    else:
        accepted = False
    CURRENT_EVENT.set(event)
    try:
        task = load_task(root)
        if not accepted or not matches_confirmation(event, task, pending):
            return "ENGINE_CONFIRMATION_REJECTED：回执未确认或任务/轮次/版本已经变化，请重新展示确认选项。"
        record_confirmation(root, pending, "codex 原生用户流程", tier)
    except (EngineError, ValueError) as error:
        return "ENGINE_CONFIRMATION_REJECTED：" + str(error)
    return "ENGINE_CONFIRMATION_RECORDED：已登记当前任务的" + ("方案批准。" if pending["action"] == "approval" else "档位选择。")


def chat_confirmation(event, root):
    """只消费宿主提交的独立用户消息，不解析 Agent 或工具正文。"""
    from workflow_engine.model import EngineError
    prompt, session = event.get("prompt"), event.get("session_id")
    if not isinstance(prompt, str) or not isinstance(session, str) or not session:
        return None
    async_reply = _parse_async_question_reply(prompt)
    if async_reply is not None:
        return _async_question_confirmation(event, root, async_reply)
    action, tier = parse_chat_confirmation_reply(prompt)
    if not action:
        return None
    host = os.environ.get("WORKFLOW_HOST") or "claude"
    path = pending_path(root, session, "chat:")
    if not path.is_file() or path.is_symlink():
        legacy_path = pending_path(root, session, host + ":chat:")
        if not legacy_path.is_file() or legacy_path.is_symlink():
            return None
        path = legacy_path
    pending = json.loads(path.read_text(encoding="utf-8"))
    if pending["action"] != action:
        return None
    CURRENT_EVENT.set(event)
    try:
        task = load_task(root)
        if not matches_confirmation(event, task, pending):
            return "ENGINE_CONFIRMATION_REJECTED：任务版本或会话已变化，请重新展示确认选项。"
        record_confirmation(root, pending, host + " 用户聊天回复", tier)
    except (EngineError, ValueError) as error:
        return "ENGINE_CONFIRMATION_REJECTED：" + str(error)
    return "ENGINE_CONFIRMATION_RECORDED：已登记当前任务的" + ("方案批准。" if action == "approval" else "档位选择。")


def record_confirmation(root, pending, actor, tier=None):
    from workflow_engine.engine import Engine
    from workflow_engine_cli import default_db
    engine = Engine(root, default_db(root))
    args = (pending["task"], pending["version"], pending["request"], actor)
    if pending["action"] == "approval":
        return engine.approve_proposal(*args, pending["digest"])
    return engine.confirm_tier(*args) if tier is None else engine.confirm_tier(*args, tier)


def confirmation_markers(event):
    """普通澄清不进入授权链；出现协议前缀后必须完整匹配，不能用前缀子串批准。"""
    text = json.dumps(event.get("tool_input") or {}, ensure_ascii=False)
    return text, re.findall(r"workflow-confirm:[^\s\"<>]+", text)


def native_confirmation_host(event):
    host = os.environ.get("WORKFLOW_HOST", "claude")
    tool = event.get("tool_name")
    if host == "codex" and tool in CODEX_CONFIRM_TOOLS:
        return host
    if host == "claude" and tool in {"AskUserQuestion", "ExitPlanMode"}:
        return host
    return None


def native_question(data):
    questions = data.get("questions")
    if isinstance(questions, list) and len(questions) == 1 and isinstance(questions[0], dict):
        return questions[0]
    return {}


def question_prompt_text(question):
    for field in ("question", "title"):
        value = question.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return None


def option_labels(question):
    options = question.get("options")
    if not isinstance(options, list):
        return None
    labels = []
    for option in options:
        if isinstance(option, str) and option.strip():
            labels.append(option.strip())
        elif isinstance(option, dict) and isinstance(option.get("label"), str) and option["label"].strip():
            labels.append(option["label"].strip())
        else:
            return None
    return labels


def _strip_recommended_suffix(text):
    """剥离宿主单选推荐标记后缀（仅用于原生选项卡片，不放宽聊天口令）。"""
    return re.sub(r"\s*(?:\(recommended\)|（推荐）|\(推荐\))\s*$", "", text.strip(), flags=re.IGNORECASE)


def normalize_tier_label(label, allow_recommended=False):
    if not isinstance(label, str):
        return None
    text = _strip_recommended_suffix(label) if allow_recommended else label.strip()
    if text in TIER_LABELS:
        return TIER_LABELS[text]
    if text.startswith("选") and text[1:] in TIER_LABELS:
        return TIER_LABELS[text[1:]]
    return None


def is_approval_accept_label(label, allow_recommended=False):
    if not isinstance(label, str):
        return False
    text = _strip_recommended_suffix(label) if allow_recommended else label.strip()
    return text == APPROVAL_ACCEPT_LABEL


def offered_tiers(question):
    labels = option_labels(question)
    if not labels or len(labels) != 3:
        return False
    mapped = [normalize_tier_label(label, allow_recommended=True) for label in labels]
    return all(mapped) and set(mapped) == set(TIER_LABELS.values())


def offered_approval(question):
    labels = option_labels(question)
    if not labels or len(labels) < 2:
        return False
    accept_count = sum(1 for label in labels if is_approval_accept_label(label, allow_recommended=True))
    return len(set(labels)) == len(labels) and accept_count == 1


def extract_native_answer(host, question, response):
    if not isinstance(response, dict):
        return None
    answers = response.get("answers")
    if isinstance(answers, dict) and len(answers) == 1:
        keys = [question.get("id")] if host == "codex" and isinstance(question.get("id"), str) else []
        prompt_text = question_prompt_text(question)
        if prompt_text:
            keys.append(prompt_text)
        answer = None
        for key in keys:
            if key in answers:
                answer = answers[key]
                break
        if answer is None and host == "codex" and not question.get("id"):
            answer = next(iter(answers.values()))
        if isinstance(answer, dict):
            values = answer.get("answers")
            if isinstance(values, list) and len(values) == 1:
                answer = values[0]
            elif isinstance(answer.get("answer"), str):
                answer = answer["answer"]
            else:
                answer = None
        return answer if isinstance(answer, str) else None
    if isinstance(answers, list) and len(answers) == 1:
        item = answers[0]
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            if isinstance(item.get("answer"), str):
                return item["answer"]
            values = item.get("answers")
            if isinstance(values, list) and len(values) == 1 and isinstance(values[0], str):
                return values[0]
    if isinstance(response.get("answer"), str):
        return response["answer"]
    return None


def prepare_confirmation(event, root):
    """将待确认目标持久化；回执只消费相同工具调用及当前版本请求。"""
    text, markers = confirmation_markers(event)
    if "workflow-confirm:" not in text:
        return None
    host = native_confirmation_host(event)
    if host is None:
        return None
    try:
        task = load_task(root)
        error = binding_error(event, task)
        if error:
            return error
        data = event.get("tool_input") or {}
        text = json.dumps(data, ensure_ascii=False)
        tool = event["tool_name"]
        if tool == "ExitPlanMode" or (len(markers) == 1 and markers[0].endswith(":approval")):
            action = "approval"
        else:
            action = "tier_confirmation"
        marker = "workflow-confirm:" + task["id"] + ":" + task["current_round"] + ":" + task["control_digest"] + ":" + action
        if markers != [marker] or text.count("workflow-confirm:") != 1 or not event.get("tool_use_id"):
            return "ENGINE_CONFIRMATION_REQUIRED：确认请求必须包含 " + marker + "，并提供宿主 tool_use_id。"
        if tool != "ExitPlanMode":
            question = native_question(data)
            question_text = question_prompt_text(question)
            if ("answers" in data or question.get("multiSelect") or
                    not isinstance(question_text, str) or marker not in question_text.split()):
                label = "定档" if action == "tier_confirmation" else "方案批准"
                return f"ENGINE_CONFIRMATION_REQUIRED：{label}须使用用户填写的单选问题。"
            if host == "codex" and tool == "request_user_input" and (not isinstance(question.get("id"), str) or not question["id"]):
                return "ENGINE_CONFIRMATION_REQUIRED：Codex 原生确认问题须提供非空 id。"
            if action == "tier_confirmation" and host == "codex" and not offered_tiers(question):
                return "ENGINE_CONFIRMATION_REQUIRED：定档请求须提供轻量档、标准档和完整档。"
            if action == "approval" and not offered_approval(question):
                return "ENGINE_CONFIRMATION_REQUIRED：方案批准单选须提供「批准方案」及至少一个不批准选项。"
        request_id = uuid.uuid4().hex
        path = pending_path(root, event.get("session_id"))
        pending = dict(confirmation_target(task, action), host=host, tool=tool,
                       call=event["tool_use_id"], input=data, request=request_id)
        save_pending(path, pending, root=root)
        if tool == "request_user_input_async":
            save_pending(pending_path(root, event.get("session_id"), "chat:"),
                         dict(confirmation_target(task, action), request=request_id), root=root)
        return None
    except Exception as exc:
        return "ENGINE_CONFIRMATION_REQUIRED：" + str(exc) + "；" + CONFIRM_HELP


def complete_confirmation(event):
    text, markers = confirmation_markers(event)
    if "workflow-confirm:" not in text:
        return None
    host = native_confirmation_host(event)
    if host is None:
        return CONFIRM_HELP
    root = project_root(event.get("cwd"))
    if root is None:
        return None
    path = pending_path(root, event.get("session_id"))
    if not path.is_file():
        return CONFIRM_HELP
    pending = json.loads(path.read_text(encoding="utf-8"))
    response = event.get("tool_response")
    expected_marker = "workflow-confirm:" + pending["task"] + ":" + pending["round"] + ":" + pending["digest"] + ":" + pending["action"]
    if markers != [expected_marker] or text.count("workflow-confirm:") != 1:
        return CONFIRM_HELP
    if host == "codex" and isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            if pending["tool"] == "request_user_input_async":
                return ASYNC_PENDING_MSG
            return CONFIRM_HELP
    if (pending.get("host") != host or pending["call"] != event.get("tool_use_id") or
            pending["tool"] != event.get("tool_name") or pending["input"] != event.get("tool_input") or
            (isinstance(response, dict) and (response.get("error") or response.get("is_error")))):
        return CONFIRM_HELP
    if not isinstance(response, dict):
        if pending["tool"] == "request_user_input_async":
            return ASYNC_PENDING_MSG
        return CONFIRM_HELP
    tier = None
    if pending["action"] == "tier_confirmation":
        question = native_question(pending["input"])
        answer = extract_native_answer(host, question, response)
        if answer is None and pending["tool"] == "request_user_input_async":
            return ASYNC_PENDING_MSG
        if answer is not None and offered_tiers(question) and not question.get("multiSelect"):
            tier = normalize_tier_label(answer, allow_recommended=True)
        accepted = tier is not None or (host == "claude" and answer == "确认" and not offered_tiers(question))
    elif pending["tool"] == "ExitPlanMode":
        accepted = response.get("approved") is True
    else:
        question = native_question(pending["input"])
        answer = extract_native_answer(host, question, response)
        if answer is None and pending["tool"] == "request_user_input_async":
            return ASYNC_PENDING_MSG
        accepted = is_approval_accept_label(answer, allow_recommended=True) and offered_approval(question) and not question.get("multiSelect")
    task = load_task(root)
    if not accepted or not matches_confirmation(event, task, pending):
        return "ENGINE_CONFIRMATION_REJECTED：回执未确认或任务/轮次/版本已经变化；" + CONFIRM_HELP
    from workflow_engine.model import EngineError
    try:
        record_confirmation(root, pending, host + " 原生用户流程", tier)
    except EngineError as error:
        return "ENGINE_CONFIRMATION_REJECTED：" + str(error)
    return "ENGINE_CONFIRMATION_RECORDED：当前任务轮次用户流程确认已登记（非可信签署）。"


def shell_command(data):
    """兼容 Codex cmd 与 shell argv；argv 必须明确是 shell -c 结构。"""
    command = data.get("command", data.get("cmd", ""))
    if isinstance(command, list):
        if len(command) == 3 and command[0] in {"bash", "sh", "zsh", "/bin/bash", "/bin/sh", "/bin/zsh"} and command[1] in {"-c", "-lc"}:
            return command[2]
        return ""
    return command


def shell_tokens(command):
    """只在引号外拒绝 shell 语法；单引号 JSON 的美元符号是普通正文。"""
    if not isinstance(command, str):
        return None
    quote = None
    escaped = False
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if char in {"'", '\"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if quote != "'" and char in "$`":
            return None
        if quote is None and char in ";&|<>\n\r\x00":
            return None
    try:
        return shlex.split(command) if quote is None else None
    except ValueError:
        return None


def load_task(root):
    """写入前和阶段边界才核对全量内容哈希，不给每次只读工具增加快照成本。"""
    from workflow_engine.engine import Engine
    from workflow_engine.state_dir import migrate_legacy
    from workflow_engine_cli import default_db
    migrate_legacy(root)
    task_id = os.environ.get("WORKFLOW_TASK_ID")
    if not task_id:
        from session_binding import lookup
        task_id = lookup(root, CURRENT_EVENT.get().get("session_id"), default_db(root))
    return Engine(root, default_db(root)).status(task_id)


def targets(event, root):
    """从受支持编辑工具提取真实目标；不明确的写入按整个任务范围检查。"""
    data = event.get("tool_input") or {}
    values = []
    for key in ("file_path", "path", "target_file", "notebook_path"):
        if data.get(key):
            values.append(data[key])
    if event.get("tool_name") == "apply_patch":
        text = data.get("command") or data.get("patch") or data.get("input") or ""
        values.extend(re.findall(r"^\*\*\* (?:Update File|Add File|Delete File|Move to): (.+)$", text, re.M))
    result = []
    for value in values:
        # 规范化前保留并拒绝穿越与链接，不能把越界路径伪装为已登记目标。
        from workflow_planning_cli import safe_path
        result.append(safe_path(root, value))
    return result


def binding_error(event, task):
    """会话和执行者必须同时匹配当前轮次，防止借用其他 Agent 的读取证据。"""
    active = next((r for r in task.get("rounds", []) if r.get("id") == task.get("current_round")), {})
    round_id = os.environ.get("WORKFLOW_ROUND_ID", task.get("current_round"))
    executor = os.environ.get("WORKFLOW_EXECUTOR", active.get("executor"))
    if (task.get("protocol_version") != 2 or task.get("id") != os.environ.get("WORKFLOW_TASK_ID", task.get("id")) or
            not round_id or round_id != task.get("current_round") or not executor or
            active.get("executor") != executor or not event.get("session_id") or
            active.get("session_id") != event.get("session_id")):
        return "ENGINE_BINDING_REQUIRED：任务/轮次/执行者/会话绑定不匹配；请先 CLI bind-executor。"
    return None


def configured_baselines(root, task, paths):
    """未知 shell/MCP 目标保守覆盖范围内文件，目录范围也要展开匹配 scoped 规则。"""
    config = load(root)
    selected = list(dict.fromkeys([*task.get("scope", []), *paths]))
    # 目录范围保守纳入可能相交的规则，不遍历整个仓库或依赖目录。
    for rule in config.get("baseline.scoped") or []:
        pattern = rule.split(" => ", 1)[0]
        prefix = re.split(r"[?*[]", pattern, maxsplit=1)[0].rstrip("/")
        if any(scope == "." or not prefix or prefix == scope or prefix.startswith(scope.rstrip("/") + "/") or scope.startswith(prefix + "/") for scope in task.get("scope", [])):
            selected.append(pattern)
    return resolve_baselines(root, selected, config)


def pre_tool(event):
    CURRENT_EVENT.set(event)
    root = project_root(event.get("cwd"))
    if root is None:
        return None
    tool = event.get("tool_name")
    if tool in {"AskUserQuestion", "ExitPlanMode"} or (tool in CODEX_CONFIRM_TOOLS and os.environ.get("WORKFLOW_HOST") == "codex"):
        return prepare_confirmation(event, root)
    if tool in READ_TOOLS or tool in set(filter(None, os.environ.get("WORKFLOW_READONLY_MCP_TOOLS", "").split(","))):
        return None
    data = event.get("tool_input") or {}
    if tool in SHELL_TOOLS and (readonly_shell(shell_command(data)) or engine_command(shell_command(data)) or dashboard_command(shell_command(data)) or archive_command(shell_command(data), event) or planning_command(shell_command(data), event) or init_read_command(shell_command(data), event)):
        return None
    try:
        paths = targets(event, root)
        from workflow_engine.state_dir import is_state_relpath
        if any(is_state_relpath(p) for p in paths):
            return "ENGINE_STATE_PROTECTED：.speclock/ 是引擎状态目录，禁止直接编辑；请使用引擎 CLI。"
        # 规划例外只覆盖原生编辑；Shell 与 MCP 不能借用规划登记写文件。
        from workflow_planning_cli import allows, read_record
        session = event.get("session_id")
        if tool in PLANNING_EDIT_TOOLS and allows(root, session, paths):
            return None
        try:
            task = load_task(root)
        except ValueError as exc:
            if not str(exc).startswith("ENGINE_TASK_UNBOUND：") or not session or not read_record(root, session):
                raise
            if tool in PLANNING_EDIT_TOOLS:
                return "ENGINE_PLANNING_TARGET_DENIED：原生编辑的所有目标须在当前规划登记清单内。"
            return "ENGINE_PLANNING_TOOL_UNSUPPORTED：规划登记仅支持原生文档编辑，当前工具不能使用此登记。"
        error = binding_error(event, task)
        if error:
            return error
        required = configured_baselines(root, task, paths)
        absent = set(required) - set(task.get("baseline", []))
        if absent:
            return "ENGINE_BASELINE_REQUIRED：任务遗漏配置基线：" + ", ".join(sorted(absent))
        # status 的 missing 还含验证/评审终态缺项，实施阶段不能据此拒绝合法编码。
        readiness_missing = [item for item in task.get("missing", []) if item not in {"review", "checks"}]
        if readiness_missing:
            message = "ENGINE_NOT_READY：" + ", ".join(readiness_missing)
            if os.environ.get("WORKFLOW_HOST") == "cursor" and "baseline" in readiness_missing:
                message += "。请使用 CLI read-baseline 登记当前实施轮次的基线。"
            return message
        if task.get("state") != "implementing":
            return "ENGINE_STATE_DENIED：仅 implementing 允许实施写入；评审后请新轮次，失败/失效请 CLI repair。"
        if paths and any(not any(p == scope or p.startswith(scope.rstrip("/") + "/") or scope == "." for scope in task.get("scope", [])) for p in paths):
            return "ENGINE_SCOPE_DENIED：目标不在批准任务范围内。"
        return None
    except Exception as exc:
        return "ENGINE_GATE_ERROR：写入已拒绝：" + str(exc)


def post_tool(event):
    """不把普通工具结果或模型代答当人工确认，能力不足时展示 CLI 入口。"""
    CURRENT_EVENT.set(event)
    if os.environ.get("WORKFLOW_HOST") == "cursor":
        if event.get("tool_name") in {"Read", "ReadFile"}:
            return None
        if event.get("tool_name") in {"AskQuestion", "AskUserQuestion", "ExitPlanMode"}:
            return CONFIRM_HELP if "workflow-confirm:" in confirmation_markers(event)[0] else None
    if event.get("tool_name") in {"AskUserQuestion", "ExitPlanMode"} or native_confirmation_host(event) == "codex":
        return complete_confirmation(event)
    if event.get("tool_name") not in {"Read", "ReadFile"}:
        return None
    root = project_root(event.get("cwd"))
    if root is None:
        return None
    paths = targets(event, root)
    if not paths:
        return None
    # 只处理配置基线；CLI read-baseline 自行输出正文并登记其他显式任务基线。
    config = load(root)
    patterns = [rule.split(" => ", 1)[0] for rule in config.get("baseline.scoped") or []]
    if paths[0] not in resolve_baselines(root, [*paths, *patterns], config):
        return None
    response = event.get("tool_response")
    if not isinstance(response, dict) or response.get("is_error") or response.get("error"):
        return "ENGINE_BASELINE_UNREAD：没有成功完整正文；请使用 CLI read-baseline。"
    file = response.get("file")
    if not isinstance(file, dict) or not isinstance(file.get("content"), str):
        return "ENGINE_BASELINE_UNREAD：宿主读取 schema 不受支持；请使用 CLI read-baseline。"
    with (root / paths[0]).open("rb") as handle:
        data = handle.read(1048577)
    if len(data) > 1048576:
        return "ENGINE_BASELINE_UNREAD：正文超过 1MiB；请使用 CLI read-baseline。"
    if (file.get("content").encode("utf-8") != data or file.get("startLine") != 1 or
            file.get("numLines") != file.get("totalLines") or not isinstance(file.get("totalLines"), int)):
        return "ENGINE_BASELINE_UNREAD：正文截断或版本不匹配；请使用 CLI read-baseline。"
    task = load_task(root)
    error = binding_error(event, task)
    if error:
        return error
    from workflow_engine.engine import Engine
    from workflow_engine_cli import default_db
    receipt = dict(path=paths[0], sha256=hashlib.sha256(data).hexdigest(), bytes_read=len(data), complete=True,
                   executor=next(r for r in task["rounds"] if r["id"] == task["current_round"])["executor"], session_id=event["session_id"], round_id=task["current_round"])
    Engine(root, default_db(root)).register_baseline(task["id"], task["version"], str(uuid.uuid4()), receipt)
    return "ENGINE_BASELINE_RECORDED：" + paths[0]


def card_reconcile_message(root, db=None):
    """SessionStart 时按任务卡结案状态自动关闭未开工本地任务，已开工冲突只提示不改库。"""
    from workflow_engine.engine import Engine
    from workflow_engine_cli import default_db

    target = Path(db) if db is not None else default_db(root)
    if target.is_symlink() or not target.is_file():
        return None
    try:
        result = Engine(root, target).reconcile_cards()
    except Exception as exc:
        return "ENGINE_CARD_RECONCILE_ERROR：" + str(exc)
    parts = []
    closed = result.get("closed") or []
    if closed:
        items = "、".join(
            f"{item['id']}（{item.get('status') or ('已勾选完成' if item.get('checked') else '')}）"
            for item in closed
        )
        parts.append("ENGINE_CARD_RECONCILED：任务卡已结案，已自动关闭本地未开工任务 " + items)
    conflicts = result.get("conflicts") or []
    if conflicts:
        items = "、".join(
            f"{item['id']}（本地 {item['state']}，任务卡 {item.get('status') or ('已勾选完成' if item.get('checked') else '')}）"
            for item in conflicts
        )
        parts.append("ENGINE_CARD_CONFLICT：任务卡已结案但本地已开工，需用户决定退回新轮次/拆新任务/放弃：" + items)
    return "；".join(parts) if parts else None


def _context_body(event, root):
    try:
        from workflow_planning_cli import read_record
        planning = read_record(root, event.get("session_id"))
        if planning:
            return "ENGINE_PLANNING：" + json.dumps({k: planning[k] for k in ("operation", "paths", "expires_at")}, ensure_ascii=False) + "；结束或交接前 CLI close，不授权产品实施。"
        task = load_task(root)
        error = binding_error(event, task)
        if error:
            return error
        message = "ENGINE_STATE：" + json.dumps({k: task.get(k) for k in ("id", "current_round", "state", "missing")}, ensure_ascii=False)
        if task.get("state") == "review_passed":
            message += "；Agent 双轴评审通过，待人工验收（非可信签署）。"
        return message
    except Exception as exc:
        if "ENGINE_TASK_UNBOUND" in str(exc):
            return "ENGINE_TASK_UNBOUND：只读调查无需任务；可调用 init / prd-breakdown 登记规划，或 dashboard 管理服务；产品实施须由 Agent 先 CLI list --active 查已有任务并 bind-executor，或用 prepare 建卡绑会话（可加 --request-tier 发起定档）并满足实施门槛，不要让用户外部手动绑定。"
        return str(exc) + "；请核对任务状态及绑定，规划使用独立 planning 入口。"


def context(event):
    """阶段边界汇总权威缺项，评审通过不等于人工验收。"""
    CURRENT_EVENT.set(event)
    root = project_root(event.get("cwd"))
    if root is None:
        return None
    if event.get("hook_event_name") == "UserPromptSubmit":
        return chat_confirmation(event, root)
    if event.get("hook_event_name") == "PostToolUse":
        return post_tool(event)
    notice = card_reconcile_message(root) if event.get("hook_event_name") == "SessionStart" else None
    base = _context_body(event, root)
    return "\n".join(item for item in (notice, base) if item) or None
