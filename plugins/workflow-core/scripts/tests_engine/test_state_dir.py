"""验证项目内 .speclock/ 默认状态目录、快照排除、门禁保护、只读边界与旧库迁移。"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
CLI = SCRIPTS / "workflow_engine_cli.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cursor_gate
import dashboard_data
import dashboard_server
import host_gate
import review_markdown
import workflow_engine_cli
import workflow_planning_cli
from workflow_config import Config
from workflow_engine import Engine, EngineError
from workflow_engine.snapshot import capture, capture_files


def _clean_env(codex_home, extra=None):
    env = {k: v for k, v in os.environ.items() if k != "WORKFLOW_ENGINE_HOME"}
    env["CODEX_HOME"] = str(codex_home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update(extra)
    return env


def _init_repo(root):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "ai-workflow.yaml").write_text(
        "version: 1\nbaseline:\n  required:\n    - docs/standards.md\n"
        f"verify:\n  light:\n    - {sys.executable} -c pass\n",
        encoding="utf-8",
    )
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/standards.md").write_text("# 规范\n保持简洁。\n", encoding="utf-8")
    (root / "src").mkdir(exist_ok=True)
    (root / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)


def _minimal_plan():
    return {
        "version": 1,
        "checks": [
            {
                "id": "all",
                "argv": [sys.executable, "-c", "pass"],
                "cwd": ".",
                "timeout": 5,
                "covers": ["format", "analyze", "test"],
                "acceptance": ["A1"],
            }
        ],
    }


def _minimal_details():
    return {
        "goal": "实现示例目标",
        "scope": ["src"],
        "source": "需求文档",
        "dependencies": [],
        "baseline": ["docs/standards.md"],
        "steps": [{"id": "s1", "title": "实现步骤"}],
    }


class StateDirTests(unittest.TestCase):
    def test_default_db_location_and_external_override(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            root.mkdir()
            codex_home = base / "codex-home"
            with patch.dict(os.environ, _clean_env(codex_home), clear=True):
                self.assertEqual(workflow_engine_cli.default_db(root), root / ".speclock" / "state.sqlite")
            ext_home = base / "external-engine"
            with patch.dict(os.environ, _clean_env(codex_home, {"WORKFLOW_ENGINE_HOME": str(ext_home)}), clear=True):
                expected = ext_home / hashlib.sha256(str(root).encode()).hexdigest() / "state.sqlite"
                self.assertEqual(workflow_engine_cli.default_db(root), expected)

    def test_cli_prepare_creates_speclock_with_gitignore_and_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            _init_repo(root)
            codex_home = base / "codex-home"
            env = _clean_env(codex_home)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--root",
                    str(root),
                    "prepare",
                    "--task",
                    "T1",
                    "--tier",
                    "轻量",
                    "--acceptance",
                    "A1",
                    "--details-json",
                    json.dumps(_minimal_details(), ensure_ascii=False),
                    "--executor",
                    "agent",
                    "--session",
                    "sess-1",
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            state_dir = root / ".speclock"
            db_file = state_dir / "state.sqlite"
            gitignore = state_dir / ".gitignore"
            self.assertTrue(state_dir.is_dir())
            self.assertTrue(db_file.is_file())
            self.assertTrue(gitignore.is_file())
            self.assertEqual(gitignore.read_text(encoding="utf-8"), "*\n")
            self.assertEqual(stat.S_IMODE(state_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(db_file.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(gitignore.stat().st_mode), 0o600)
            git_status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(git_status.stdout.strip(), "")

    def test_snapshot_excludes_speclock_even_after_writes_and_if_tracked(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            _init_repo(root)
            plan = _minimal_plan()
            details = _minimal_details()
            plan_digest = hashlib.sha256(
                json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            before = capture(root, plan_digest)

            engine = Engine(root, root / ".speclock" / "state.sqlite")
            task = engine.create("T1", "light", ["A1"], plan, "r1", details=details)
            task = engine.confirm_tier("T1", task["version"], "r2", "人工")
            task = engine.bind_executor("T1", task["version"], "r3", "agent", "sess-1")
            data = (root / "docs/standards.md").read_bytes()
            receipt = {
                "path": "docs/standards.md",
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes_read": len(data),
                "complete": True,
                "executor": "agent",
                "session_id": "sess-1",
                "round_id": task["current_round"],
            }
            task = engine.register_baseline("T1", task["version"], "r4", receipt)
            task = engine.start("T1", task["version"], "r5")
            task = engine.record_tdd("T1", task["version"], "r6", {"adopted": True})
            task = engine.finish_step("T1", task["version"], "r7", "s1", "完成")
            task = engine.finish_implementation("T1", task["version"], "r8")
            task = engine.run("T1", task["version"], "r9")
            self.assertEqual(task["state"], "passed")
            after = capture(root, plan_digest)
            self.assertEqual(before, after)
            self.assertEqual(engine.status("T1")["state"], "passed")

            tracked_file = root / ".speclock" / "tracked.txt"
            tracked_file.write_text("v1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-f", ".speclock/tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "track speclock"], check=True)
            self.assertFalse(any(rel.startswith(".speclock") for rel, *_ in capture_files(root)))
            tracked_file.write_text("v2\n", encoding="utf-8")
            self.assertEqual(capture(root, plan_digest), before)
            self.assertEqual(engine.status("T1")["state"], "passed")

    def test_db_location_rejects_other_in_root_paths_and_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            root.mkdir()
            with self.assertRaises(EngineError) as caught:
                Engine(root, root / "db")
            self.assertEqual(caught.exception.code, "DB_LOCATION")

            with self.assertRaises(EngineError) as nested:
                Engine(root, root / ".speclock" / "other.sqlite")
            self.assertEqual(nested.exception.code, "DB_LOCATION")

            outside = base / "outside"
            outside.mkdir()
            (root / ".speclock").symlink_to(outside)
            with self.assertRaises(EngineError) as sym:
                Engine(root, root / ".speclock" / "state.sqlite")
            self.assertEqual(sym.exception.code, "DB_LOCATION")

            proc = subprocess.run(
                [sys.executable, str(CLI), "--root", str(root), "status", "--task", "T1"],
                capture_output=True,
                text=True,
                env=_clean_env(base / "codex-home"),
            )
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout)["code"], "DB_LOCATION")

    def test_read_command_does_not_create_speclock_when_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            _init_repo(root)
            env = _clean_env(base / "codex-home")
            proc = subprocess.run(
                [sys.executable, str(CLI), "--root", str(root), "progress", "--task", "missing"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout)["code"], "NOT_FOUND")
            self.assertFalse((root / ".speclock").exists())

            listed = subprocess.run(
                [sys.executable, str(CLI), "--root", str(root), "list"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(listed.returncode, 0)
            listed_payload = json.loads(listed.stdout)
            self.assertTrue(listed_payload["ok"])
            self.assertEqual(listed_payload["tasks"], [])
            self.assertFalse(listed_payload["hooks"]["hook_active"])
            self.assertFalse((root / ".speclock").exists())

    def test_legacy_migration_copies_once_and_preserves_old_db(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            _init_repo(root)
            codex_home = base / "codex-home"
            key = hashlib.sha256(str(root).encode()).hexdigest()
            old_db = codex_home / "workflow-engine" / key / "state.sqlite"

            old_engine = Engine(root, old_db)
            created = old_engine.create("T1", "light", ["A1"], _minimal_plan(), "legacy-1", details=_minimal_details())
            self.assertEqual(created["version"], 1)
            old_snapshot = old_db.read_bytes()

            env = _clean_env(codex_home)
            first = subprocess.run(
                [sys.executable, str(CLI), "--root", str(root), "status", "--task", "T1"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            payload = json.loads(first.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["task"]["id"], "T1")
            self.assertIn("已将旧状态库迁移至", first.stderr)

            new_db = root / ".speclock" / "state.sqlite"
            self.assertTrue(new_db.is_file())
            self.assertEqual(stat.S_IMODE(new_db.stat().st_mode), 0o600)
            self.assertEqual((root / ".speclock" / ".gitignore").read_text(encoding="utf-8"), "*\n")
            self.assertTrue(old_db.is_file())
            self.assertEqual(old_db.read_bytes(), old_snapshot)

            confirmed = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--root",
                    str(root),
                    "confirm-tier",
                    "--task",
                    "T1",
                    "--version",
                    "1",
                    "--actor",
                    "人工",
                    "--json",
                ],
                input="confirm\n",
                capture_output=True,
                text=True,
                env=env,
            )
            # confirm-tier 需要交互 TTY，改用 Engine 更新新库并验证不会被旧库覆盖。
            self.assertEqual(confirmed.returncode, 2)
            new_engine = Engine(root, new_db)
            updated = new_engine.confirm_tier("T1", 1, "confirm-new", "人工")
            self.assertEqual(updated["version"], 2)

            second = subprocess.run(
                [sys.executable, str(CLI), "--root", str(root), "status", "--task", "T1"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertNotIn("迁移", second.stderr)
            self.assertEqual(json.loads(second.stdout)["task"]["version"], 2)

    def test_unwritable_state_dir_reports_state_not_writable(self):
        if os.geteuid() == 0:
            self.skipTest("root 用户忽略文件权限检查")
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            _init_repo(root)
            speclock = root / ".speclock"
            speclock.mkdir(mode=0o700)
            self.addCleanup(lambda: speclock.exists() and os.chmod(str(speclock), 0o700))
            os.chmod(str(speclock), 0o500)

            env = _clean_env(base / "codex-home")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--root",
                    str(root),
                    "create",
                    "--task",
                    "T1",
                    "--tier",
                    "轻量",
                    "--acceptance",
                    "A1",
                    "--plan-json",
                    json.dumps(_minimal_plan()),
                    "--details-json",
                    json.dumps(_minimal_details()),
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 2)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["code"], "STATE_NOT_WRITABLE")
            self.assertIn(str(speclock), payload["message"])
            self.assertIn("WORKFLOW_ENGINE_HOME", payload["message"])
            self.assertIn("不要用聊天记录代替引擎登记", payload["message"])

            # 若目录和库已存在但目录只读（SQLite 无法建锁/日志），同样报 STATE_NOT_WRITABLE。
            os.chmod(str(speclock), 0o700)
            Engine(root, speclock / "state.sqlite")
            os.chmod(str(speclock), 0o500)
            proc2 = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--root",
                    str(root),
                    "create",
                    "--task",
                    "T2",
                    "--tier",
                    "轻量",
                    "--acceptance",
                    "A1",
                    "--plan-json",
                    json.dumps(_minimal_plan()),
                    "--details-json",
                    json.dumps(_minimal_details()),
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(proc2.returncode, 2)
            self.assertEqual(json.loads(proc2.stdout)["code"], "STATE_NOT_WRITABLE")

    def test_host_gate_and_cursor_gate_protect_speclock(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            _init_repo(root)
            with patch.dict(os.environ, _clean_env(base / "codex-home"), clear=True):
                event = {
                    "hook_event_name": "PreToolUse",
                    "cwd": str(root),
                    "session_id": "sess-1",
                    "tool_name": "Edit",
                    "tool_input": {"file_path": ".speclock/state.sqlite"},
                }
                reason = host_gate.pre_tool(event)
                self.assertIsNotNone(reason)
                self.assertTrue(reason.startswith("ENGINE_STATE_PROTECTED"), reason)

                patch_event = {
                    "hook_event_name": "PreToolUse",
                    "cwd": str(root),
                    "session_id": "sess-1",
                    "tool_name": "apply_patch",
                    "tool_input": {"patch": "*** Begin Patch\n*** Update File: .speclock/.gitignore\n*** End Patch"},
                }
                patch_reason = host_gate.pre_tool(patch_event)
                self.assertIsNotNone(patch_reason)
                self.assertTrue(patch_reason.startswith("ENGINE_STATE_PROTECTED"), patch_reason)

                cursor_res = cursor_gate.handle(
                    {
                        "hook_event_name": "preToolUse",
                        "conversation_id": "conv-1",
                        "workspace_roots": [str(root)],
                        "tool_name": "Write",
                        "tool_input": {"file_path": str(root / ".speclock" / "state.sqlite")},
                    }
                )
                self.assertEqual(cursor_res["permission"], "deny")
                self.assertIn("ENGINE_STATE_PROTECTED", cursor_res["user_message"])

    def test_review_markdown_allows_speclock_only_inside_root(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            root.mkdir()
            written = review_markdown.write_review_markdown(
                root / ".speclock", root, {"id": "T1", "version": 1}, "# 审阅"
            )
            self.assertEqual(written, root / ".speclock" / "reviews" / "T1-v1.md")
            self.assertTrue(written.is_file())
            self.assertEqual((root / ".speclock" / ".gitignore").read_text(encoding="utf-8"), "*\n")

            with self.assertRaises(ValueError):
                review_markdown.write_review_markdown(root / ".engine", root, {"id": "T1", "version": 1}, "# x")

            sym_root = base / "sym-repo"
            sym_root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            (sym_root / ".speclock").symlink_to(outside)
            with self.assertRaises(ValueError):
                review_markdown.write_review_markdown(
                    sym_root / ".speclock", sym_root, {"id": "T1", "version": 1}, "# x"
                )

    def test_planning_rejects_speclock_and_dashboard_reports_migration_hint(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            _init_repo(root)
            config = Config({"version": 1}, "test", root)
            for op in ("init", "prd-breakdown", "clarify"):
                with self.assertRaises(ValueError):
                    workflow_planning_cli.legal_target(root, op, ".speclock/a.md", config)

            codex_home = base / "codex-home"
            key = hashlib.sha256(str(root).encode()).hexdigest()
            old_db = codex_home / "workflow-engine" / key / "state.sqlite"
            Engine(root, old_db).create("T1", "light", ["A1"], _minimal_plan(), "c1", details=_minimal_details())

            with patch.dict(os.environ, _clean_env(codex_home), clear=True):
                result = {"mode": {}, "issues": []}
                dashboard_data._engine(root, None, result, {}, {})
                self.assertEqual(result["mode"]["state"], "unavailable")
                self.assertIn("旧版状态库", result["mode"]["warning"])
                self.assertFalse((root / ".speclock").exists())
                self.assertEqual(dashboard_server.state_path(root), root / ".speclock" / "dashboard.json")

            ext_home = base / "external"
            with patch.dict(os.environ, _clean_env(codex_home, {"WORKFLOW_ENGINE_HOME": str(ext_home)}), clear=True):
                self.assertEqual(dashboard_server.state_path(root), ext_home / key / "dashboard.json")

    def test_planning_open_and_chat_confirmation_share_speclock_and_keep_git_clean(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            _init_repo(root)
            env = _clean_env(base / "codex-home")
            planning_cli = SCRIPTS / "workflow_planning_cli.py"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(planning_cli),
                    "open",
                    "--root",
                    str(root),
                    "--session",
                    "sess-plan",
                    "--operation",
                    "init",
                    "--path",
                    "docs/development/standards.md",
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue((root / ".speclock" / ".gitignore").is_file())
            self.assertEqual((root / ".speclock" / ".gitignore").read_text(encoding="utf-8"), "*\n")
            git_status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(git_status.stdout.strip(), "")

            with patch.dict(os.environ, env, clear=True):
                engine = Engine(root, workflow_engine_cli.default_db(root))
                task = engine.create("T1", "light", ["A1"], _minimal_plan(), "c1", details=_minimal_details())
                task = engine.bind_executor("T1", task["version"], "b1", "agent", "sess-chat")
                res = host_gate.request_chat_confirmation(root, task, task["version"], "sess-chat", "tier_confirmation", "req-1")
                self.assertEqual(res["task"], "T1")
                self.assertTrue(any(p.name.startswith("confirmation-") for p in (root / ".speclock").iterdir()))

    def test_hook_activity_and_chat_confirmation_keep_speclock_clean(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "repo"
            _init_repo(root)
            plan_digest = hashlib.sha256(
                json.dumps(_minimal_plan(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            before = capture(root, plan_digest)

            codex_home = base / "codex-home"
            key = hashlib.sha256(str(root).encode()).hexdigest()
            old_db = codex_home / "workflow-engine" / key / "state.sqlite"
            Engine(root, old_db).create("T-MIG", "light", ["A1"], _minimal_plan(), "old-1", details=_minimal_details())

            env = _clean_env(codex_home)
            gate = SCRIPTS / "workflow_gate.py"
            read_proc = subprocess.run(
                [sys.executable, str(gate)],
                input=json.dumps({"cwd": str(root), "session_id": "sess-hook", "hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "docs/standards.md"}}),
                capture_output=True,
                text=True,
                env={**env, "WORKFLOW_HOST": "codex"},
            )
            self.assertEqual(read_proc.returncode, 0, read_proc.stderr)
            self.assertTrue(any(p.name.startswith("hook-session-") for p in (root / ".speclock").iterdir()))
            self.assertFalse((root / ".speclock" / "state.sqlite").exists())
            self.assertEqual((root / ".speclock" / ".gitignore").read_text(encoding="utf-8"), "*\n")
            self.assertEqual(capture(root, plan_digest), before)
            git_status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(git_status.stdout.strip(), "")

            # hook-session-* 已存在但 state.sqlite 尚未创建时，仍能正确检测并迁移旧版 state.sqlite。
            migrated = subprocess.run(
                [sys.executable, str(CLI), "--root", str(root), "status", "--task", "T-MIG"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(migrated.returncode, 0, migrated.stdout + migrated.stderr)
            self.assertIn("已将旧状态库迁移至", migrated.stderr)
            self.assertEqual(json.loads(migrated.stdout)["task"]["id"], "T-MIG")

            for event in (
                {"cwd": str(root), "session_id": "sess-hook", "hook_event_name": "SessionStart"},
                {"cwd": str(root), "session_id": "sess-hook", "hook_event_name": "UserPromptSubmit", "prompt": "检查"},
            ):
                proc = subprocess.run(
                    [sys.executable, str(gate)],
                    input=json.dumps(event),
                    capture_output=True,
                    text=True,
                    env={**env, "WORKFLOW_HOST": "codex"},
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)

            prep = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--root",
                    str(root),
                    "prepare",
                    "--task",
                    "T-NEW",
                    "--tier",
                    "轻量",
                    "--acceptance",
                    "A1",
                    "--details-json",
                    json.dumps(_minimal_details(), ensure_ascii=False),
                    "--executor",
                    "codex",
                    "--session",
                    "sess-hook",
                    "--request-tier",
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(prep.returncode, 0, prep.stdout + prep.stderr)
            prep_payload = json.loads(prep.stdout)
            self.assertTrue(prep_payload["confirmation"]["hook_active"])
            self.assertEqual(prep_payload["confirmation"]["hook_host"], "codex")

            confirm = subprocess.run(
                [sys.executable, str(gate)],
                input=json.dumps({"cwd": str(root), "session_id": "sess-hook", "hook_event_name": "UserPromptSubmit", "prompt": "**`选标准档`**"}),
                capture_output=True,
                text=True,
                env={**env, "WORKFLOW_HOST": "codex"},
            )
            self.assertEqual(confirm.returncode, 0, confirm.stderr)
            self.assertIn("ENGINE_CONFIRMATION_RECORDED", confirm.stdout)

            task = Engine(root, workflow_engine_cli.default_db(root)).status("T-NEW")
            self.assertEqual(task["tier"], "standard")
            self.assertNotIn("tier_confirmation", task["missing"])
            self.assertEqual(
                subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip(),
                "",
            )


if __name__ == "__main__":
    unittest.main()
