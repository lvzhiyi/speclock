"""验证 Markdown 审阅渲染、项目外安全写盘、非阻塞打开及 CLI/PTY 交互审批。"""
import json
import os
from pathlib import Path
import pty
import select
import stat
import subprocess
import sys
import tempfile
import termios
import threading
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
CLI = SCRIPTS / 'workflow_engine_cli.py'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import host_gate
import review_markdown
from workflow_engine import Engine


def _full_details():
    return {
        'goal': '统一空态公共组件\n并接入学习与计划页',
        'scope': ['lib/widgets/common', 'lib/pages/learn', 'docs/development/changes/T-FULL'],
        'source': 'docs/product/任务/全局组件.md',
        'dependencies': [{'id': 'Q01', 'status': 'done'}],
        'baseline': ['rules.md'],
        'steps': [
            {'id': 's1', 'title': '实现公共空态组件'},
            {'id': 's2', 'title': '接入页面并补充测试'},
        ],
        'note': '含管道符 | 与多行\n备注',
        'card': {'id': 'UI-06', 'path': 'docs/product/任务/全局组件.md'},
        'proposal': {
            'goal': '消除三端重复空态实现',
            'design': '抽离 CommonEmptyState 组件，按类型切换图标与操作按钮',
            'scope': ['lib/widgets/common', 'lib/pages/learn'],
            'impact': '不改动接口与路由，仅影响三个入口页面',
            'risk': '注意区分无数据与网络异常',
            'rollback': '回退组件引用与测试提交',
            'acceptance': ['三端表现一致', '支持窄屏与大字体'],
            'extra_notes': {'owner': 'frontend', 'priority': 'high'},
        },
    }


def _sample_plan(acceptance=('A1',)):
    return {
        'version': 1,
        'checks': [
            {
                'id': 'check-1',
                'argv': [sys.executable, '-c', 'pass'],
                'cwd': '.',
                'timeout': 120,
                'covers': ['format', 'analyze', 'test'],
                'acceptance': list(acceptance),
            }
        ],
    }


def _read_stream(stream, chunks):
    try:
        while True:
            data = stream.read(4096)
            if not data:
                break
            chunks.append(data)
    finally:
        stream.close()


def _run_with_pty(cmd, input_text, *, stdout_pipe=False, env=None):
    master_fd, slave_fd = pty.openpty()
    attrs = termios.tcgetattr(slave_fd)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=subprocess.PIPE if stdout_pipe else slave_fd,
        stderr=subprocess.PIPE,
        env=env,
        close_fds=True,
    )
    os.close(slave_fd)

    stderr_chunks = []
    stdout_chunks = []
    pty_chunks = []
    err_thread = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_chunks), daemon=True)
    err_thread.start()
    out_thread = None
    if stdout_pipe:
        out_thread = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_chunks), daemon=True)
        out_thread.start()

    try:
        os.write(master_fd, input_text.encode('utf-8'))
        while proc.poll() is None:
            if not stdout_pipe:
                readable, _, _ = select.select([master_fd], [], [], 0.05)
                if readable:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if chunk:
                        pty_chunks.append(chunk)
            else:
                try:
                    proc.wait(timeout=0.05)
                except subprocess.TimeoutExpired:
                    pass
        proc.wait(timeout=10)
        if not stdout_pipe:
            while True:
                readable, _, _ = select.select([master_fd], [], [], 0.05)
                if not readable:
                    break
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                pty_chunks.append(chunk)
    finally:
        os.close(master_fd)
        err_thread.join(timeout=5)
        if out_thread is not None:
            out_thread.join(timeout=5)

    stdout_bytes = b''.join(stdout_chunks if stdout_pipe else pty_chunks)
    stderr_bytes = b''.join(stderr_chunks)
    return (
        proc.returncode,
        stdout_bytes.decode('utf-8', errors='replace'),
        stderr_bytes.decode('utf-8', errors='replace'),
    )


