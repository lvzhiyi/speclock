#!/usr/bin/env python3
"""任务工作流 JSON 入口；人工确认是流程证据，不是身份签名。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

TIER_MAP = {
    '轻量': 'light',
    '标准': 'standard',
    '完整': 'full',
    'light': 'light',
    'standard': 'standard',
    'full': 'full',
}
CONFIRM_ACTIONS = ('confirm-plan', 'confirm-tier', 'approve-proposal', 'return-task')


class ArgumentError(Exception):
    """参数错误也输出 JSON。"""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentError(message)


def default_db(root):
    """状态不进入纳管源码指纹。"""
    from workflow_engine.state_dir import state_dir
    return state_dir(root) / 'state.sqlite'


def parser():
    result = Parser(description=__doc__)
    result.add_argument('--root', default='.')
    result.add_argument('--db')
    commands = result.add_subparsers(dest='action', required=True, parser_class=Parser)
    hooks_command = commands.add_parser('check-hooks', help='前置检查当前会话的 SpecLock Hook 是否已授权并运行')
    hooks_command.add_argument('--session', default=None, help='可选：当前宿主会话 ID（Codex 默认读取 CODEX_THREAD_ID，Claude Code 读取 CLAUDE_SESSION_ID，Cursor 读取 CURSOR_CONVERSATION_ID）')
    list_command = commands.add_parser('list')
    list_command.add_argument('--active', action='store_true', help='仅显示未终态的活动任务')
    list_command.add_argument('--session', default=None, help='可选：当前宿主会话 ID，用于内联钩子状态检查')
    commands.add_parser('reconcile-cards', help='按任务卡结案状态自动关闭未开工本地任务')
    reads = ('status', 'snapshot', 'history', 'progress', 'render-md')
    actions = reads + ('prepare', 'begin', 'create', 'start', 'resume', 'run', 'complete', 'cancel', 'recover', 'confirm-plan', 'confirm-tier', 'request-confirmation', 'approve-proposal', 'read-baseline', 'register-baseline', 'record-tdd', 'finish-step', 'finish-implementation', 'review', 'sync-review-card', 'update-task', 'adopt-protocol', 'bind-executor', 'repair', 'refine-steps', 'return-task')
    for action in actions:
        command = commands.add_parser(action)
        command.add_argument('--task', required=True)
        if action in ('status', 'resume'):
            command.add_argument('--session', default=None, help='可选：当前宿主会话 ID，用于内联钩子状态检查')
        if action not in reads:
            command.add_argument('--request', default=None, help='幂等请求 ID；省略时自动生成')
        if action not in reads + ('create', 'prepare', 'begin'):
            command.add_argument('--version', type=int, required=True)
        if action == 'begin':
            command.add_argument('--version', type=int, default=None, help='可选 CAS 版本号；省略时按当前版本检查')
        if action in ('create', 'prepare'):
            command.add_argument('--tier', choices=tuple(TIER_MAP.keys()), required=True)
            command.add_argument('--acceptance', action='append', required=True)
            for name in ('plan', 'details'):
                group = command.add_mutually_exclusive_group(required=(action == 'create' or name == 'details'))
                group.add_argument('--' + name)
                group.add_argument('--' + name + '-json')
        if action == 'prepare':
            command.add_argument('--executor', default=None, help='可选：同时绑定执行者')
            command.add_argument('--session', default=None, help='可选：同时绑定宿主会话')
            command.add_argument('--request-tier', action='store_true', help='可选：同时登记聊天定档请求（需配合 --executor 和 --session）')
        if action == 'begin':
            command.add_argument('--executor', required=True)
            command.add_argument('--session', required=True)
            command.add_argument('--max-bytes', type=int, default=65536)
            tdd_group = command.add_mutually_exclusive_group(required=False)
            tdd_group.add_argument('--tdd')
            tdd_group.add_argument('--tdd-json')
        if action in ('confirm-plan', 'approve-proposal'):
            command.add_argument('--digest', required=True)
        if action in ('confirm-tier', 'approve-proposal', 'return-task'):
            command.add_argument('--actor', required=True)
        if action in ('register-baseline', 'record-tdd', 'review', 'update-task', 'adopt-protocol', 'repair', 'refine-steps'):
            group = command.add_mutually_exclusive_group(required=True)
            group.add_argument('--file')
            group.add_argument('--file-json')
        if action in ('read-baseline', 'bind-executor'):
            command.add_argument('--executor', required=True)
        if action in ('read-baseline', 'bind-executor', 'request-confirmation'):
            command.add_argument('--session', required=True)
        if action == 'request-confirmation':
            command.add_argument('--kind', choices=('tier_confirmation', 'approval'), required=True)
        if action == 'read-baseline':
            group = command.add_mutually_exclusive_group(required=True)
            group.add_argument('--path', action='append', help='基线路径，可重复指定')
            group.add_argument('--all', action='store_true', help='读取任务声明的全部基线')
            command.add_argument('--max-bytes', type=int, default=65536)
        if action in ('repair', 'refine-steps'):
            command.add_argument('--reason', required=True)
        if action == 'finish-step':
            command.add_argument('--step', required=True)
            command.add_argument('--summary', required=True)
            command.add_argument('--finish-implementation', action='store_true', help='完成步骤后顺带执行 finish-implementation')
        if action == 'return-task':
            command.add_argument('--reason', required=True)
        if action == 'sync-review-card':
            command.add_argument('--round', required=True)
            command.add_argument('--card-path', required=True)
            command.add_argument('--card-id', required=True)
        if action in CONFIRM_ACTIONS:
            command.add_argument('--json', action='store_true', help='以 JSON 格式输出确认结果')
            command.add_argument('--no-open', action='store_true', help='仅在终端展示审阅内容，不自动弹出外部窗口')
        if action == 'render-md':
            command.add_argument('--save', action='store_true', help='将审阅 Markdown 保存到状态目录下的 reviews/')
            command.add_argument('--open', action='store_true', help='保存并尝试在默认应用或编辑器中打开审阅 Markdown')
            command.add_argument('--json', action='store_true', help='以 JSON 格式输出结果')
    return result


def load_json(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def input_json(args, name):
    inline = getattr(args, name + '_json', None)
    return json.loads(inline) if inline is not None else load_json(getattr(args, name))


def human_confirmation(label):
    # 终端交互保留人工流程属性；同用户程序仍可代答，绝非安全认证。
    if not sys.stdin.isatty():
        raise ArgumentError('人工流程确认须在交互终端执行')
    print(label + '，请输入 confirm：', file=sys.stderr, flush=True)
    try:
        answer = input().strip()
    except (EOFError, KeyboardInterrupt):
        raise ArgumentError('已取消人工确认')
    if answer != 'confirm':
        raise ArgumentError('未确认人工流程')


def confirm_with_markdown(args, task, database, root):
    if not sys.stdin.isatty():
        raise ArgumentError('人工流程确认须在交互终端执行')
    from review_markdown import open_review_file, render_review_markdown, render_terminal_summary, write_review_markdown

    markdown = render_review_markdown(
        task,
        action=args.action,
        actor=getattr(args, 'actor', None),
        digest=getattr(args, 'digest', None),
        reason=getattr(args, 'reason', None),
        expected_version=args.version,
    )
    review_path = None
    write_error = None
    try:
        review_path = write_review_markdown(database.parent, root, task, markdown, action=args.action)
    except (OSError, ValueError) as exc:
        write_error = str(exc)

    opened_with = None
    open_error = None
    if review_path is not None:
        if getattr(args, 'no_open', False):
            open_error = '已指定 --no-open'
        else:
            opened_with, open_error = open_review_file(review_path)

    summary = render_terminal_summary(
        task,
        action=args.action,
        markdown=markdown,
        review_path=review_path,
        opened_with=opened_with,
        open_error=open_error,
        write_error=write_error,
        actor=getattr(args, 'actor', None),
        reason=getattr(args, 'reason', None),
    )
    print(summary, file=sys.stderr, flush=True)
    human_confirmation('确认已由人工审阅此操作')
    return review_path


def baseline_document(engine, path, limit):
    data = engine.read_baseline_bytes(path, limit + 1)
    truncated = len(data) > limit
    try:
        content = data[:limit].decode('utf-8', errors='ignore' if truncated else 'strict')
    except UnicodeDecodeError:
        raise ArgumentError(f'{path}：基线正文必须为完整 UTF-8 文本，未登记完整读取')
    return dict(path=path, content=content, truncated=truncated, bytes_read=min(len(data), limit)), data


def baseline_receipt(args, task, document, data):
    return dict(path=document['path'], sha256=hashlib.sha256(data).hexdigest(),
                bytes_read=len(data), complete=True, executor=args.executor,
                session_id=args.session, round_id=task['current_round'])


def collect_baseline_batch(args, engine, task, paths):
    from workflow_engine.model import EngineError

    if not paths or any(path not in task['baseline'] for path in paths):
        raise EngineError('BASELINE_INVALID', '基线清单为空或包含未声明的基线')
    documents = []
    receipts = []
    # 限制整个 documents 数组的 UTF-8 JSON 大小，包括转义和分隔符。
    remaining = args.max_bytes - 2
    for path in paths:
        document, data = baseline_document(engine, path, max(0, remaining))
        remaining -= len(json.dumps(document, ensure_ascii=False).encode('utf-8'))
        if document['truncated'] or remaining < 0:
            raise EngineError('BASELINE_BATCH_LIMIT',
                              f'基线批次超出输出限额（{path}），请用 --path 缩小批次')
        remaining -= 2
        documents.append(document)
        receipts.append(baseline_receipt(args, task, document, data))
    return documents, receipts


def read_baseline_batch(args, engine, task):
    paths = list(dict.fromkeys(task['baseline'] if args.all else args.path))
    documents, receipts = collect_baseline_batch(args, engine, task, paths)
    value = engine.register_baselines(args.task, args.version, args.request, receipts)
    print(json.dumps(dict(ok=True, version=value['version'], documents=documents), ensure_ascii=False))
    return 0


def derive_plan(root, tier_key, acceptance):
    from workflow_engine import config_checks
    from workflow_engine.model import EngineError

    commands, _ = config_checks.configured(root, tier_key)
    if not commands:
        raise EngineError('VERIFY_CONFIG', f'ai-workflow.yaml 未配置 verify.{tier_key}，请补充配置或显式传入 --plan/--plan-json')
    checks = []
    for index, argv in enumerate(commands, 1):
        covers = ['format', 'analyze', 'test'] if index == 1 else ['analyze']
        checks.append({'id': f'check-{index}', 'argv': argv, 'cwd': '.', 'timeout': 300,
                       'covers': covers, 'acceptance': list(acceptance)})
    return {'version': 1, 'checks': checks}


def derive_baselines(root, details):
    from baseline_config import resolve_baselines
    from workflow_config import load as load_config

    paths = resolve_baselines(root, details.get('scope') or [], load_config(root))
    if not paths:
        raise ArgumentError('details.baseline 缺失且 ai-workflow.yaml 未配置 baseline.required')
    return paths


def handle_prepare(args, engine, root, database):
    details = input_json(args, 'details')
    if not isinstance(details, dict):
        raise ArgumentError('details 必须为任务协议 v2 对象，不得为 null')
    if bool(args.executor) != bool(args.session):
        raise ArgumentError('--executor 与 --session 必须成对提供')
    if args.request_tier and not args.session:
        raise ArgumentError('--request-tier 需要同时提供 --executor 与 --session')
    if args.request_tier and args.db and database != default_db(root).resolve():
        raise ArgumentError('聊天确认须与宿主使用同一默认状态库')
    tier_key = TIER_MAP[args.tier]
    if not details.get('baseline'):
        details = dict(details, baseline=derive_baselines(root, details))
    plan = (derive_plan(root, tier_key, args.acceptance)
            if args.plan is None and args.plan_json is None else input_json(args, 'plan'))
    req = args.request
    task = engine.create(args.task, tier_key, args.acceptance, plan, f'{req}:create', details=details)
    if args.executor and args.session:
        task = engine.bind_executor(args.task, task['version'], f'{req}:bind', args.executor, args.session)
    confirmation = None
    if args.request_tier:
        from host_gate import request_chat_confirmation
        confirmation = request_chat_confirmation(
            root, task, task['version'], args.session, 'tier_confirmation', f'{req}:confirm')
    return task, confirmation


def handle_begin(args, engine):
    from workflow_engine.model import EngineError
    from workflow_engine.protocol import readiness

    if not 0 < args.max_bytes <= 1048576:
        raise ArgumentError('max-bytes 必须在 1 到 1048576 之间')
    task = engine.status(args.task)
    if task.get('protocol_version') != 2:
        raise EngineError('PROTOCOL_REQUIRED', '旧任务必须先 adopt-protocol，CLI 不执行旧协议变更')
    if args.version is not None and task['version'] != args.version:
        raise EngineError('VERSION_CONFLICT', '版本不匹配，请重新读取 status')
    if task.get('state') != 'created':
        raise EngineError('INVALID_STATE', f"当前状态 {task.get('state')} 不能执行 begin")
    blockers = [item for item in readiness(task) if item not in ('executor_binding', 'baseline')]
    if blockers:
        raise EngineError('NOT_READY', '任务尚缺前置条件，不能开工：' + ', '.join(blockers))
    req = args.request
    current_round = task['rounds'][-1]
    if current_round.get('executor') != args.executor or current_round.get('session_id') != args.session:
        task = engine.bind_executor(args.task, task['version'], f'{req}:bind', args.executor, args.session)
    documents, receipts = collect_baseline_batch(args, engine, task, list(dict.fromkeys(task['baseline'])))
    task = engine.register_baselines(args.task, task['version'], f'{req}:baseline', receipts)
    task = engine.start(args.task, task['version'], f'{req}:start')
    if args.tdd is not None or args.tdd_json is not None:
        task = engine.record_tdd(args.task, task['version'], f'{req}:tdd', input_json(args, 'tdd'))
    return task, documents


def main(argv=None):
    args = None
    state_target = None
    try:
        args = parser().parse_args(argv)
        if hasattr(args, 'request') and args.request is None:
            args.request = uuid.uuid4().hex
        document = None
        documents = None
        confirmation = None
        review_path = None
        reconcile = None
        from workflow_engine.engine import Engine
        from workflow_engine.state_dir import migrate_legacy
        root = Path(args.root).resolve()
        raw_database = Path(args.db) if args.db else default_db(root)
        state_target = raw_database.parent
        if not args.db and args.action != 'check-hooks':
            migrate_legacy(root)
        if args.action == 'check-hooks':
            from host_gate import hook_precheck_status
            print(json.dumps({'ok': True, 'hooks': hook_precheck_status(root, args.session)}, ensure_ascii=False))
            return 0
        if args.action == 'list':
            from host_gate import hook_precheck_status
            from session_binding import list_tasks
            from workflow_engine.model import EngineError

            try:
                tasks = list_tasks(root, raw_database, active_only=args.active)
            except ValueError as exc:
                message = str(exc)
                code = message.split('：', 1)[0] if '：' in message else 'BLOCKED'
                raise EngineError(code, message) from exc
            print(json.dumps({'ok': True, 'tasks': tasks, 'hooks': hook_precheck_status(root, args.session)}, ensure_ascii=False))
            return 0
        database = raw_database.resolve()
        if args.action == 'reconcile-cards':
            if raw_database.is_symlink():
                from workflow_engine.model import EngineError
                raise EngineError('DB_LOCATION', '数据库不允许符号链接')
            if not database.is_file():
                print(json.dumps({'ok': True, 'closed': [], 'conflicts': []}, ensure_ascii=False))
                return 0
            result = Engine(root, database).reconcile_cards()
            print(json.dumps({'ok': True, **result}, ensure_ascii=False))
            return 0
        if args.action == 'request-confirmation' and args.db and database != default_db(root).resolve():
            raise ArgumentError('聊天确认须与宿主使用同一默认状态库')
        if args.action in ('status', 'snapshot', 'history', 'progress', 'render-md', 'request-confirmation', 'begin') and not database.is_file():
            from workflow_engine.model import EngineError
            raise EngineError('NOT_FOUND', '状态库不存在，未执行初始化')
        engine = Engine(root, database)
        if args.action == 'render-md':
            from review_markdown import format_review_path, open_review_file, render_review_markdown, write_review_markdown

            task = engine.status(args.task)
            markdown = render_review_markdown(task)
            awaiting_approval = task.get('tier') == 'full' and 'approval' in (task.get('missing') or [])
            opened_with = None
            open_error = None
            if args.open or args.save:
                try:
                    review_path = write_review_markdown(database.parent, root, task, markdown)
                except (OSError, ValueError) as exc:
                    raise ArgumentError(str(exc)) from exc
            if args.open and review_path is not None:
                opened_with, open_error = open_review_file(review_path)
            display_path = format_review_path(root, review_path) if review_path is not None else None
            presentation_note = (
                '发起方案批准前，请在聊天回复正文中完整展示以上 Markdown 方案内容并附上审阅稿路径，切勿压缩为简短摘要。'
                if awaiting_approval
                else None
            )
            if args.json:
                payload = {
                    'ok': True,
                    'task_id': task['id'],
                    'version': task['version'],
                    'state': task['state'],
                    'control_digest': task.get('control_digest'),
                    'markdown': markdown,
                }
                if review_path is not None:
                    payload['path'] = str(review_path)
                    payload['display_path'] = display_path
                if presentation_note is not None:
                    payload['presentation_note'] = presentation_note
                if args.open:
                    payload['opened'] = bool(opened_with)
                    payload['opened_with'] = opened_with
                    if open_error:
                        payload['open_error'] = open_error
                print(json.dumps(payload, ensure_ascii=False))
            else:
                if review_path is not None:
                    if args.open:
                        if opened_with:
                            print(f'已保存并在 {opened_with} 中打开：{review_path}', file=sys.stderr, flush=True)
                        else:
                            note = f'（{open_error}）' if open_error else ''
                            print(f'已保存审阅文档：{review_path}{note}', file=sys.stderr, flush=True)
                    else:
                        print(f'已保存审阅文档：{review_path}', file=sys.stderr, flush=True)
                    if awaiting_approval:
                        print(
                            f'提示：发起方案批准前，请在聊天回复正文中完整展示以上 Markdown 方案内容并附上审阅稿路径（{display_path}），切勿压缩为简短摘要。',
                            file=sys.stderr,
                            flush=True,
                        )
                print(markdown, end='' if markdown.endswith('\n') else '\n')
            return 0
        if args.action == 'create':
            details = input_json(args, 'details')
            if not isinstance(details, dict):
                raise ArgumentError('details 必须为任务协议 v2 对象，不得为 null')
            value = engine.create(args.task, TIER_MAP[args.tier], args.acceptance, input_json(args, 'plan'), args.request, details=details)
        elif args.action == 'prepare':
            reconcile = engine.reconcile_cards()
            value, confirmation = handle_prepare(args, engine, root, database)
        elif args.action == 'begin':
            reconcile = engine.reconcile_cards()
            value, documents = handle_begin(args, engine)
        elif args.action == 'progress':
            from agent_progress import project_progress
            value = project_progress(engine.status(args.task))
        elif args.action in ('status', 'snapshot', 'history'):
            value = getattr(engine, args.action)(args.task)
        elif args.action == 'request-confirmation':
            from host_gate import request_chat_confirmation
            value = request_chat_confirmation(root, engine.status(args.task), args.version, args.session, args.kind, args.request)
        else:
            if args.action == 'resume':
                reconcile = engine.reconcile_cards()
            task = engine.status(args.task)
            if task.get('protocol_version') != 2 and args.action != 'adopt-protocol':
                from workflow_engine.model import EngineError
                raise EngineError('PROTOCOL_REQUIRED', '旧任务必须先 adopt-protocol，CLI 不执行旧协议变更')
            operation = getattr(engine, args.action.replace('-', '_'), None)
            parameters = [args.task, args.version, args.request]
            if args.action in CONFIRM_ACTIONS:
                review_path = confirm_with_markdown(args, task, database, root)
            if args.action == 'confirm-plan':
                parameters.append(args.digest)
            elif args.action == 'confirm-tier':
                parameters.append(args.actor)
            elif args.action == 'approve-proposal':
                parameters += [args.actor, args.digest]
            elif args.action == 'return-task':
                parameters += [args.reason, args.actor]
            elif args.action == 'bind-executor':
                parameters += [args.executor, args.session]
            elif args.action in ('register-baseline', 'record-tdd', 'review', 'update-task', 'adopt-protocol', 'repair', 'refine-steps'):
                parameters.append(input_json(args, 'file'))
                if args.action in ('repair', 'refine-steps'):
                    parameters.append(args.reason)
            elif args.action == 'finish-step':
                parameters += [args.step, args.summary]
            elif args.action == 'sync-review-card':
                parameters += [args.round, {'path': args.card_path, 'id': args.card_id}]
            elif args.action == 'read-baseline':
                if not 0 < args.max_bytes <= 1048576:
                    raise ArgumentError('max-bytes 必须在 1 到 1048576 之间')
                if args.all or len(args.path) > 1:
                    return read_baseline_batch(args, engine, task)
                document, data = baseline_document(engine, args.path[0], args.max_bytes)
                if document['truncated']:
                    print(json.dumps(dict(ok=False, code='BASELINE_TRUNCATED', document=document, task=task), ensure_ascii=False))
                    return 2
                parameters.append(baseline_receipt(args, task, document, data))
                operation = engine.register_baseline
            value = operation(*parameters)
            if args.action == 'finish-step' and args.finish_implementation:
                value = engine.finish_implementation(args.task, value['version'], f'{args.request}:finish-impl')
        expected_state = {'run': 'passed', 'review': 'review_passed', 'sync-review-card': 'review_passed'}
        passed = args.action not in expected_state or value.get('state') == expected_state[args.action]
        key = {'history': 'history', 'progress': 'progress', 'request-confirmation': 'confirmation'}.get(args.action, 'task')
        output = {'ok': passed, key: value}
        if document is not None:
            output['document'] = document
        if documents is not None:
            output['version'] = value['version']
            output['documents'] = documents
        if confirmation is not None:
            output['confirmation'] = confirmation
        if review_path is not None:
            output['review_path'] = str(review_path)
        if reconcile and (reconcile.get('closed') or reconcile.get('conflicts')):
            output['reconcile'] = reconcile
        if key == 'task' and isinstance(value, dict) and value.get('protocol_version') == 2 and args.action not in ('status', 'snapshot'):
            from agent_progress import project_progress
            output['progress'] = project_progress(value)
        if args.action in ('status', 'prepare', 'bind-executor', 'resume'):
            from host_gate import hook_precheck_status
            output['hooks'] = hook_precheck_status(
                root,
                getattr(args, 'session', None),
                task=value if isinstance(value, dict) else None,
            )
        if args.action in CONFIRM_ACTIONS and not getattr(args, 'json', False) and sys.stdout.isatty():
            from review_markdown import render_confirmation_receipt
            print(render_confirmation_receipt(args.action, value, progress=output.get('progress'), review_path=review_path))
        else:
            print(json.dumps(output, ensure_ascii=False))
        return 0 if passed else 1
    except Exception as error:
        is_readonly_sqlite = isinstance(error, sqlite3.OperationalError) and any(
            token in str(error).lower() for token in ('readonly', 'unable to open')
        )
        if isinstance(error, PermissionError) or is_readonly_sqlite:
            code = 'STATE_NOT_WRITABLE'
            target_text = str(state_target) if state_target is not None else '.speclock/'
            message = (
                f'状态目录不可写（{target_text}）。'
                '默认状态目录位于项目内 .speclock/；若设置了 WORKFLOW_ENGINE_HOME 或 --db 指向项目外，'
                '请取消该设置，或在宿主沙箱中放行该目录。不要用聊天记录代替引擎登记。'
            )
        else:
            code = 'ARGUMENT' if isinstance(error, ArgumentError) else getattr(error, 'code', 'BLOCKED')
            message = str(error) if isinstance(error, ArgumentError) or hasattr(error, 'code') else '引擎不可用或输入无效'
        action = getattr(args, 'action', None)
        interactive_confirm_error = action in CONFIRM_ACTIONS and sys.stdin.isatty() and sys.stdout.isatty()
        interactive_render_error = action == 'render-md' and sys.stdout.isatty()
        if (interactive_confirm_error or interactive_render_error) and not getattr(args, 'json', False):
            print(f'❌ 操作未完成（{code}）：{message}', file=sys.stderr)
        else:
            print(json.dumps({'ok': False, 'code': code, 'message': message}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
