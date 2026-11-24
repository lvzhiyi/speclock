"""双宿主模拟门禁测试，不代表真实宿主端到端验证。"""
import os
import json
import shlex
from pathlib import Path
import tempfile
import subprocess
import sys
import uuid
import unittest
from unittest.mock import patch

import host_gate


class HostGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "ai-workflow.yaml").write_text("version: 1\nengine:\n  enabled: false\n", encoding="utf-8")
        # 本组验证 Claude 回执契约，不能继承启动测试的 Cursor/Codex 宿主。
        self.env = patch.dict(os.environ, {"WORKFLOW_HOST": "claude", "WORKFLOW_TASK_ID": "T1", "WORKFLOW_ROUND_ID": "r1", "WORKFLOW_EXECUTOR": "agent"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def event(self, tool="Edit", **data):
        return {"cwd": str(self.root), "session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": data}

    def task(self, state="implementing", missing=None):
        return {"protocol_version": 2, "id": "T1", "version": 3, "current_round": "r1", "state": state, "scope": ["src"], "baseline": ["rules.md"], "missing": missing or [], "rounds": [{"id": "r1", "executor": "agent", "session_id": "s1", "binding_version": 1}]}

    def test_read_only_never_hashes_task(self):
        with patch.object(host_gate, "load_task", side_effect=AssertionError("不应查询全量哈希")):
            self.assertIsNone(host_gate.pre_tool(self.event("Read", file_path="rules.md")))
            self.assertIsNone(host_gate.pre_tool(self.event("Bash", command="git status --short")))

    def test_native_progress_updates_are_observational(self):
        with patch.object(host_gate, "load_task", side_effect=AssertionError("展示进度不应查询授权或源码哈希")):
            for tool in ("TodoWrite", "update_plan"):
                with self.subTest(tool=tool):
                    self.assertIsNone(host_gate.pre_tool(self.event(tool, todos=[])))

    def test_arbitrary_shell_and_mcp_are_writes(self):
        for tool, data in [("Bash", {"command": "python3 -c 'open(\"x\",\"w\")'"}), ("Bash", {"command": "git status; touch x"}), ("mcp__service__update", {})]:
            with self.subTest(tool=tool), patch.object(host_gate, "load_task", return_value=self.task(missing=["tier_confirmation"])):
                self.assertIn("tier_confirmation", host_gate.pre_tool(self.event(tool, **data)))

    def test_binding_state_and_baseline_are_required(self):
        (self.root / "rules.md").write_text("规范", encoding="utf-8")
        for state in ("review_passed", "created", "cancelled"):
            with patch.object(host_gate, "load_task", return_value=self.task(state)):
                self.assertIsNotNone(host_gate.pre_tool(self.event(file_path="src/a.py")))
        with patch.object(host_gate, "load_task", return_value=self.task()):
            self.assertIsNone(host_gate.pre_tool(self.event(file_path="src/a.py")))
            with patch.dict(os.environ, {"WORKFLOW_EXECUTOR": "other"}):
                self.assertIn("绑定", host_gate.pre_tool(self.event(file_path="src/a.py")))

    def test_config_baseline_cannot_be_omitted(self):
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  required:\n    - required.md\n", encoding="utf-8")
        with patch.object(host_gate, "load_task", return_value=self.task()):
            self.assertIn("required.md", host_gate.pre_tool(self.event(file_path="src/a.py")))

    def test_shell_read_allowlist_rejects_execution_features(self):
        for command in ("python -c pass", "rg --pre python x", "git -c alias.x='!touch x' x", "find . -exec touch x ;", "cat x > y", "env python -c pass", "git diff --output=x", "git diff --ext-diff"):
            self.assertFalse(host_gate.readonly_shell(command), command)
        for command in ("git status --short", "rg -n needle src", "pwd", "ls -la", "cat rules.md"):
            self.assertTrue(host_gate.readonly_shell(command), command)

    def test_readonly_chains_preserve_quotes_and_reject_unknown_syntax(self):
        for command in ("pwd && git remote -v", "git symbolic-ref --short refs/remotes/origin/HEAD", "rg 'a && b' src && git --no-pager diff", 'rg "a && b" src && pwd'):
            self.assertTrue(host_gate.readonly_shell(command), command)
        for command in ("pwd &&", "&& pwd", "pwd && && ls", "pwd & ls", "pwd || ls", "pwd; ls", "pwd | cat", "pwd && cat x > y", "pwd && $(touch x)", "pwd && `touch x`", "pwd && git remote remove origin", "pwd && git symbolic-ref --delete HEAD", "pwd && git symbolic-ref HEAD refs/heads/x", "pwd && git -c alias.x=x status", "pwd && python3 -c pass"):
            self.assertFalse(host_gate.readonly_shell(command), command)
        event = self.event("Shell", cmd=["bash", "-lc", "git diff && git --no-pager show HEAD"], timeout=9)
        updated = host_gate.safe_shell_input(event)
        self.assertEqual(updated["timeout"], 9)
        self.assertEqual(updated["cmd"][:2], ["bash", "-lc"])
        self.assertEqual(updated["cmd"][2].count("--no-ext-diff"), 2)
        self.assertEqual(updated["cmd"][2].count("--no-textconv"), 2)
        with patch.object(host_gate, "load_task", side_effect=AssertionError("只读组合不得读取任务全量快照")):
            self.assertIsNone(host_gate.pre_tool(self.event("Shell", command="git status && git remote -v")))

    def test_scoped_baselines_cover_directory_and_real_target(self):
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  scoped:\n    - src/**/*.py => python.md\n    - other/** => other.md\n", encoding="utf-8")
        with patch.object(host_gate, "load_task", return_value=self.task()):
            self.assertIn("python.md", host_gate.pre_tool(self.event(file_path="src/new.py")))
            self.assertIn("other.md", host_gate.pre_tool(self.event(file_path="other/new.txt")))

    def test_full_tier_unapproved_and_other_session_are_denied(self):
        task = self.task(missing=["approval"])
        with patch.object(host_gate, "load_task", return_value=task):
            self.assertIn("approval", host_gate.pre_tool(self.event(file_path="src/a.py")))
            event = self.event(file_path="src/a.py")
            event["session_id"] = "s2"
            self.assertIn("绑定", host_gate.pre_tool(event))

    def test_plan_exception_only_explicit_document_paths(self):
        with patch.dict(os.environ, {"WORKFLOW_PLAN_PATHS": "docs/plan.md"}), patch.object(host_gate, "load_task", side_effect=ValueError("unbound")):
            self.assertIsNotNone(host_gate.pre_tool(self.event("Write", file_path="docs/plan.md")))
            self.assertIsNotNone(host_gate.pre_tool(self.event("Write", file_path="docs/source.py")))
            self.assertIsNotNone(host_gate.pre_tool(self.event("Write", file_path="docs/other.md")))

    def test_read_receipt_rejects_truncated_failed_and_unknown_schemas(self):
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  required:\n    - rules.md\n", encoding="utf-8")
        (self.root / "rules.md").write_text("完整规范", encoding="utf-8")
        for response in ({"error": "failed"}, "完整规范", {"file": {"content": "完整", "startLine": 1, "numLines": 1, "totalLines": 2}}):
            event = self.event("Read", file_path="rules.md")
            event["tool_response"] = response
            with patch.object(host_gate, "load_task", side_effect=AssertionError("失败读取不应登记")):
                self.assertIn("ENGINE_BASELINE_UNREAD", host_gate.post_tool(event))

    def test_read_receipt_registers_full_exact_content_with_binding(self):
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  required:\n    - rules.md\n", encoding="utf-8")
        (self.root / "rules.md").write_text("完整规范", encoding="utf-8")
        event = self.event("Read", file_path="rules.md")
        event["tool_response"] = {"file": {"content": "完整规范", "startLine": 1, "numLines": 1, "totalLines": 1}}
        with patch.object(host_gate, "load_task", return_value=self.task()), patch("workflow_engine.engine.Engine") as engine:
            self.assertIn("ENGINE_BASELINE_RECORDED", host_gate.post_tool(event))
            args = engine.return_value.register_baseline.call_args.args
            self.assertEqual(args[1], 3)
            self.assertEqual(args[3]["round_id"], "r1")
            self.assertEqual(args[3]["executor"], "agent")
            self.assertTrue(args[3]["complete"])

    def test_real_engine_binding_read_receipt_and_invalidation(self):
        from workflow_engine.engine import Engine
        from workflow_engine_cli import default_db
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  required:\n    - rules.md\n", encoding="utf-8")
        (self.root / "rules.md").write_text("完整规范", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src/a.py").write_text("pass", encoding="utf-8")
        engine_home = tempfile.TemporaryDirectory()
        self.addCleanup(engine_home.cleanup)
        with patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": engine_home.name}):
            engine = Engine(self.root, default_db(self.root))
            plan = {"version": 1, "checks": [{"id": "all", "argv": [sys.executable, "-c", "pass"], "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"], "acceptance": ["A1"]}]}
            task = engine.create("T1", "light", ["A1"], plan, str(uuid.uuid4()), details={"goal": "目标", "scope": ["src"], "source": "用户", "dependencies": [], "baseline": ["rules.md"], "steps": [{"id": "s1", "title": "实现"}]})
            task = engine.confirm_tier("T1", task["version"], str(uuid.uuid4()), "用户")
            task = engine.bind_executor("T1", task["version"], str(uuid.uuid4()), "agent", "s1")
            with patch.dict(os.environ):
                for key in ("WORKFLOW_TASK_ID", "WORKFLOW_EXECUTOR", "WORKFLOW_ROUND_ID"):
                    os.environ.pop(key, None)
                self.assertIn("baseline", host_gate.pre_tool(self.event(file_path="src/a.py")))
                read = self.event("Read", file_path="rules.md")
                read["hook_event_name"] = "PostToolUse"
                read["tool_response"] = {"file": {"content": "完整规范", "startLine": 1, "numLines": 1, "totalLines": 1}}
                self.assertIn("RECORDED", host_gate.post_tool(read))
                task = engine.status("T1")
                engine.start("T1", task["version"], str(uuid.uuid4()))
                self.assertIsNone(host_gate.pre_tool(self.event(file_path="src/a.py")))
                wrong = self.event(file_path="src/a.py")
                wrong["session_id"] = "other-session"
                self.assertIsNotNone(host_gate.pre_tool(wrong))
                current = engine.status("T1")
                engine.return_task("T1", current["version"], str(uuid.uuid4()), "重新授权", "用户")
                self.assertIsNotNone(host_gate.pre_tool(self.event(file_path="src/a.py")))
                (self.root / "rules.md").write_text("已经变更的规范", encoding="utf-8")
                self.assertIsNotNone(host_gate.pre_tool(self.event(file_path="src/a.py")))

    def test_pending_confirmation_matches_task_round_digest_and_call(self):
        task = self.task()
        task["control_digest"] = "digest"
        question = "workflow-confirm:T1:r1:digest:tier_confirmation"
        event = self.event("AskUserQuestion", questions=[{"question": question, "options": [{"label": "确认"}, {"label": "拒绝"}]}])
        event["tool_use_id"] = "call1"
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": home, "WORKFLOW_HOST": "claude"}), patch.object(host_gate, "load_task", return_value=task), patch("workflow_engine.engine.Engine") as engine:
            self.assertIsNone(host_gate.pre_tool(event))
            event["tool_response"] = {"answers": {question: "确认"}}
            wrong = dict(event, tool_use_id="wrong")
            self.assertIn("UNSUPPORTED", host_gate.post_tool(wrong))
            engine.return_value.confirm_tier.assert_not_called()
            self.assertIn("RECORDED", host_gate.post_tool(event))
            engine.return_value.confirm_tier.assert_called_once()
            task["version"] += 1
            self.assertIn("REJECTED", host_gate.post_tool(event))
            engine.return_value.confirm_tier.assert_called_once()
            event = dict(event, tool_name="ExitPlanMode", tool_use_id="call2", tool_input={"plan": "workflow-confirm:T1:r1:digest:approval"}, tool_response={"approved": True})
            self.assertIsNone(host_gate.pre_tool(event))
            self.assertIn("RECORDED", host_gate.post_tool(event))
            engine.return_value.approve_proposal.assert_called_once()

    def test_cli_inline_create_bind_read_start_without_parent_binding(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "rules.md").write_text("规范", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src/a.py").write_text("pass", encoding="utf-8")
        cli = str(Path(host_gate.__file__).with_name("workflow_engine_cli.py"))
        plan = {"version": 1, "checks": [{"id": "all", "argv": [sys.executable, "-c", "pass"], "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"], "acceptance": ["A1"]}]}
        details = {"goal": "含 $ 和 ; 的目标", "scope": ["src"], "source": "用户", "dependencies": [], "baseline": ["rules.md"], "steps": [{"id": "s1", "title": "实现"}]}
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": home}):
            for key in ("WORKFLOW_TASK_ID", "WORKFLOW_ROUND_ID", "WORKFLOW_EXECUTOR"):
                os.environ.pop(key, None)
            def run(action, *args):
                argv = ["python3", cli, "--root", str(self.root), action, "--task", "T1", *args]
                if action != "create":
                    current = run.current
                    argv += ["--version", str(current["version"])]
                argv += ["--request", str(uuid.uuid4())]
                self.assertIsNone(host_gate.pre_tool(self.event("exec_command", cmd=shlex.join(argv))))
                result = subprocess.run(argv, text=True, capture_output=True, env=os.environ.copy())
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                run.current = json.loads(result.stdout)["task"]
                return run.current
            run("create", "--tier", "轻量", "--acceptance", "A1", "--plan-json", json.dumps(plan), "--details-json", json.dumps(details, ensure_ascii=False))
            run("bind-executor", "--executor", "agent", "--session", "s1")
            task = run.current
            marker = "workflow-confirm:T1:" + task["current_round"] + ":" + task["control_digest"] + ":tier_confirmation"
            confirmation = self.event("AskUserQuestion", questions=[{"question": marker}])
            confirmation["tool_use_id"] = "native-confirm-call"
            with patch.dict(os.environ, {"WORKFLOW_HOST": "claude"}):
                self.assertIsNone(host_gate.pre_tool(confirmation))
                confirmation["tool_response"] = {"answers": {marker: "确认"}}
                self.assertIn("RECORDED", host_gate.post_tool(confirmation))
            host_gate.CURRENT_EVENT.set(self.event())
            run.current = host_gate.load_task(self.root)
            run("read-baseline", "--path", "rules.md", "--executor", "agent", "--session", "s1")
            run("start")
            self.assertIsNone(host_gate.pre_tool(self.event(file_path="src/a.py")))
            wrong = self.event(file_path="src/a.py")
            wrong["session_id"] = "wrong"
            self.assertIsNotNone(host_gate.pre_tool(wrong))

    def test_ordinary_questions_and_plans_do_not_require_binding_or_approve(self):
        for tool, data in (("AskUserQuestion", {"questions": [{"question": "需要什么功能？"}]}), ("ExitPlanMode", {"plan": "先调查需求"})):
            event = self.event(tool, **data)
            event["tool_response"] = {"approved": True, "answers": {"需要什么功能？": "确认"}}
            with patch.object(host_gate, "load_task", side_effect=AssertionError("普通澄清不查询任务")):
                self.assertIsNone(host_gate.pre_tool(event))
                self.assertIsNone(host_gate.post_tool(event))

    def test_malformed_confirmation_marker_never_becomes_approval(self):
        for text in ("workflow-confirm:", "workflow-confirm:wrong:round:digest:approval", "workflow-confirm:T1:r1:digest:tier_confirmation-extra"):
            event = self.event("AskUserQuestion", questions=[{"question": text}])
            event["tool_use_id"] = "bad-marker"
            event["tool_response"] = {"answers": {text: "确认"}}
            with patch.object(host_gate, "load_task", return_value={**self.task(), "control_digest": "digest"}), patch("workflow_engine.engine.Engine") as engine:
                self.assertIsNotNone(host_gate.pre_tool(event))
                self.assertNotIn("RECORDED", host_gate.post_tool(event) or "")
                engine.return_value.confirm_tier.assert_not_called()

    def test_session_lookup_ignores_terminal_tasks_and_bounds_resources(self):
        import sqlite3
        from session_binding import lookup
        database = self.root / "state.sqlite"
        def record(identifier, state):
            task = self.task(state)
            task.update(id=identifier, root=str(self.root.resolve()))
            return json.dumps(task)
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, data TEXT)")
            db.executemany("INSERT INTO tasks VALUES(?,?)", [("old", record("old", "review_passed")), ("cancelled", record("cancelled", "cancelled")), ("active", record("active", "implementing"))])
        self.assertEqual(lookup(self.root, "s1", database), "active")
        with patch("session_binding.MAX_TASKS", 2):
            with self.assertRaisesRegex(ValueError, "LIMIT"):
                lookup(self.root, "s1", database)
        with patch("session_binding.MAX_TASK_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "LIMIT"):
                lookup(self.root, "s1", database)
        with patch("session_binding.MAX_TOTAL_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "LIMIT"):
                lookup(self.root, "s1", database)
        missing = self.root / "missing" / "state.sqlite"
        with self.assertRaises(ValueError):
            lookup(self.root, "s1", missing)
        self.assertFalse(missing.parent.exists())

    def test_stale_confirmation_cannot_approve(self):
        task = self.task()
        task["control_digest"] = "digest"
        question = "workflow-confirm:T1:r1:digest:tier_confirmation"
        event = self.event("AskUserQuestion", questions=[{"question": question}])
        event["tool_use_id"] = "call1"
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": home, "WORKFLOW_HOST": "claude"}), patch.object(host_gate, "load_task", return_value=task), patch("workflow_engine.engine.Engine") as engine:
            self.assertIsNone(host_gate.pre_tool(event))
            task["current_round"] = "different"
            event["tool_response"] = {"answers": {question: "确认"}}
            self.assertIn("REJECTED", host_gate.post_tool(event))
            engine.return_value.confirm_tier.assert_not_called()

    def test_explicit_mcp_allowlist_and_dashboard_status(self):
        command = "python3 " + str(Path(host_gate.__file__).with_name("dashboard_server.py"))
        self.assertTrue(host_gate.dashboard_command(command + " status --root /tmp"))
        self.assertTrue(host_gate.dashboard_command(command + " on"))
        with patch.dict(os.environ, {"WORKFLOW_READONLY_MCP_TOOLS": "mcp__known__read"}), patch.object(host_gate, "load_task", side_effect=ValueError("unbound")):
            self.assertIsNone(host_gate.pre_tool(self.event("mcp__known__read")))
            self.assertIsNotNone(host_gate.pre_tool(self.event("mcp__unknown__read")))

    def test_codex_real_shapes_and_quoted_inline_json(self):
        cli = Path(host_gate.__file__).with_name("workflow_engine_cli.py")
        command = "python3 " + str(cli) + " create --details-json '{\"goal\":\"$x; $(touch bad)\"}'"
        self.assertTrue(host_gate.engine_command(command))
        self.assertFalse(host_gate.engine_command("python3 " + str(cli) + ' create --details-json "$(touch bad)"'))
        for data in ({"cmd": "git status --short"}, {"command": ["bash", "-lc", "git status --short"]}):
            event = self.event("exec_command", **data)
            with patch.object(host_gate, "load_task", side_effect=AssertionError("不应哈希")):
                self.assertIsNone(host_gate.pre_tool(event))
        event = self.event("exec_command", cmd="git --no-pager diff src")
        self.assertIn("--no-ext-diff", host_gate.safe_shell_input(event)["cmd"])
        self.assertIn("--no-textconv", host_gate.safe_shell_input(event)["cmd"])

    def test_oversize_baseline_is_not_registered(self):
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  required:\n    - rules.md\n", encoding="utf-8")
        (self.root / "rules.md").write_bytes(b"x" * 1048577)
        event = self.event("Read", file_path="rules.md")
        event["tool_response"] = {"file": {"content": "x", "startLine": 1, "numLines": 1, "totalLines": 1}}
        self.assertIn("1MiB", host_gate.post_tool(event))

    def test_native_confirmation_has_no_unverified_auto_approval(self):
        with patch.object(host_gate, "load_task", side_effect=AssertionError("不能批准")):
            self.assertIsNone(host_gate.post_tool(self.event("AskUserQuestion")))

    def test_archive_command_allowlist_and_boundaries(self):
        script = Path(host_gate.__file__).with_name("archive_change.py").absolute()
        base = f"python3 {script}"
        allowed = (
            f"{base} --help",
            f"{base} --root {self.root} --task T1 --dry-run",
            f"WORKFLOW_HOST=cursor {base} --root {self.root} --task T1 --task T2 --changes-dir openspec/changes --month 2026-11",
        )
        for cmd in allowed:
            with self.subTest(allowed=cmd), patch.object(host_gate, "load_task", side_effect=ValueError("unbound")):
                self.assertIsNone(host_gate.pre_tool(self.event("Bash", command=cmd)))
        rejected = (
            f"{base} --root /tmp --task T1",
            f"{base} --root {self.root}",
            f"{base} --root {self.root} --task T1 --month bad",
            f"{base} --root {self.root} --task T1 --evil x",
            f"{base} --root {self.root} --task T1 && touch x",
            f"python3 /tmp/archive_change.py --root {self.root} --task T1",
        )
        for cmd in rejected:
            with self.subTest(rejected=cmd), patch.object(host_gate, "load_task", side_effect=ValueError("unbound")):
                self.assertIsNotNone(host_gate.pre_tool(self.event("Bash", command=cmd)))

    def test_chat_reply_parsing_tolerates_paired_wrappers_and_rejects_prose(self):
        valid = (
            ("选标准档", ("tier_confirmation", "standard")),
            ("`选标准档`", ("tier_confirmation", "standard")),
            ("**`选标准档`**", ("tier_confirmation", "standard")),
            ("`**选标准档**`", ("tier_confirmation", "standard")),
            ("**选轻量档**", ("tier_confirmation", "light")),
            ("「选完整档」", ("tier_confirmation", "full")),
            ("【选标准档】", ("tier_confirmation", "standard")),
            (" \u3000\ufeff“选标准档”\n ", ("tier_confirmation", "standard")),
            ("```\n选标准档\n```", ("tier_confirmation", "standard")),
            ("批准方案", ("approval", None)),
            ("“批准方案”", ("approval", None)),
            ("**`批准方案`**", ("approval", None)),
        )
        for text, expected in valid:
            with self.subTest(valid=text):
                self.assertEqual(host_gate.parse_chat_confirmation_reply(text), expected)
        rejected = ("我建议选完整档", "选标准档？", "**选标准档", "`选标准档` 吧", "请批准方案", "", None, 123)
        for text in rejected:
            with self.subTest(rejected=text):
                self.assertEqual(host_gate.parse_chat_confirmation_reply(text), (None, None))

    def test_chat_confirmation_channel_is_host_agnostic_with_legacy_fallback(self):
        task = {
            **self.task("created", missing=["tier_confirmation", "baseline"]),
            "control_digest": "digest",
            "tier": "light",
        }
        with tempfile.TemporaryDirectory() as home:
            base_env = {k: v for k, v in os.environ.items() if k not in {"WORKFLOW_HOST", "CODEX_THREAD_ID", "CURSOR_PROJECT_DIR", "CURSOR_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "CLAUDECODE"}}
            base_env["WORKFLOW_ENGINE_HOME"] = home
            with patch.dict(os.environ, base_env, clear=True):
                with self.assertRaises(Exception):
                    with patch.dict(os.environ, {"WORKFLOW_HOST": "invalid"}):
                        host_gate.request_chat_confirmation(self.root, task, 3, "s1", "tier_confirmation", "req-bad")
                prepared = host_gate.request_chat_confirmation(self.root, task, 3, "s1", "tier_confirmation", "req-1")
                self.assertFalse(prepared["hook_active"])
                self.assertIn("ENGINE_HOOK_INACTIVE", prepared["hook_warning"])

            for host in ("codex", "cursor", "claude"):
                with self.subTest(host=host), \
                        patch.dict(os.environ, {**base_env, "WORKFLOW_HOST": host}, clear=True), \
                        patch.object(host_gate, "load_task", return_value=task), \
                        patch("workflow_engine.engine.Engine") as engine:
                    event = {"cwd": str(self.root), "session_id": "s1", "hook_event_name": "UserPromptSubmit", "prompt": "**`选标准档`**\n"}
                    res = host_gate.chat_confirmation(event, self.root)
                    self.assertIn("ENGINE_CONFIRMATION_RECORDED", res)
                    engine.return_value.confirm_tier.assert_called_once_with("T1", 3, "req-1", host + " 用户聊天回复", "standard")

            # 删除统一通道文件，验证对旧版宿主前缀通道文件的向后兼容回退。
            with patch.dict(os.environ, {**base_env, "WORKFLOW_HOST": "codex"}, clear=True), \
                    patch.object(host_gate, "load_task", return_value=task), \
                    patch("workflow_engine.engine.Engine") as engine:
                host_gate.pending_path(self.root, "s1", "chat:").unlink()
                legacy_pending = dict(host_gate.confirmation_target(task, "tier_confirmation"), request="req-legacy")
                host_gate.save_pending(host_gate.pending_path(self.root, "s1", "codex:chat:"), legacy_pending, root=self.root)
                res = host_gate.chat_confirmation({"cwd": str(self.root), "session_id": "s1", "hook_event_name": "UserPromptSubmit", "prompt": "选完整档"}, self.root)
                self.assertIn("ENGINE_CONFIRMATION_RECORDED", res)
                engine.return_value.confirm_tier.assert_called_once_with("T1", 3, "req-legacy", "codex 用户聊天回复", "full")

    def test_hook_activity_recording_and_confirmation_diagnostics(self):
        with tempfile.TemporaryDirectory() as home:
            base_env = {k: v for k, v in os.environ.items() if k not in {"WORKFLOW_HOST", "CODEX_THREAD_ID", "CURSOR_PROJECT_DIR", "CURSOR_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "CLAUDECODE"}}
            base_env["WORKFLOW_ENGINE_HOME"] = home
            with patch.dict(os.environ, {**base_env, "CODEX_THREAD_ID": "s1"}, clear=True):
                inactive = host_gate.hook_confirmation_status(self.root, "s1")
                self.assertFalse(inactive["hook_active"])
                self.assertEqual(inactive["hook_events"], [])
                self.assertIn("ENGINE_HOOK_INACTIVE", inactive["hook_warning"])
                self.assertIn("Settings → Hooks", inactive["hook_warning"])

            with patch.dict(os.environ, {**base_env, "WORKFLOW_HOST": "codex"}, clear=True):
                host_gate.record_hook_activity(self.root, {"session_id": "s1", "hook_event_name": "SessionStart"})
                partial = host_gate.hook_confirmation_status(self.root, "s1")
                self.assertFalse(partial["hook_active"])
                self.assertEqual(partial["hook_host"], "codex")
                self.assertEqual(partial["hook_events"], ["SessionStart"])
                self.assertIn("UserPromptSubmit", partial["hook_warning"])

                activity_file = host_gate.hook_activity_path(self.root, "s1")
                with patch.object(host_gate, "save_pending", side_effect=AssertionError("重复事件不应重写磁盘")):
                    host_gate.record_hook_activity(self.root, {"session_id": "s1", "hook_event_name": "SessionStart"})
                self.assertTrue(activity_file.is_file())

                host_gate.record_hook_activity(self.root, {"session_id": "s1", "hook_event_name": "UserPromptSubmit"})
                active = host_gate.hook_confirmation_status(self.root, "s1")
                self.assertTrue(active["hook_active"])
                self.assertEqual(active["hook_host"], "codex")
                self.assertEqual(active["hook_events"], ["SessionStart", "UserPromptSubmit"])
                self.assertNotIn("hook_warning", active)

        # 异常状态（如 .speclock 为符号链接）时记录活跃状态不得阻断门禁主路径。
        sym_root = Path(self.tmp.name) / "sym"
        sym_root.mkdir()
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (sym_root / ".speclock").symlink_to(outside)
        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "WORKFLOW_ENGINE_HOME"}, clear=True):
            host_gate.record_hook_activity(sym_root, {"session_id": "s1", "hook_event_name": "PreToolUse"})

    def test_native_single_choice_approval_validation_and_receipt(self):
        task = self.task()
        task["control_digest"] = "digest"
        marker = "workflow-confirm:T1:r1:digest:approval"
        question_text = "请确认完整档方案 " + marker
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": home, "WORKFLOW_HOST": "claude"}), patch.object(host_gate, "load_task", return_value=task), patch("workflow_engine.engine.Engine") as engine:
            bad_inputs = (
                {"questions": [{"question": question_text, "options": [{"label": "批准方案"}]}]},
                {"questions": [{"question": question_text, "options": [{"label": "批准方案"}, {"label": "批准方案"}]}]},
                {"questions": [{"question": question_text, "multiSelect": True, "options": [{"label": "批准方案"}, {"label": "需要修改"}]}]},
                {"questions": [{"question": question_text, "options": [{"label": "批准方案"}, {"label": "需要修改"}]}], "answers": {question_text: "批准方案"}},
            )
            for payload in bad_inputs:
                bad_event = self.event("AskUserQuestion", **payload)
                bad_event["tool_use_id"] = "bad-call"
                self.assertIn("ENGINE_CONFIRMATION_REQUIRED", host_gate.pre_tool(bad_event))

            event = self.event("AskUserQuestion", questions=[{"question": question_text, "multiSelect": False, "options": [{"label": "批准方案"}, {"label": "需要修改"}]}])
            event["tool_use_id"] = "approve-call"
            self.assertIsNone(host_gate.pre_tool(event))
            rejected = dict(event, tool_response={"answers": {question_text: "需要修改"}})
            self.assertIn("REJECTED", host_gate.post_tool(rejected))
            engine.return_value.approve_proposal.assert_not_called()

            approved = dict(event, tool_response={"answers": {question_text: "批准方案"}})
            self.assertIn("RECORDED", host_gate.post_tool(approved))
            engine.return_value.approve_proposal.assert_called_once()

    def test_hook_activity_heartbeat_throttle_and_stop_transition(self):
        with tempfile.TemporaryDirectory() as home:
            env = {k: v for k, v in os.environ.items() if k not in {"WORKFLOW_HOST", "CODEX_THREAD_ID", "CURSOR_PROJECT_DIR", "CURSOR_PLUGIN_ROOT"}}
            env["WORKFLOW_ENGINE_HOME"] = home
            env["WORKFLOW_HOST"] = "claude"
            with patch.dict(os.environ, env, clear=True):
                with patch("host_gate.time.time", return_value=1000.0):
                    host_gate.record_hook_activity(self.root, {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Edit"})
                data = host_gate.read_hook_activity(self.root, "s1")
                self.assertEqual(data["last_event"], "PreToolUse")
                self.assertEqual(data["last_tool"], "Edit")
                self.assertEqual(data["updated_at"], 1000.0)

                with patch("host_gate.time.time", return_value=1005.0), patch.object(host_gate, "save_pending", side_effect=AssertionError("15秒内重复事件应节流")):
                    host_gate.record_hook_activity(self.root, {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Edit"})

                with patch("host_gate.time.time", return_value=1020.0):
                    host_gate.record_hook_activity(self.root, {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash"})
                data = host_gate.read_hook_activity(self.root, "s1")
                self.assertEqual(data["updated_at"], 1020.0)
                self.assertEqual(data["last_tool"], "Bash")

                with patch("host_gate.time.time", return_value=1022.0):
                    host_gate.record_hook_activity(self.root, {"session_id": "s1", "hook_event_name": "Stop"})
                data = host_gate.read_hook_activity(self.root, "s1")
                self.assertEqual(data["last_event"], "Stop")
                self.assertEqual(data["updated_at"], 1022.0)

                with patch("host_gate.time.time", return_value=1024.0):
                    host_gate.record_hook_activity(self.root, {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Read"})
                data = host_gate.read_hook_activity(self.root, "s1")
                self.assertEqual(data["last_event"], "PreToolUse")
                self.assertEqual(data["last_tool"], "Read")
                self.assertEqual(data["updated_at"], 1024.0)

    def test_hook_precheck_status_and_session_resolution(self):
        proj = Path(self.tmp.name) / "precheck_proj"
        proj.mkdir()
        clean_env = {
            k: v for k, v in os.environ.items()
            if k not in {"WORKFLOW_HOST", "WORKFLOW_ENGINE_HOME", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID", "CURSOR_PROJECT_DIR", "CURSOR_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "CLAUDECODE"}
        }
        with patch.dict(os.environ, clean_env, clear=True):
            initial = host_gate.hook_precheck_status(proj)
            self.assertFalse(initial["hook_active"])
            self.assertEqual(initial["hook_events"], [])
            self.assertIn("ENGINE_HOOK_INACTIVE", initial["hook_warning"])
            self.assertIn("原生单选卡片", initial["hook_warning"])
            self.assertFalse((proj / ".speclock").exists())

        with patch.dict(os.environ, {**clean_env, "WORKFLOW_HOST": "codex"}, clear=True):
            host_gate.record_hook_activity(proj, {"session_id": "sess-old", "hook_event_name": "SessionStart"})
            host_gate.record_hook_activity(proj, {"session_id": "sess-old", "hook_event_name": "UserPromptSubmit"})

        stale_task = {"rounds": [{"id": "r1", "session_id": "sess-old"}]}
        with patch.dict(os.environ, {**clean_env, "CODEX_THREAD_ID": "sess-new"}, clear=True):
            mismatch = host_gate.hook_precheck_status(proj, task=stale_task)
            self.assertEqual(mismatch["session_id"], "sess-new")
            self.assertFalse(mismatch["hook_active"])
            self.assertTrue(mismatch["other_active_sessions"])
            self.assertIn("ENGINE_HOOK_INACTIVE", mismatch["hook_warning"])
            self.assertIn("Settings → Hooks", mismatch["hook_warning"])
            self.assertIn("--session", mismatch["hook_warning"])

        with patch.dict(os.environ, clean_env, clear=True):
            unknown = host_gate.hook_precheck_status(proj)
            self.assertIsNone(unknown["hook_active"])
            self.assertEqual(unknown["hook_events"], [])
            self.assertIn("ENGINE_HOOK_SESSION_UNKNOWN", unknown["hook_warning"])

            from_task = host_gate.hook_precheck_status(proj, task=stale_task)
            self.assertEqual(from_task["session_id"], "sess-old")
            self.assertTrue(from_task["hook_active"])
            self.assertEqual(from_task["hook_host"], "codex")
            self.assertNotIn("hook_warning", from_task)

        with patch.dict(os.environ, {**clean_env, "WORKFLOW_HOST": "codex"}, clear=True):
            host_gate.record_hook_activity(proj, {"session_id": "sess-new", "hook_event_name": "SessionStart"})
            host_gate.record_hook_activity(proj, {"session_id": "sess-new", "hook_event_name": "UserPromptSubmit"})
            ready = host_gate.hook_precheck_status(proj, session="sess-new")
            self.assertTrue(ready["hook_active"])
            self.assertEqual(ready["hook_host"], "codex")
            self.assertNotIn("hook_warning", ready)
            self.assertNotIn("other_active_sessions", ready)

    def test_recommended_suffix_only_accepted_for_native_options(self):
        self.assertEqual(host_gate.normalize_tier_label("轻量档 (Recommended)", allow_recommended=True), "light")
        self.assertEqual(host_gate.normalize_tier_label("标准档（推荐）", allow_recommended=True), "standard")
        self.assertTrue(host_gate.is_approval_accept_label("批准方案 (Recommended)", allow_recommended=True))
        self.assertEqual(host_gate.parse_chat_confirmation_reply("选轻量档 (Recommended)"), (None, None))
        self.assertEqual(host_gate.parse_chat_confirmation_reply("批准方案 (Recommended)"), (None, None))
