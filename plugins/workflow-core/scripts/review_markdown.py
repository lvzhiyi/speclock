"""将任务状态、提案与审批材料渲染为可读 Markdown，并安全写入状态审阅目录。"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid

TIER_NAMES = {'light': '轻量档', 'standard': '标准档', 'full': '完整档'}

ACTION_TITLES = {
    'approve-proposal': '方案审批审阅',
    'confirm-tier': '档位确认审阅',
    'confirm-plan': '检查计划确认审阅',
    'return-task': '任务退回审阅',
}

ACTION_LABELS = {
    'approve-proposal': '完整档方案批准',
    'confirm-tier': '档位确认',
    'confirm-plan': '检查计划确认',
    'return-task': '任务退回',
}

MISSING_LABELS = {
    'goal': '任务目标未明确',
    'scope': '任务范围未明确',
    'source': '需求来源未明确',
    'acceptance': '验收标准未明确',
    'dependencies': '依赖尚未就绪',
    'tier_confirmation': '档位尚未确认',
    'approval': '方案尚未批准',
    'steps': '实施步骤尚未就绪',
    'proposal': '方案信息不完整',
    'executor_binding': '执行者尚未绑定',
    'baseline': '基线尚未完成有效读取',
    'verify_config': '验证配置尚未就绪',
    'checks': '当前验证尚未通过',
    'review': '当前双轴评审尚未通过',
    'snapshot': '证据快照已失效',
    'plan_confirmation': '检查计划尚未确认',
}

_PROPOSAL_SECTIONS = (
    ('goal', '方案目标'),
    ('design', '技术设计'),
    ('scope', '方案范围'),
    ('impact', '影响范围'),
    ('risk', '风险与边界'),
    ('rollback', '回滚方案'),
    ('acceptance', '方案验收'),
)


def _cell(value):
    text = '' if value is None else str(value)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('|', '\\|').replace('\n', '<br>')
    return text


def _tier_label(tier):
    if not tier:
        return '未设置'
    name = TIER_NAMES.get(tier)
    return f'{name} ({tier})' if name else str(tier)


def _missing_label(item):
    label = MISSING_LABELS.get(item)
    return f'{label} ({item})' if label else str(item)


def _format_scalar(value):
    if value is None:
        return '（无）'
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip()
    return text if text else '（无）'


def _format_block(value, indent=0):
    prefix = '  ' * indent
    if value is None or value == '' or value == [] or value == {}:
        return [f'{prefix}（无）']
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                summary = ', '.join(f'{k}: {v}' for k, v in item.items())
                lines.append(f'{prefix}- {summary}' if summary else f'{prefix}- （空对象）')
            elif isinstance(item, list):
                lines.append(f'{prefix}-')
                lines.extend(_format_block(item, indent + 1))
            else:
                lines.append(f'{prefix}- {_format_scalar(item)}')
        return lines
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (list, dict)) and item:
                lines.append(f'{prefix}- **{key}**：')
                lines.extend(_format_block(item, indent + 1))
            else:
                lines.append(f'{prefix}- **{key}**：{_format_scalar(item)}')
        return lines
    text = str(value).replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        return [f'{prefix}（无）']
    return [f'{prefix}{line}' if line else '' for line in text.split('\n')]


def _current_round(task):
    rounds = task.get('rounds')
    if not isinstance(rounds, list) or not rounds:
        return None
    current_id = task.get('current_round')
    if current_id:
        for item in rounds:
            if isinstance(item, dict) and item.get('id') == current_id:
                return item
    return rounds[-1] if isinstance(rounds[-1], dict) else None


def _render_metadata(task, action, actor, reason):
    rows = []
    if action:
        rows.append(('操作', f'{ACTION_LABELS.get(action, action)} ({action})'))
    rows.append(('任务 ID', f"`{task.get('id', '')}`"))
    rows.append(('档位', _tier_label(task.get('tier'))))
    state = task.get('state') or '未知'
    phase = task.get('phase')
    status_text = f'v{task.get("version", "?")} · {state}' + (f' / {phase}' if phase else '')
    rows.append(('当前版本 / 状态', status_text))
    if actor:
        rows.append(('操作者', actor))
    if reason:
        rows.append(('原因', reason))
    card = task.get('card')
    if isinstance(card, dict) and (card.get('id') or card.get('path')):
        card_text = f"{card.get('id', '')} (`{card.get('path', '')}`)" if card.get('path') else str(card.get('id', ''))
        rows.append(('关联任务卡', card_text))
    if task.get('control_digest'):
        rows.append(('控制摘要', f"`{task['control_digest']}`"))
    elif task.get('plan_digest'):
        rows.append(('计划摘要', f"`{task['plan_digest']}`"))
    if task.get('root'):
        rows.append(('项目根目录', f"`{task['root']}`"))

    lines = ['| 字段 | 内容 |', '| --- | --- |']
    for key, value in rows:
        lines.append(f'| {_cell(key)} | {_cell(value)} |')
    return lines


def _mismatch_warnings(task, action, digest, expected_version):
    notes = []
    if expected_version is not None and task.get('version') != expected_version:
        notes.append(f"传入版本号 `v{expected_version}` 与任务当前版本 `v{task.get('version')}` 不一致")
    if action == 'approve-proposal' and digest and digest != task.get('control_digest'):
        notes.append(f"传入摘要 `{digest}` 与当前控制摘要 `{task.get('control_digest')}` 不一致")
    if action == 'confirm-plan' and digest and digest != task.get('plan_digest'):
        notes.append(f"传入摘要 `{digest}` 与当前计划摘要 `{task.get('plan_digest')}` 不一致")
    if not notes:
        return []
    return [f"> ⚠️ 注意：{'；'.join(notes)}。确认时将由引擎按实际版本与摘要校验。"]


def _render_goal_section(task):
    lines = ['## 目标与来源', '']
    has_any = False
    for key, label in (('goal', '任务目标'), ('source', '需求来源'), ('note', '补充说明')):
        if key in task and task[key] not in (None, ''):
            has_any = True
            lines.append(f'- **{label}**：')
            lines.extend(_format_block(task[key], indent=1))
    if not has_any:
        lines.append('（无目标与来源信息）')
    return lines


def _render_proposal_section(task):
    proposal = task.get('proposal')
    lines = ['## 方案提案与技术设计', '']
    if not isinstance(proposal, dict) or not proposal:
        if task.get('tier') == 'full':
            lines.append('> ⚠️ 尚未登记完整方案提案。')
        else:
            lines.append('（当前任务未登记单独方案提案）')
        return lines

    seen = set()
    for key, label in _PROPOSAL_SECTIONS:
        if key in proposal:
            seen.add(key)
            lines.append(f'### {label}')
            lines.append('')
            lines.extend(_format_block(proposal[key]))
            lines.append('')
    for key, value in proposal.items():
        if key in seen:
            continue
        lines.append(f'### {key}')
        lines.append('')
        lines.extend(_format_block(value))
        lines.append('')
    while lines and lines[-1] == '':
        lines.pop()
    return lines


def _render_acceptance_section(task):
    lines = ['## 验收标准', '']
    acceptance = task.get('acceptance')
    if isinstance(acceptance, list) and acceptance:
        for index, item in enumerate(acceptance, 1):
            prefix = f'{index}. '
            text = _format_scalar(item).replace('\r\n', '\n').replace('\r', '\n')
            parts = text.split('\n')
            lines.append(prefix + parts[0])
            indent = ' ' * len(prefix)
            for extra in parts[1:]:
                lines.append(f'{indent}{extra}' if extra else '')
    else:
        lines.append('（无验收标准）')
    return lines


def _render_scope_section(task):
    lines = ['## 实施范围与前置条件', '']
    scope = task.get('scope')
    lines.append('### 实施范围')
    if isinstance(scope, list) and scope:
        for item in scope:
            lines.append(f'- `{item}`')
    elif scope:
        lines.extend(_format_block(scope))
    else:
        lines.append('（未指定范围）')
    lines.append('')

    baseline = task.get('baseline')
    lines.append('### 必读基线')
    if isinstance(baseline, list) and baseline:
        for item in baseline:
            lines.append(f'- `{item}`')
    elif baseline:
        lines.extend(_format_block(baseline))
    else:
        lines.append('（无必读基线）')
    lines.append('')

    dependencies = task.get('dependencies')
    lines.append('### 前置依赖')
    if isinstance(dependencies, list) and dependencies:
        for dep in dependencies:
            if isinstance(dep, dict):
                dep_id = dep.get('id', '?')
                dep_status = dep.get('status', 'unknown')
                status_text = '已完成 (done)' if dep_status == 'done' else f'待处理 ({dep_status})'
                lines.append(f'- **{dep_id}**：{status_text}')
            else:
                lines.append(f'- {_format_scalar(dep)}')
    elif dependencies == []:
        lines.append('（无前置依赖）')
    else:
        lines.append('（未声明依赖）')
    return lines


def _render_steps_section(task):
    lines = ['## 实施步骤', '']
    active_round = _current_round(task)
    todos = active_round.get('todos') if active_round else None
    if isinstance(todos, list) and todos:
        for todo in todos:
            done = todo.get('status') == 'done'
            mark = 'x' if done else ' '
            tags = []
            if todo.get('refinement'):
                tags.append('细化')
            if todo.get('repair'):
                tags.append('修复')
            tag_text = f" [{'/'.join(tags)}]" if tags else ''
            summary = f" — {todo['summary']}" if todo.get('summary') else ''
            lines.append(f"- [{mark}] `{todo.get('id', '')}` {todo.get('title', '')}{tag_text}{summary}")
        return lines

    steps = task.get('steps')
    if isinstance(steps, list) and steps:
        for step in steps:
            if isinstance(step, dict):
                lines.append(f"- [ ] `{step.get('id', '')}` {step.get('title', '')}")
            else:
                lines.append(f'- [ ] {_format_scalar(step)}')
        return lines

    lines.append('（无实施步骤）')
    return lines


def _render_plan_section(task):
    lines = ['## 验证计划', '']
    plan = task.get('plan')
    checks = plan.get('checks') if isinstance(plan, dict) else None
    if not isinstance(checks, list) or not checks:
        lines.append('（无验证命令）')
        return lines

    for check in checks:
        if not isinstance(check, dict):
            lines.append(f'- {_format_scalar(check)}')
            continue
        check_id = check.get('id', 'check')
        covers = check.get('covers') or []
        covers_text = ', '.join(str(c) for c in covers) if isinstance(covers, list) else str(covers)
        cwd = check.get('cwd', '.')
        timeout = check.get('timeout', '-')
        lines.append(f'- **{check_id}**（覆盖：`{covers_text}`；目录：`{cwd}`；超时：{timeout}s）')
        argv = check.get('argv')
        if isinstance(argv, list) and argv:
            cmd = shlex.join(str(part) for part in argv)
            lines.append('  ```sh')
            lines.append(f'  {cmd}')
            lines.append('  ```')
    return lines


def _render_gate_section(task):
    lines = ['## 当前门禁与证据状态', '']
    missing = task.get('missing') or []
    if missing:
        lines.append('**待完成缺项：**')
        for item in missing:
            lines.append(f'- {_missing_label(item)}')
    else:
        lines.append('所有门禁条件已满足。')

    active_round = _current_round(task)
    if not active_round:
        return lines

    lines.append('')
    executor = active_round.get('executor')
    session_id = active_round.get('session_id')
    if executor or session_id:
        lines.append(f"- **执行者绑定**：`{executor or '-'}`（会话 `{session_id or '-'}`，绑定代次 {active_round.get('binding_version', 0)}）")
    else:
        lines.append('- **执行者绑定**：未绑定')

    digest = task.get('control_digest')
    evidences = [
        item for item in active_round.get('evidence', [])
        if isinstance(item, dict) and item.get('valid', True) and (not digest or item.get('control_digest') == digest)
    ]
    tier_evs = [item for item in evidences if item.get('kind') == 'tier_confirmation']
    approval_evs = [item for item in evidences if item.get('kind') == 'approval']
    baseline_paths = sorted({
        item.get('data', {}).get('path')
        for item in evidences
        if item.get('kind') == 'baseline' and isinstance(item.get('data'), dict) and item['data'].get('path')
    })

    if tier_evs:
        actor = tier_evs[-1].get('data', {}).get('actor', '')
        lines.append(f'- **档位确认**：已记录（{actor}）')
    else:
        lines.append('- **档位确认**：未确认')

    if task.get('tier') == 'full':
        if approval_evs:
            actor = approval_evs[-1].get('data', {}).get('actor', '')
            lines.append(f'- **方案批准**：已记录（{actor}）')
        else:
            lines.append('- **方案批准**：待批准')

    declared_baselines = task.get('baseline') or []
    if declared_baselines:
        joined = ', '.join(f'`{path}`' for path in baseline_paths) if baseline_paths else '无'
        lines.append(f'- **基线阅读**：{len(baseline_paths)}/{len(declared_baselines)} 份已登记（{joined}）')
    return lines


def render_review_markdown(task, *, action=None, actor=None, digest=None, reason=None, expected_version=None):
    """将引擎 Task 字典渲染为可读 Markdown 审阅文档，兼容 v2 与 legacy v1。"""
    task_id = task.get('id', '未命名任务')
    if action:
        title = f"{ACTION_TITLES.get(action, action)}：{task_id}"
    else:
        title = f'任务方案与状态：{task_id}'

    sections = [f'# {title}', '']
    sections.extend(_render_metadata(task, action, actor, reason))

    warnings = _mismatch_warnings(task, action, digest, expected_version)
    if warnings:
        sections.append('')
        sections.extend(warnings)

    for builder in (
        _render_goal_section,
        _render_proposal_section,
        _render_acceptance_section,
        _render_scope_section,
        _render_steps_section,
        _render_plan_section,
        _render_gate_section,
    ):
        sections.append('')
        sections.extend(builder(task))

    if action is not None:
        sections.extend([
            '',
            '---',
            '> 审阅完成后，请返回终端输入 `confirm` 完成本次确认；如需取消，请直接按回车或 `Ctrl+C`。',
        ])

    return '\n'.join(sections) + '\n'


def _safe_task_stem(task_id):
    raw_id = str(task_id or 'task')
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', raw_id).strip('._') or 'task'
    truncated = len(cleaned) > 80
    safe_id = cleaned[:80].rstrip('._') or 'task'
    if safe_id != raw_id or truncated:
        suffix = hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:8]
        return f'{safe_id}-{suffix}'
    return safe_id


def write_review_markdown(state_dir, root, task, markdown, *, action=None):
    """把审阅 Markdown 原子写入状态目录的 reviews/ 下，禁止落入受管源码或符号链接。"""
    from workflow_engine.model import EngineError
    from workflow_engine.state_dir import STATE_DIRNAME, ensure_internal_state_dir

    resolved_root = Path(root).resolve()
    speclock_dir = resolved_root / STATE_DIRNAME
    if speclock_dir.is_symlink():
        raise ValueError('状态目录不可为符号链接')
    raw_state = Path(state_dir)
    if raw_state.is_symlink():
        raise ValueError('状态目录不可为符号链接')
    resolved_state = raw_state.resolve()
    reviews_dir = resolved_state / 'reviews'
    allowed_internal = (resolved_state == speclock_dir and reviews_dir == speclock_dir / 'reviews')

    if not allowed_internal and (reviews_dir == resolved_root or resolved_root in reviews_dir.parents or reviews_dir in resolved_root.parents):
        raise ValueError('审阅目录不得位于项目根目录内或覆盖项目根目录')
    if reviews_dir.is_symlink():
        raise ValueError('审阅目录不可为符号链接')
    if reviews_dir.exists() and not reviews_dir.is_dir():
        raise ValueError('审阅目录路径已存在且不是目录')

    if allowed_internal:
        try:
            ensure_internal_state_dir(resolved_root)
        except EngineError as exc:
            raise ValueError(str(exc)) from exc

    reviews_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(str(reviews_dir), 0o700)

    resolved_reviews = reviews_dir.resolve()
    allowed_internal_resolved = (resolved_reviews == speclock_dir / 'reviews')
    if not allowed_internal_resolved and (resolved_reviews == resolved_root or resolved_root in resolved_reviews.parents or resolved_reviews in resolved_root.parents):
        raise ValueError('审阅目录解析后不得落入项目根目录')

    safe_id = _safe_task_stem(task.get('id', 'task'))
    version = task.get('version', 'unknown')
    stem = f'{safe_id}-v{version}-{action}' if action else f'{safe_id}-v{version}'
    target = reviews_dir / f'{stem}.md'

    if target.is_symlink():
        raise ValueError('审阅文件目标不可为符号链接')
    if target.exists() and not target.is_file():
        raise ValueError('审阅文件目标不是普通文件')

    temp_path = reviews_dir / f'.{stem}.{uuid.uuid4().hex}.tmp'
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        descriptor = os.open(str(temp_path), flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
        except OSError:
            pass
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(markdown)
            if not markdown.endswith('\n'):
                handle.write('\n')
        if target.is_symlink():
            raise ValueError('审阅文件目标不可为符号链接')
        os.replace(str(temp_path), str(target))
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass
    return target


def _is_cursor_env():
    if os.environ.get('WORKFLOW_HOST') == 'cursor':
        return True
    if os.environ.get('TERM_PROGRAM') == 'cursor':
        return True
    if 'cursor' in os.environ.get('VSCODE_GIT_ASKPASS_MAIN', '').lower():
        return True
    return bool(os.environ.get('CURSOR_TRACE_ID') or os.environ.get('CURSOR_AGENT'))


def _is_vscode_env():
    if _is_cursor_env():
        return False
    return os.environ.get('TERM_PROGRAM') == 'vscode' or bool(os.environ.get('VSCODE_IPC_HOOK_CLI'))


def open_review_file(path):
    """按宿主/系统白名单非阻塞打开审阅 Markdown，返回 (opener_name, error_message)。"""
    disabled = os.environ.get('WORKFLOW_NO_OPEN', '').strip().lower()
    if disabled in ('1', 'true', 'yes'):
        return None, '已由 WORKFLOW_NO_OPEN 禁用自动打开'

    target = Path(path)
    if target.is_symlink() or not target.is_file():
        return None, '审阅文件不存在或为符号链接'

    candidates = []
    if _is_cursor_env():
        cursor_bin = shutil.which('cursor')
        if cursor_bin:
            candidates.append(('cursor', [cursor_bin, '--reuse-window', str(target)]))
    elif _is_vscode_env():
        code_bin = shutil.which('code')
        if code_bin:
            candidates.append(('code', [code_bin, '--reuse-window', str(target)]))

    if sys.platform == 'darwin':
        open_bin = shutil.which('open') or ('/usr/bin/open' if Path('/usr/bin/open').is_file() else None)
        if open_bin:
            candidates.append(('open', [open_bin, str(target)]))
    elif sys.platform.startswith('linux'):
        if os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
            xdg_bin = shutil.which('xdg-open')
            if xdg_bin:
                candidates.append(('xdg-open', [xdg_bin, str(target)]))
    elif os.name == 'nt' and hasattr(os, 'startfile'):
        candidates.append(('startfile', None))

    if not candidates:
        return None, '未找到可用的图形界面或编辑器打开器'

    last_error = None
    for name, argv in candidates:
        try:
            if name == 'startfile':
                os.startfile(str(target))
                return name, None
            if name == 'xdg-open':
                subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return name, None
            proc = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0:
                return name, None
            last_error = f'{name} 退出码 {proc.returncode}'
        except (OSError, subprocess.SubprocessError) as exc:
            last_error = str(exc)

    return None, last_error or '打开审阅文件失败'


def _preview_text(value, limit=120):
    if isinstance(value, list):
        text = '；'.join(_format_scalar(item) for item in value)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = _format_scalar(value)
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + '…'


def render_terminal_summary(
    task,
    *,
    action,
    markdown,
    review_path=None,
    opened_with=None,
    open_error=None,
    write_error=None,
    actor=None,
    reason=None,
):
    """已弹外部窗口时展示紧凑摘要；未弹出时直接展示完整 Markdown 正文。"""
    if not opened_with:
        notices = []
        if write_error:
            notices.append(f'注意：审阅文档写入失败（{write_error}），以下在终端直接展示完整 Markdown 审阅稿：')
        elif review_path:
            reason_note = f'（{open_error}）' if open_error else ''
            notices.append(f'审阅文档已生成：{review_path}{reason_note}')
            notices.append('已在终端展示完整 Markdown 审阅稿：')
        else:
            notices.append('以下在终端展示完整 Markdown 审阅稿：')
        return '\n'.join(notices) + '\n\n' + markdown

    title = ACTION_TITLES.get(action, action)
    lines = [f"=== {title}：{task.get('id', '')} ==="]
    if review_path:
        lines.append(f'审阅文档已打开（{opened_with}）：{review_path}')
    meta = [
        f"档位：{_tier_label(task.get('tier'))}",
        f"版本：v{task.get('version', '?')}",
        f"状态：{task.get('state', '未知')}",
    ]
    if actor:
        meta.append(f'操作者：{actor}')
    lines.append(' | '.join(meta))
    if reason:
        lines.append(f'原因：{reason}')
    if task.get('goal'):
        lines.append(f"目标：{_preview_text(task['goal'], 160)}")

    scope = task.get('scope') or []
    if isinstance(scope, list) and scope:
        preview = ', '.join(str(item) for item in scope[:5])
        suffix = f' 等共 {len(scope)} 项' if len(scope) > 5 else ''
        lines.append(f'范围（{len(scope)} 项）：{preview}{suffix}')

    proposal = task.get('proposal')
    if isinstance(proposal, dict) and proposal:
        if proposal.get('design'):
            lines.append(f"技术设计：{_preview_text(proposal['design'], 140)}")
        if proposal.get('risk'):
            lines.append(f"风险与边界：{_preview_text(proposal['risk'], 120)}")

    active_round = _current_round(task)
    steps = (active_round.get('todos') if active_round else None) or task.get('steps') or []
    if isinstance(steps, list) and steps:
        lines.append(f'实施步骤（{len(steps)} 项）：')
        for step in steps[:8]:
            if isinstance(step, dict):
                lines.append(f"  - {step.get('id', '')}: {step.get('title', '')}")
        if len(steps) > 8:
            lines.append(f'  - ... 其余 {len(steps) - 8} 项见审阅文档')

    acceptance = task.get('acceptance') or []
    checks = (task.get('plan') or {}).get('checks') or []
    lines.append(f'验收标准：{len(acceptance)} 条 | 验证命令：{len(checks)} 条')

    missing = task.get('missing') or []
    if missing:
        lines.append('待补缺项：' + '、'.join(_missing_label(item) for item in missing))
    return '\n'.join(lines) + '\n'


def render_confirmation_receipt(action, task, *, progress=None, review_path=None):
    """确认完成后输出简洁 Markdown 回执，替代密密麻麻的单行 JSON。"""
    label = ACTION_LABELS.get(action, action)
    lines = [
        f'## ✅ {label}已登记',
        '',
        f"- 任务：`{task.get('id', '')}`（{_tier_label(task.get('tier'))}）",
        f"- 版本：v{task.get('version', '?')}",
        f"- 状态：{task.get('state', '未知')} / {task.get('phase', '未知')}",
    ]
    if task.get('control_digest'):
        digest = task['control_digest']
        lines.append(f'- 控制摘要：`{digest[:12]}`（`{digest}`）')
    elif task.get('plan_digest'):
        digest = task['plan_digest']
        lines.append(f'- 计划摘要：`{digest[:12]}`（`{digest}`）')

    if isinstance(progress, dict) and progress.get('text'):
        lines.append(f"- 进度：{progress['text']}")

    missing = task.get('missing') or []
    if missing:
        lines.append('- 待完成前置：' + '、'.join(_missing_label(item) for item in missing))
    else:
        lines.append('- 待完成前置：无（已全部就绪）')

    readiness_missing = [item for item in missing if item not in ('checks', 'review')]
    if task.get('state') == 'created':
        if 'approval' in readiness_missing:
            lines.append('- 下一步：补齐/核对完整档方案后执行 `approve-proposal`')
        elif not readiness_missing:
            lines.append('- 下一步：可执行 `begin`（或绑定执行者并登记基线后 `start`）进入实施')
        else:
            lines.append('- 下一步：补齐上述前置缺项（' + ', '.join(readiness_missing) + '）')

    if review_path:
        lines.append(f'- 审阅文档：`{review_path}`')

    lines.extend(['', '> 如需完整原始 JSON，请追加 `--json` 或通过管道调用。'])
    return '\n'.join(lines)
