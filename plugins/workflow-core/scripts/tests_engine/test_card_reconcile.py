"""任务卡结案自动对账与冲突提示测试。"""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_protocol
import host_gate


CLI = Path(__file__).resolve().parents[1] / 'workflow_engine_cli.py'
CARD = 'docs/product/任务/模块.md'
OTHER_CARD = 'docs/product/任务/另一个模块.md'
BINDING = {'path': CARD, 'id': 't'}


def render_card(card_id='t', status='待处理', checked=False):
    box = 'x' if checked else ' '
    return (
        '## 模块\n'
        f'### {card_id} 测试任务\n'
        f'- [{box}] 子需求完成\n'
        f'- 协作状态：{status}\n'
    )


class CardReconcileTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_protocol.ProtocolTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.engine = self.fixture.e
        self.card = self.root / CARD
        self.card.parent.mkdir(parents=True, exist_ok=True)
        (self.root / 'ai-workflow.yaml').write_text(
            'version: 1\ndocs:\n  cards_dir: docs/product/任务\n', encoding='utf-8'
        )

    def cli(self, *args, db=None):
        target_db = db if db is not None else self.engine.db
        process = subprocess.run(
            [sys.executable, str(CLI), '--root', str(self.root), '--db', str(target_db), *args],
            capture_output=True, text=True,
        )
        return process.returncode, json.loads(process.stdout)

    def test_bound_closed_card_auto_closes_created_task(self):
        self.card.write_text(render_card(status='评审通过，待人工验收'), encoding='utf-8')
        task = self.fixture.create()
        task = self.fixture.call('update_task', task, {'card': BINDING})

        status = self.engine.status('t')
        self.assertEqual(status['version'], task['version'])
        self.assertEqual(status['card_closure']['action'], 'auto_close')
        self.assertEqual(status['card_closure']['status'], '评审通过，待人工验收')

        result = self.engine.reconcile_cards()
        self.assertEqual(len(result['closed']), 1)
        self.assertEqual(result['closed'][0]['id'], 't')
        self.assertEqual(result['conflicts'], [])

        after = self.engine.status('t')
        self.assertEqual(after['state'], 'cancelled')
        self.assertEqual(after['phase'], 'done')
        self.assertNotIn('card_closure', after)
        self.assertEqual(after['rounds'][-1]['cancel']['reason'], 'card_superseded')
        self.assertEqual(after['rounds'][-1]['cancel']['card'], BINDING)

        history = self.engine.history('t')
        self.assertEqual(history[-1]['action'], 'card_superseded')

    def test_checked_box_auto_closes_even_when_status_pending(self):
        self.card.write_text(render_card(status='待处理', checked=True), encoding='utf-8')
        task = self.fixture.create()
        self.fixture.call('update_task', task, {'card': BINDING})

        result = self.engine.reconcile_cards()
        self.assertEqual(len(result['closed']), 1)
        self.assertTrue(result['closed'][0]['checked'])
        self.assertEqual(self.engine.status('t')['state'], 'cancelled')

    def test_unbound_task_matches_unique_card_heading_only(self):
        self.card.write_text(render_card(status='已验收'), encoding='utf-8')
        self.fixture.create()
        result = self.engine.reconcile_cards()
        self.assertEqual(len(result['closed']), 1)
        self.assertEqual(result['closed'][0]['card'], BINDING)
        self.assertEqual(self.engine.status('t')['state'], 'cancelled')

        # 另一份任务卡也出现相同标题时不再自动匹配关闭。
        self.setUp()
        self.card.write_text(render_card(status='已验收'), encoding='utf-8')
        other = self.root / OTHER_CARD
        other.write_text(render_card(status='已验收'), encoding='utf-8')
        self.fixture.create()
        ambiguous = self.engine.reconcile_cards()
        self.assertEqual(ambiguous, {'closed': [], 'conflicts': []})
        self.assertEqual(self.engine.status('t')['state'], 'created')

    def test_implementing_task_with_closed_card_reports_conflict_without_closing(self):
        self.card.write_text(render_card(status='待处理'), encoding='utf-8')
        task = self.fixture.ready()
        self.assertEqual(task['state'], 'implementing')
        self.card.write_text(render_card(status='已交付'), encoding='utf-8')

        status = self.engine.status('t')
        self.assertEqual(status['card_closure']['action'], 'needs_decision')
        result = self.engine.reconcile_cards()
        self.assertEqual(result['closed'], [])
        self.assertEqual(len(result['conflicts']), 1)
        self.assertEqual(result['conflicts'][0]['id'], 't')
        self.assertEqual(result['conflicts'][0]['state'], 'implementing')
        self.assertEqual(self.engine.status('t')['state'], 'implementing')

    def test_pending_card_has_no_closure_and_empty_reconcile(self):
        self.card.write_text(render_card(status='待处理'), encoding='utf-8')
        task = self.fixture.create()
        self.fixture.call('update_task', task, {'card': BINDING})

        status = self.engine.status('t')
        self.assertNotIn('card_closure', status)
        self.assertEqual(self.engine.reconcile_cards(), {'closed': [], 'conflicts': []})

    def test_reconcile_cards_is_idempotent(self):
        self.card.write_text(render_card(status='已完成'), encoding='utf-8')
        self.fixture.create()

        first = self.engine.reconcile_cards()
        second = self.engine.reconcile_cards()
        self.assertEqual(len(first['closed']), 1)
        self.assertEqual(second, {'closed': [], 'conflicts': []})

    def test_locally_reviewed_and_synced_task_is_untouched(self):
        self.card.write_text(render_card(status='待处理'), encoding='utf-8')
        task = self.fixture.create()
        task = self.fixture.call('update_task', task, {'card': BINDING, 'baseline': [CARD]})
        task = self.fixture.call('confirm_tier', task, '人工')
        task = self.fixture.call('bind_executor', task, 'agent', 'session')
        data = self.card.read_bytes()
        task = self.fixture.call('register_baseline', task, {
            'path': CARD, 'sha256': sha256(data).hexdigest(), 'bytes_read': len(data),
            'complete': True, 'executor': 'agent', 'session_id': 'session',
            'round_id': task['current_round'],
        })
        task = self.fixture.call('start', task)
        task = self.fixture.call('record_tdd', task, {
            'adopted': False, 'reason': '文档任务', 'alternative_validation': '真实检查',
        })
        task = self.fixture.call('finish_step', task, '0', '实施完成')
        task = self.fixture.call('finish_implementation', task)
        task = self.fixture.call('run', task)
        task = self.fixture.call('review', task, self.fixture.report(task))
        self.assertEqual(task['state'], 'review_passed')
        self.assertEqual(task['card_sync'], 'synced')

        self.assertEqual(self.engine.reconcile_cards(), {'closed': [], 'conflicts': []})
        status = self.engine.status('t')
        self.assertEqual(status['state'], 'review_passed')
        self.assertEqual(status['card_sync'], 'synced')
        self.assertNotIn('card_closure', status)

    def test_cli_reconcile_cards_and_prepare_hook_behavior(self):
        missing_db = self.root.parent / 'missing.sqlite'
        code, empty_out = self.cli('reconcile-cards', db=missing_db)
        self.assertEqual(code, 0, empty_out)
        self.assertEqual(empty_out, {'ok': True, 'closed': [], 'conflicts': []})
        self.assertFalse(missing_db.exists())

        self.card.write_text(render_card(status='评审通过，待人工验收'), encoding='utf-8')
        task = self.fixture.create()
        self.fixture.call('update_task', task, {'card': BINDING})

        code, cli_out = self.cli('reconcile-cards')
        self.assertEqual(code, 0, cli_out)
        self.assertTrue(cli_out['ok'])
        self.assertEqual([item['id'] for item in cli_out['closed']], ['t'])
        self.assertEqual(self.engine.status('t')['state'], 'cancelled')

    def test_cli_prepare_attaches_reconcile_and_begin_blocks_closed_task(self):
        self.card.write_text(render_card(status='评审通过，待人工验收'), encoding='utf-8')
        self.fixture.create()
        details = {
            'goal': '新任务', 'scope': ['code.py'], 'source': '需求',
            'dependencies': [], 'baseline': ['baseline.md'],
            'steps': [{'id': 's1', 'title': '步骤'}],
        }
        plan = {
            'version': 1,
            'checks': [{'id': 'all', 'argv': [sys.executable, '-c', 'pass'], 'cwd': '.',
                        'timeout': 2, 'covers': ['format', 'analyze', 'test'], 'acceptance': ['A1']}],
        }
        code, prep_out = self.cli(
            'prepare', '--task', 't-new', '--tier', '轻量', '--acceptance', 'A1',
            '--plan-json', json.dumps(plan), '--details-json', json.dumps(details),
        )
        self.assertEqual(code, 0, prep_out)
        self.assertEqual([item['id'] for item in prep_out['reconcile']['closed']], ['t'])
        self.assertEqual(self.engine.status('t')['state'], 'cancelled')

        # 目标任务自身在 begin 前已由任务卡结案时，begin 自动关闭后拒绝继续开工。
        self.card.write_text(render_card(card_id='t-new', status='已验收'), encoding='utf-8')
        self.fixture.e.confirm_tier('t-new', prep_out['task']['version'], 'tier-new', '人工')
        code, begin_out = self.cli('begin', '--task', 't-new', '--executor', 'agent', '--session', 's1')
        self.assertNotEqual(code, 0)
        self.assertEqual(begin_out['code'], 'INVALID_STATE')
        self.assertEqual(self.engine.status('t-new')['state'], 'cancelled')

    def test_host_gate_card_reconcile_message_and_session_start(self):
        self.card.write_text(render_card(status='评审通过，待人工验收'), encoding='utf-8')
        task = self.fixture.create()
        self.fixture.call('update_task', task, {'card': BINDING})

        message = host_gate.card_reconcile_message(self.root, self.engine.db)
        self.assertIsNotNone(message)
        self.assertIn('ENGINE_CARD_RECONCILED', message)
        self.assertIn('t（评审通过，待人工验收）', message)
        self.assertEqual(self.engine.status('t')['state'], 'cancelled')
        self.assertIsNone(host_gate.card_reconcile_message(self.root, self.engine.db))

        # 已开工冲突场景提示人工决定。
        self.setUp()
        self.card.write_text(render_card(status='待处理'), encoding='utf-8')
        self.fixture.ready()
        self.card.write_text(render_card(status='', checked=True), encoding='utf-8')
        conflict_msg = host_gate.card_reconcile_message(self.root, self.engine.db)
        self.assertIsNotNone(conflict_msg)
        self.assertIn('ENGINE_CARD_CONFLICT', conflict_msg)
        self.assertIn('t（本地 implementing，任务卡 已勾选完成）', conflict_msg)


if __name__ == '__main__':
    unittest.main()