class ReviewMarkdownUnitTests(unittest.TestCase):
    def test_render_full_proposal_and_warnings(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'rules.md').write_text('工程规范', encoding='utf-8')

            engine = Engine(root, base / 'state.sqlite')
            acceptance = ['A1 | 兼容旧入口', 'A2\n支持大字体']
            task = engine.create(
                'T-FULL',
                'full',
                acceptance,
                _sample_plan(acceptance),
                'req-create',
                details=_full_details(),
            )
            task = engine.confirm_tier('T-FULL', task['version'], 'req-tier', '用户')

            md = review_markdown.render_review_markdown(
                task,
                action='approve-proposal',
                actor='评审人 | 二组\n主审',
                digest=task['control_digest'],
                expected_version=task['version'],
            )
            self.assertIn('# 方案审批审阅：T-FULL', md)
            self.assertIn('完整档方案批准 (approve-proposal)', md)
            self.assertIn('UI-06', md)
            self.assertIn('### 方案目标', md)
            self.assertIn('### 技术设计', md)
            self.assertIn('### 方案范围', md)
            self.assertIn('- `lib/widgets/common`', md)
            self.assertNotIn("['lib/widgets/common'", md)
            self.assertIn('### 影响范围', md)
            self.assertIn('### 风险与边界', md)
            self.assertIn('### 回滚方案', md)
            self.assertIn('### 方案验收', md)
            self.assertIn('- 三端表现一致', md)
            self.assertIn('### extra_notes', md)
            self.assertIn('`s1` 实现公共空态组件', md)
            self.assertIn('- **check-1**', md)
            self.assertIn('2. A2\n   支持大字体', md)
            self.assertIn('方案尚未批准 (approval)', md)
            self.assertIn('档位确认**：已记录（用户）', md)
            self.assertIn('请返回终端输入 `confirm` 完成本次确认', md)
            self.assertIn('\\|', md)
            self.assertIn('<br>', md)
            self.assertNotIn('> ⚠️ 注意：', md)

            warned = review_markdown.render_review_markdown(
                task,
                action='approve-proposal',
                actor='评审人',
                digest='wrong-digest',
                expected_version=99,
            )
            self.assertIn('> ⚠️ 注意：', warned)
            self.assertIn('v99', warned)
            self.assertIn('wrong-digest', warned)

    def test_render_other_actions_readonly_and_legacy_v1(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            engine = Engine(root, base / 'state.sqlite')
            legacy = engine.create('LEGACY-1', 'light', ['A1'], _sample_plan(), 'req-legacy')

            readonly_md = review_markdown.render_review_markdown(legacy)
            self.assertIn('# 任务方案与状态：LEGACY-1', readonly_md)
            self.assertIn('计划摘要', readonly_md)
            self.assertNotIn('请返回终端输入 `confirm`', readonly_md)

            confirm_plan_md = review_markdown.render_review_markdown(
                legacy, action='confirm-plan', digest='bad-digest'
            )
            self.assertIn('# 检查计划确认审阅：LEGACY-1', confirm_plan_md)
            self.assertIn('> ⚠️ 注意：', confirm_plan_md)

            tier_md = review_markdown.render_review_markdown(legacy, action='confirm-tier', actor='用户')
            self.assertIn('# 档位确认审阅：LEGACY-1', tier_md)

            return_md = review_markdown.render_review_markdown(
                legacy, action='return-task', actor='人工', reason='范围需要调整'
            )
            self.assertIn('# 任务退回审阅：LEGACY-1', return_md)
            self.assertIn('范围需要调整', return_md)

    def test_terminal_summary_and_confirmation_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'rules.md').write_text('工程规范', encoding='utf-8')
            engine = Engine(root, base / 'state.sqlite')
            task = engine.create('T1', 'full', ['A1'], _sample_plan(), 'c1', details=_full_details())
            md = review_markdown.render_review_markdown(task, action='approve-proposal', actor='人')

            opened_summary = review_markdown.render_terminal_summary(
                task,
                action='approve-proposal',
                markdown=md,
                review_path=base / 'reviews/T1.md',
                opened_with='cursor',
                actor='人',
            )
            self.assertIn('审阅文档已打开（cursor）', opened_summary)
            self.assertNotIn('### 回滚方案', opened_summary)

            fallback_summary = review_markdown.render_terminal_summary(
                task,
                action='approve-proposal',
                markdown=md,
                review_path=base / 'reviews/T1.md',
                open_error='无图形界面',
            )
            self.assertIn('无图形界面', fallback_summary)
            self.assertIn('### 回滚方案', fallback_summary)

            approved = engine.approve_proposal('T1', task['version'], 'a1', '人', task['control_digest'])
            receipt = review_markdown.render_confirmation_receipt(
                'approve-proposal',
                approved,
                progress={'text': 'T1：实施步骤 0/2；待就绪，实施未开始'},
                review_path=base / 'reviews/T1.md',
            )
            self.assertIn('完整档方案批准已登记', receipt)
            self.assertIn('`T1`', receipt)
            self.assertNotIn('"rounds"', receipt)
            self.assertIn('--json', receipt)

    def test_write_review_markdown_security_and_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / 'project'
            root.mkdir()
            state_dir = base / 'engine-state'
            state_dir.mkdir()

            weird_task = {'id': '../../etc/passwd?任务', 'version': 3}
            written = review_markdown.write_review_markdown(
                state_dir, root, weird_task, '# 审阅', action='approve-proposal'
            )
            self.assertTrue(written.is_file())
            self.assertEqual(written.parent, state_dir.resolve() / 'reviews')
            self.assertNotIn('..', written.name)
            self.assertNotIn('/', written.name)
            self.assertEqual(stat.S_IMODE(written.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(written.stat().st_mode), 0o600)

            with self.assertRaises(ValueError):
                review_markdown.write_review_markdown(root / '.engine', root, {'id': 'T1', 'version': 1}, '# x')

            symlink_dir = base / 'sym-state'
            symlink_dir.mkdir()
            (symlink_dir / 'reviews').symlink_to(root)
            with self.assertRaises(ValueError):
                review_markdown.write_review_markdown(symlink_dir, root, {'id': 'T1', 'version': 1}, '# x')

            normal = state_dir / 'reviews' / 'T2-v1.md'
            normal.symlink_to(root / 'README.md')
            with self.assertRaises(ValueError):
                review_markdown.write_review_markdown(state_dir, root, {'id': 'T2', 'version': 1}, '# x')

    def test_open_review_file_detection_and_fallbacks(self):
        with tempfile.TemporaryDirectory() as folder:
            review_file = Path(folder) / 'review.md'
            review_file.write_text('# test\n', encoding='utf-8')

            with patch.dict(os.environ, {'WORKFLOW_NO_OPEN': '1'}):
                opener, err = review_markdown.open_review_file(review_file)
                self.assertIsNone(opener)
                self.assertIn('WORKFLOW_NO_OPEN', err)

            with patch.dict(os.environ, {'WORKFLOW_HOST': 'cursor'}, clear=True), \
                 patch.object(review_markdown.sys, 'platform', 'darwin'), \
                 patch('review_markdown.shutil.which', side_effect=lambda name: f'/usr/local/bin/{name}' if name in ('cursor', 'open') else None), \
                 patch('review_markdown.subprocess.run') as mock_run:
                mock_run.side_effect = [
                    subprocess.CompletedProcess(['cursor'], 1),
                    subprocess.CompletedProcess(['open'], 0),
                ]
                opener, err = review_markdown.open_review_file(review_file)
                self.assertEqual((opener, err), ('open', None))
                self.assertEqual(mock_run.call_args_list[0].args[0], ['/usr/local/bin/cursor', '--reuse-window', str(review_file)])
                self.assertEqual(mock_run.call_args_list[1].args[0], ['/usr/local/bin/open', str(review_file)])

            with patch.dict(os.environ, {'TERM_PROGRAM': 'vscode'}, clear=True), \
                 patch.object(review_markdown.sys, 'platform', 'darwin'), \
                 patch('review_markdown.shutil.which', side_effect=lambda name: f'/usr/local/bin/{name}' if name == 'code' else None), \
                 patch('review_markdown.subprocess.run', return_value=subprocess.CompletedProcess(['code'], 0)) as mock_run:
                opener, err = review_markdown.open_review_file(review_file)
                self.assertEqual((opener, err), ('code', None))
                self.assertEqual(mock_run.call_args.args[0], ['/usr/local/bin/code', '--reuse-window', str(review_file)])

            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(review_markdown.sys, 'platform', 'darwin'), \
                 patch('review_markdown.shutil.which', return_value='/usr/bin/open'), \
                 patch('review_markdown.subprocess.run', side_effect=OSError('no gui')):
                opener, err = review_markdown.open_review_file(review_file)
                self.assertIsNone(opener)
                self.assertIn('no gui', err)

            with patch.dict(os.environ, {'DISPLAY': ':0'}, clear=True), \
                 patch.object(review_markdown.sys, 'platform', 'linux'), \
                 patch('review_markdown.shutil.which', side_effect=lambda name: '/usr/bin/xdg-open' if name == 'xdg-open' else None), \
                 patch('review_markdown.subprocess.Popen') as mock_popen:
                opener, err = review_markdown.open_review_file(review_file)
                self.assertEqual((opener, err), ('xdg-open', None))
                self.assertEqual(mock_popen.call_args.args[0], ['/usr/bin/xdg-open', str(review_file)])

            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(review_markdown.sys, 'platform', 'linux'), \
                 patch('review_markdown.shutil.which', return_value='/usr/bin/xdg-open'):
                opener, err = review_markdown.open_review_file(review_file)
                self.assertIsNone(opener)
                self.assertIn('未找到可用', err)


class ReviewMarkdownCliAndPtyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.base = Path(self.tempdir.name)
        self.root = self.base / 'repo'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / 'rules.md').write_text('工程规范全文', encoding='utf-8')
        subprocess.run(['git', 'add', 'rules.md'], cwd=self.root, check=True)
        subprocess.run(
            ['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-q', '-m', 'init'],
            cwd=self.root,
            check=True,
        )
        self.db = self.base / 'engine' / 'state.sqlite'
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'WORKFLOW_NO_OPEN': '1'}

    def _create_full_task_ready_for_approval(self):
        engine = Engine(self.root, self.db)
        acceptance = ['三端表现一致']
        task = engine.create('T-FULL', 'full', acceptance, _sample_plan(acceptance), 'create-1', details=_full_details())
        task = engine.confirm_tier('T-FULL', task['version'], 'tier-1', '用户')
        return engine, task

    def test_render_md_missing_db_and_export_modes(self):
        missing_db = self.base / 'missing' / 'state.sqlite'
        res = subprocess.run(
            [sys.executable, str(CLI), '--root', str(self.root), '--db', str(missing_db), 'render-md', '--task', 'T-FULL'],
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(res.returncode, 2)
        self.assertEqual(json.loads(res.stdout)['code'], 'NOT_FOUND')
        self.assertFalse(missing_db.exists())
        self.assertFalse(missing_db.parent.exists())

        _, task = self._create_full_task_ready_for_approval()
        res = subprocess.run(
            [sys.executable, str(CLI), '--root', str(self.root), '--db', str(self.db), 'render-md', '--task', 'T-FULL'],
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn('# 任务方案与状态：T-FULL', res.stdout)
        self.assertIn('消除三端重复空态实现', res.stdout)
        self.assertEqual(Engine(self.root, self.db).status('T-FULL')['version'], task['version'])

        saved = subprocess.run(
            [sys.executable, str(CLI), '--root', str(self.root), '--db', str(self.db), 'render-md', '--task', 'T-FULL', '--save', '--json'],
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)
        payload = json.loads(saved.stdout)
        self.assertTrue(payload['ok'])
        saved_path = Path(payload['path'])
        self.assertTrue(saved_path.is_file())
        self.assertEqual(stat.S_IMODE(saved_path.stat().st_mode), 0o600)
        self.assertFalse(saved_path.is_relative_to(self.root.resolve()))

        opened = subprocess.run(
            [sys.executable, str(CLI), '--root', str(self.root), '--db', str(self.db), 'render-md', '--task', 'T-FULL', '--open'],
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(opened.returncode, 0, opened.stderr)
        self.assertIn('已保存审阅文档', opened.stderr)
        self.assertIn('# 任务方案与状态：T-FULL', opened.stdout)

    def test_approve_proposal_non_tty_rejects_without_writing_review(self):
        _, task = self._create_full_task_ready_for_approval()
        res = subprocess.run(
            [
                sys.executable, str(CLI), '--root', str(self.root), '--db', str(self.db),
                'approve-proposal', '--task', 'T-FULL', '--version', str(task['version']),
                '--actor', '人工', '--digest', task['control_digest'], '--request', 'non-tty',
            ],
            input='confirm\n',
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(res.returncode, 2)
        payload = json.loads(res.stdout)
        self.assertEqual(payload['code'], 'ARGUMENT')
        self.assertFalse((self.db.parent / 'reviews').exists())

    def test_approve_proposal_pty_interactive_receipt_and_git_clean(self):
        engine, task = self._create_full_task_ready_for_approval()
        cmd = [
            sys.executable, str(CLI), '--root', str(self.root), '--db', str(self.db),
            'approve-proposal', '--task', 'T-FULL', '--version', str(task['version']),
            '--actor', '人工审核员', '--digest', task['control_digest'], '--request', 'pty-ok',
        ]
        code, stdout, stderr = _run_with_pty(cmd, 'confirm\n', stdout_pipe=False, env=self.env)
        self.assertEqual(code, 0, f'stdout={stdout}\nstderr={stderr}')
        self.assertIn('# 方案审批审阅：T-FULL', stderr)
        self.assertIn('消除三端重复空态实现', stderr)
        self.assertIn('.md', stderr)
        self.assertIn('请输入 confirm：', stderr)
        self.assertIn('完整档方案批准已登记', stdout)
        self.assertNotIn('{"ok": true, "task":', stdout)

        updated = engine.status('T-FULL')
        self.assertNotIn('approval', updated['missing'])
        git_status = subprocess.run(['git', 'status', '--short'], cwd=self.root, capture_output=True, text=True, check=True)
        self.assertEqual(git_status.stdout.strip(), '')

    def test_approve_proposal_pty_explicit_json_and_piped_stdout(self):
        engine, task = self._create_full_task_ready_for_approval()
        cmd_json = [
            sys.executable, str(CLI), '--root', str(self.root), '--db', str(self.db),
            'approve-proposal', '--task', 'T-FULL', '--version', str(task['version']),
            '--actor', '人工审核员', '--digest', task['control_digest'], '--request', 'pty-json', '--json',
        ]
        code, stdout, stderr = _run_with_pty(cmd_json, 'confirm\n', stdout_pipe=False, env=self.env)
        self.assertEqual(code, 0, f'stdout={stdout}\nstderr={stderr}')
        payload = json.loads(stdout)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['task']['version'], task['version'] + 1)
        self.assertIn('progress', payload)
        self.assertTrue(Path(payload['review_path']).is_file())

        cmd_pipe = [
            sys.executable, str(CLI), '--root', str(self.root), '--db', str(self.db),
            'confirm-tier', '--task', 'T-FULL', '--version', str(payload['task']['version']),
            '--actor', '人工', '--request', 'pty-pipe', '--no-open',
        ]
        code2, stdout2, stderr2 = _run_with_pty(cmd_pipe, 'confirm\n', stdout_pipe=True, env=self.env)
        self.assertEqual(code2, 0, f'stdout={stdout2}\nstderr={stderr2}')
        payload2 = json.loads(stdout2)
        self.assertTrue(payload2['ok'])
        self.assertIn('已指定 --no-open', stderr2)

    def test_approve_proposal_pty_cancel_returns_readable_error(self):
        engine, task = self._create_full_task_ready_for_approval()
        cmd = [
            sys.executable, str(CLI), '--root', str(self.root), '--db', str(self.db),
            'approve-proposal', '--task', 'T-FULL', '--version', str(task['version']),
            '--actor', '人工', '--digest', task['control_digest'], '--request', 'pty-cancel',
        ]
        code, stdout, stderr = _run_with_pty(cmd, '\n', stdout_pipe=False, env=self.env)
        self.assertEqual(code, 2)
        self.assertEqual(stdout.strip(), '')
        self.assertIn('操作未完成', stderr)
        self.assertNotIn('{"ok": false', stderr)
        self.assertIn('approval', engine.status('T-FULL')['missing'])

    def test_host_gate_allows_new_cli_flags(self):
        self.assertTrue(host_gate.engine_command(f'python3 "{CLI}" --root "{self.root}" render-md --task T1 --open'))
        self.assertTrue(
            host_gate.engine_command(
                f'WORKFLOW_HOST=cursor python3 "{CLI}" --root "{self.root}" approve-proposal --task T1 --version 2 --actor 用户 --digest abc --no-open'
            )
        )


if __name__ == '__main__':
    unittest.main()
