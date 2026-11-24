"""钩子进程双宿主模拟测试；不是实际宿主端到端测试。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).parent


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "project"
        self.project.mkdir()
        (self.project / "ai-workflow.yaml").write_text("version: 1\nengine:\n  enabled: false\n", encoding="utf-8")
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()
        (self.state / "disabled").touch()

    def hook(self, name, host="claude", raw=None, cwd=None, **extra):
        event = {"session_id": "s1", "cwd": str(cwd or self.project), "hook_event_name": name, **extra}
        env = {k: v for k, v in os.environ.items() if not k.startswith("WORKFLOW_")}
        env.update(WORKFLOW_HOST=host, WORKFLOW_GATE_DIR=str(self.state), WORKFLOW_ENGINE_HOME=self.tmp.name)
        return subprocess.run([sys.executable, str(HERE / "workflow_gate.py")], input=json.dumps(event) if raw is None else raw,
                              text=True, capture_output=True, env=env)

    def test_disabled_switches_do_not_bypass_pretool(self):
        for host in ("claude", "codex"):
            for tool, data in (("Edit", {"file_path": "src/a.py"}), ("Write", {"file_path": "a.py"}),
                               ("apply_patch", {"command": "*** Add File: x.py"}), ("Bash", {"command": "python3 -c pass"}),
                               ("mcp__example__update", {})):
                with self.subTest(host=host, tool=tool):
                    result = self.hook("PreToolUse", host, tool_name=tool, tool_input=data)
                    self.assertEqual(result.returncode, 0)
                    value = json.loads(result.stdout)["hookSpecificOutput"]
                    self.assertEqual(value["permissionDecision"], "deny")
                    self.assertIn("ENGINE_TASK_UNBOUND", value["permissionDecisionReason"])
                    self.assertNotIn('"ask"', result.stdout)

    def test_readonly_and_unconfigured_project_are_allowed(self):
        for tool, data in (("Read", {"file_path": "rules.md"}), ("Bash", {"command": "git status --short"})):
            self.assertEqual(self.hook("PreToolUse", tool_name=tool, tool_input=data).stdout, "")
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        self.assertEqual(self.hook("PreToolUse", cwd=other, tool_name="Write", tool_input={"file_path": "x.py"}).stdout, "")
        # 未接入的独立 .git 仓库（哪怕嵌套在已接入父目录下）也必须完全旁路门禁。
        for repo in (other / "git_repo", self.project / "nested_git_repo"):
            (repo / ".git").mkdir(parents=True)
            for host in ("claude", "codex"):
                for tool, data in (("Write", {"file_path": "x.py"}), ("Bash", {"command": "npm test"}), ("mcp__example__update", {})):
                    result = self.hook("PreToolUse", host, cwd=repo, tool_name=tool, tool_input=data)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                for event_name in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
                    result = self.hook(event_name, host, cwd=repo)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertFalse((repo / ".speclock").exists())

    def test_malformed_json_is_explicit_nonzero(self):
        for payload in ("not json", "[]", "null"):
            result = self.hook("PreToolUse", raw=payload)
            self.assertEqual(result.returncode, 2)
            self.assertIn("ENGINE_GATE_ERROR", result.stderr)

    def test_invalid_pretool_input_fails_closed(self):
        result = self.hook("PreToolUse", tool_name="Write", tool_input=["invalid"])
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_stop_reports_task_missing_not_legacy_deliver(self):
        for host in ("claude", "codex"):
            result = self.hook("Stop", host)
            self.assertIn("ENGINE_TASK_UNBOUND", result.stdout)
            self.assertNotIn("workflow-core:deliver", result.stdout)

    def test_confirmation_callback_does_not_auto_approve(self):
        for tool in ("AskUserQuestion", "ExitPlanMode"):
            result = self.hook("PostToolUse", tool_name=tool, tool_input={}, tool_response={"answer": "approved"})
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")

    def test_native_tier_selection_is_bound_to_the_question_and_call(self):
        from workflow_engine.engine import Engine
        from workflow_engine_cli import default_db
        from unittest.mock import patch

        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        with patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": self.tmp.name}):
            engine = Engine(self.project, default_db(self.project))
        for host, tool in (("codex", "request_user_input"), ("claude", "AskUserQuestion")):
            with self.subTest(host=host):
                plan = {"version": 1, "checks": [{"id": "check", "argv": ["true"], "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"], "acceptance": ["A"]}]}
                task = engine.create(host, "light", ["A"], plan, host + "-create", details={"goal": "目标", "scope": ["src"], "source": "用户", "steps": [{"id": "s1", "title": "修改"}]})
                session = "session-" + host
                task = engine.bind_executor(host, task["version"], host + "-bind", "agent", session)
                marker = f"workflow-confirm:{host}:{task['current_round']}:{task['control_digest']}:tier_confirmation"
                question = {"question": "选择档位 " + marker, "header": "工作档位", "options": [{"label": label, "description": label} for label in ("轻量档", "标准档", "完整档")]}
                if host == "codex":
                    question["id"] = "workflow_tier"
                    answer = json.dumps({"answers": {"workflow_tier": {"answers": ["完整档"]}}}, ensure_ascii=False)
                else:
                    question["multiSelect"] = False
                    answer = {"answers": {question["question"]: "完整档"}}
                event = dict(session_id=session, tool_name=tool, tool_input={"questions": [question]}, tool_use_id="call")
                self.assertEqual(self.hook("PreToolUse", host, **event).stdout, "")
                wrong = dict(event, tool_use_id="other")
                self.assertIn("UNSUPPORTED", self.hook("PostToolUse", host, **wrong, tool_response=answer).stdout)
                self.assertEqual(engine.status(host)["version"], task["version"])
                self.assertIn("RECORDED", self.hook("PostToolUse", host, **event, tool_response=answer).stdout)
                selected = engine.status(host)
                self.assertEqual(selected["tier"], "full")
                self.assertEqual(selected["version"], task["version"] + 1)
                self.assertNotIn("tier_confirmation", selected["missing"])
                self.assertIn("approval", selected["missing"])
                self.assertIn("REJECTED", self.hook("PostToolUse", host, **event, tool_response=answer).stdout)
                self.assertEqual(engine.status(host)["version"], selected["version"])

    def test_native_single_choice_approval_works_for_codex_and_claude(self):
        from workflow_engine.engine import Engine
        from workflow_engine_cli import default_db
        from unittest.mock import patch

        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        with patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": self.tmp.name}):
            engine = Engine(self.project, default_db(self.project))
        for host, tool in (("codex", "request_user_input"), ("claude", "AskUserQuestion")):
            with self.subTest(host=host):
                task_id = host + "-approve"
                plan = {"version": 1, "checks": [{"id": "check", "argv": ["true"], "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"], "acceptance": ["A"]}]}
                proposal = {"goal": "目标", "scope": "仅改 src", "impact": "无", "risk": "低", "rollback": "回退提交", "acceptance": ["A"]}
                details = {"goal": "目标", "scope": ["src"], "source": "用户", "dependencies": [], "baseline": [], "steps": [{"id": "s1", "title": "步骤一"}, {"id": "s2", "title": "步骤二"}, {"id": "s3", "title": "步骤三"}], "proposal": proposal}
                task = engine.create(task_id, "full", ["A"], plan, task_id + "-create", details=details)
                session = "session-approve-" + host
                task = engine.bind_executor(task_id, task["version"], task_id + "-bind", "agent", session)
                task = engine.confirm_tier(task_id, task["version"], task_id + "-tier", "用户", "full")
                self.assertIn("approval", task["missing"])

                marker = f"workflow-confirm:{task_id}:{task['current_round']}:{task['control_digest']}:approval"
                question = {
                    "question": "请确认是否批准完整档实施方案 " + marker,
                    "header": "方案批准",
                    "options": [
                        {"label": "批准方案", "description": "批准后进入实施"},
                        {"label": "需要修改", "description": "退回调整方案"},
                    ],
                }
                if host == "codex":
                    question["id"] = "workflow_approval"
                    reject_answer = json.dumps({"answers": {"workflow_approval": {"answers": ["需要修改"]}}}, ensure_ascii=False)
                    accept_answer = json.dumps({"answers": {"workflow_approval": {"answers": ["批准方案"]}}}, ensure_ascii=False)
                else:
                    question["multiSelect"] = False
                    reject_answer = {"answers": {question["question"]: "需要修改"}}
                    accept_answer = {"answers": {question["question"]: "批准方案"}}

                # 单选项（无不批准选项）必须被拒绝。
                only_approve = dict(question, options=[{"label": "批准方案", "description": "唯一项"}])
                bad_pre = self.hook("PreToolUse", host, session_id=session, tool_name=tool, tool_input={"questions": [only_approve]}, tool_use_id="call-bad")
                self.assertEqual(json.loads(bad_pre.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

                event = dict(session_id=session, tool_name=tool, tool_input={"questions": [question]}, tool_use_id="call-approve")
                self.assertEqual(self.hook("PreToolUse", host, **event).stdout, "")
                self.assertIn("REJECTED", self.hook("PostToolUse", host, **event, tool_response=reject_answer).stdout)
                self.assertIn("approval", engine.status(task_id)["missing"])

                self.assertIn("RECORDED", self.hook("PostToolUse", host, **event, tool_response=accept_answer).stdout)
                approved = engine.status(task_id)
                self.assertEqual(approved["version"], task["version"] + 1)
                self.assertNotIn("approval", approved["missing"])

                # 同一回执重放必须被拒绝。
                self.assertIn("REJECTED", self.hook("PostToolUse", host, **event, tool_response=accept_answer).stdout)
                self.assertEqual(engine.status(task_id)["version"], approved["version"])

    def test_codex_request_user_input_async_tier_and_approval(self):
        from workflow_engine.engine import Engine
        from workflow_engine_cli import default_db
        from unittest.mock import patch

        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        with patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": self.tmp.name}):
            engine = Engine(self.project, default_db(self.project))
        plan = {"version": 1, "checks": [{"id": "check", "argv": ["true"], "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"], "acceptance": ["A"]}]}
        proposal = {"goal": "目标", "scope": "仅改 src", "impact": "无", "risk": "低", "rollback": "回退提交", "acceptance": ["A"]}
        details = {"goal": "目标", "scope": ["src"], "source": "用户", "dependencies": [], "baseline": [], "steps": [{"id": "s1", "title": "步骤一"}, {"id": "s2", "title": "步骤二"}, {"id": "s3", "title": "步骤三"}], "proposal": proposal}
        task = engine.create("T-ASYNC", "light", ["A"], plan, "async-create", details=details)
        session = "session-async-codex"
        task = engine.bind_executor("T-ASYNC", task["version"], "async-bind", "agent", session)

        # 1. 定档：Codex request_user_input_async 使用 title + 字符串 options，PostToolUse 返回异步确认，UserPromptSubmit 收到点选结果。
        tier_marker = f"workflow-confirm:T-ASYNC:{task['current_round']}:{task['control_digest']}:tier_confirmation"
        tier_input = {"questions": [{"title": f"请选择档位。 {tier_marker} ", "options": ["选完整档", "选标准档", "选轻量档"]}]}
        tier_event = dict(session_id=session, tool_name="request_user_input_async", tool_input=tier_input, tool_use_id="call-async-tier")
        self.assertEqual(self.hook("PreToolUse", "codex", **tier_event).stdout, "")
        self.assertIn("ENGINE_CONFIRMATION_PENDING", self.hook("PostToolUse", "codex", **tier_event, tool_response={"status": "pending"}).stdout)
        self.assertIn("ENGINE_CONFIRMATION_RECORDED", self.hook("UserPromptSubmit", "codex", session_id=session, prompt="选完整档").stdout)
        selected = engine.status("T-ASYNC")
        self.assertEqual(selected["tier"], "full")
        self.assertNotIn("tier_confirmation", selected["missing"])
        self.assertIn("approval", selected["missing"])

        # 2. 方案批准：同时验证 PostToolUse 直接返回字符串数组答案的同步路径。
        app_marker = f"workflow-confirm:T-ASYNC:{selected['current_round']}:{selected['control_digest']}:approval"
        app_input = {"questions": [{"title": f"请审批方案 {app_marker}", "options": ["批准方案", "需要修改"]}]}
        app_event = dict(session_id=session, tool_name="request_user_input_async", tool_input=app_input, tool_use_id="call-async-app")
        self.assertEqual(self.hook("PreToolUse", "codex", **app_event).stdout, "")
        self.assertIn("ENGINE_CONFIRMATION_RECORDED", self.hook("PostToolUse", "codex", **app_event, tool_response=json.dumps({"answers": ["批准方案"]}, ensure_ascii=False)).stdout)
        approved = engine.status("T-ASYNC")
        self.assertNotIn("approval", approved["missing"])

    def test_manifests_install_synchronous_wildcard_gate(self):
        for filename in ("hooks.json", "codex.json"):
            manifest = json.loads((HERE.parent / "hooks" / filename).read_text(encoding="utf-8"))
            for name in ("PreToolUse", "PostToolUse", "UserPromptSubmit"):
                groups = [g for g in manifest["hooks"][name] if any("workflow_gate.py" in str(h) for h in g["hooks"])]
                self.assertTrue(groups)
                self.assertNotIn("matcher", groups[0])
                self.assertTrue(all(not h.get("async") for g in groups for h in g["hooks"]))

    def test_prepare_request_tier_diagnostics_and_markdown_codex_chat_reply(self):
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        (self.project / "rules.md").write_text("规范全文", encoding="utf-8")
        (self.project / "ai-workflow.yaml").write_text(
            "version: 1\n"
            "baseline:\n"
            "  required:\n"
            "    - rules.md\n"
            "verify:\n"
            f"  light: {sys.executable} -c pass\n"
            f"  standard: {sys.executable} -c pass\n",
            encoding="utf-8",
        )
        cli = str(HERE / "workflow_engine_cli.py")
        cli_env = {k: v for k, v in os.environ.items() if not k.startswith("WORKFLOW_") and k not in {"CODEX_THREAD_ID", "CURSOR_PROJECT_DIR", "CURSOR_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "CLAUDECODE"}}
        cli_env["WORKFLOW_ENGINE_HOME"] = self.tmp.name

        details = {"goal": "测试定档", "scope": ["src"], "source": "需求", "dependencies": [], "steps": [{"id": "s1", "title": "步骤一"}, {"id": "s2", "title": "步骤二"}, {"id": "s3", "title": "步骤三"}]}
        prep_proc = subprocess.run(
            [sys.executable, cli, "--root", str(self.project), "prepare", "--task", "T-CHAT", "--tier", "轻量", "--acceptance", "A1", "--details-json", json.dumps(details, ensure_ascii=False), "--executor", "codex", "--session", "s-codex", "--request-tier"],
            text=True, capture_output=True, env=cli_env,
        )
        self.assertEqual(prep_proc.returncode, 0, prep_proc.stdout + prep_proc.stderr)
        prep = json.loads(prep_proc.stdout)
        self.assertFalse(prep["confirmation"]["hook_active"])
        self.assertIn("ENGINE_HOOK_INACTIVE", prep["confirmation"]["hook_warning"])

        self.assertEqual(self.hook("SessionStart", "codex", session_id="s-codex").returncode, 0)
        prompt_init = self.hook("UserPromptSubmit", "codex", session_id="s-codex", prompt="开始执行 T-CHAT")
        self.assertEqual(prompt_init.returncode, 0)
        self.assertEqual(prompt_init.stdout, "")

        req_proc = subprocess.run(
            [sys.executable, cli, "--root", str(self.project), "request-confirmation", "--task", "T-CHAT", "--version", str(prep["task"]["version"]), "--session", "s-codex", "--kind", "tier_confirmation"],
            text=True, capture_output=True, env=cli_env,
        )
        self.assertEqual(req_proc.returncode, 0, req_proc.stdout + req_proc.stderr)
        req = json.loads(req_proc.stdout)
        self.assertTrue(req["confirmation"]["hook_active"])
        self.assertEqual(req["confirmation"]["hook_host"], "codex")
        self.assertNotIn("hook_warning", req["confirmation"])

        reply = self.hook("UserPromptSubmit", "codex", session_id="s-codex", prompt="**`选标准档`**\n")
        self.assertEqual(reply.returncode, 0, reply.stderr)
        payload = json.loads(reply.stdout)["hookSpecificOutput"]
        self.assertEqual(payload["hookEventName"], "UserPromptSubmit")
        self.assertIn("ENGINE_CONFIRMATION_RECORDED", payload["additionalContext"])

        status_proc = subprocess.run([sys.executable, cli, "--root", str(self.project), "status", "--task", "T-CHAT"], text=True, capture_output=True, env=cli_env)
        self.assertEqual(status_proc.returncode, 0, status_proc.stderr)
        task = json.loads(status_proc.stdout)["task"]
        self.assertEqual(task["tier"], "standard")
        self.assertNotIn("tier_confirmation", task["missing"])

    def test_cli_hook_precheck_on_check_hooks_and_entry_commands(self):
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        (self.project / "rules.md").write_text("规范全文", encoding="utf-8")
        (self.project / "ai-workflow.yaml").write_text(
            "version: 1\n"
            "baseline:\n"
            "  required:\n"
            "    - rules.md\n"
            "verify:\n"
            f"  light: {sys.executable} -c pass\n"
            f"  standard: {sys.executable} -c pass\n",
            encoding="utf-8",
        )
        cli = str(HERE / "workflow_engine_cli.py")
        base_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("WORKFLOW_") and k not in {"CODEX_THREAD_ID", "CLAUDE_SESSION_ID", "CURSOR_PROJECT_DIR", "CURSOR_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "CLAUDECODE"}
        }

        clean_check = subprocess.run(
            [sys.executable, cli, "--root", str(self.project), "check-hooks", "--session", "s-pre"],
            text=True, capture_output=True, env=base_env,
        )
        self.assertEqual(clean_check.returncode, 0, clean_check.stdout + clean_check.stderr)
        clean_payload = json.loads(clean_check.stdout)
        self.assertTrue(clean_payload["ok"])
        self.assertFalse(clean_payload["hooks"]["hook_active"])
        self.assertFalse((self.project / ".speclock").exists())

        cli_env = {**base_env, "WORKFLOW_ENGINE_HOME": self.tmp.name}

        def run_cli(*args, extra_env=None):
            env = {**cli_env, **(extra_env or {})}
            proc = subprocess.run([sys.executable, cli, "--root", str(self.project), *args], text=True, capture_output=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            return json.loads(proc.stdout)

        self.assertFalse(run_cli("check-hooks", "--session", "s-pre")["hooks"]["hook_active"])
        listed = run_cli("list", "--session", "s-pre")
        self.assertEqual(listed["tasks"], [])
        self.assertFalse(listed["hooks"]["hook_active"])

        details = {"goal": "测试前置检查", "scope": ["src"], "source": "需求", "dependencies": [], "steps": [{"id": "s1", "title": "步骤一"}]}
        prep = run_cli(
            "prepare", "--task", "T-PRE", "--tier", "轻量", "--acceptance", "A1",
            "--details-json", json.dumps(details, ensure_ascii=False),
            "--executor", "codex", "--session", "s-pre",
        )
        self.assertFalse(prep["hooks"]["hook_active"])
        self.assertIn("ENGINE_HOOK_INACTIVE", prep["hooks"]["hook_warning"])
        self.assertFalse(run_cli("status", "--task", "T-PRE", "--session", "s-pre")["hooks"]["hook_active"])
        bound = run_cli(
            "bind-executor", "--task", "T-PRE", "--version", str(prep["task"]["version"]),
            "--executor", "codex", "--session", "s-pre",
        )
        self.assertFalse(bound["hooks"]["hook_active"])
        resumed = run_cli("resume", "--task", "T-PRE", "--version", str(bound["task"]["version"]), "--session", "s-pre")
        self.assertFalse(resumed["hooks"]["hook_active"])

        self.assertEqual(self.hook("SessionStart", "codex", session_id="s-pre").returncode, 0)
        self.assertEqual(self.hook("UserPromptSubmit", "codex", session_id="s-pre", prompt="执行 T-PRE").returncode, 0)

        for payload in (
            run_cli("check-hooks", "--session", "s-pre"),
            run_cli("list", "--session", "s-pre"),
            run_cli("status", "--task", "T-PRE", "--session", "s-pre"),
            run_cli("bind-executor", "--task", "T-PRE", "--version", str(resumed["task"]["version"]), "--executor", "codex", "--session", "s-pre"),
        ):
            self.assertTrue(payload["hooks"]["hook_active"])
            self.assertEqual(payload["hooks"]["hook_host"], "codex")
            self.assertNotIn("hook_warning", payload["hooks"])

        latest = run_cli("status", "--task", "T-PRE")
        self.assertTrue(latest["hooks"]["hook_active"])
        mismatch = run_cli("status", "--task", "T-PRE", extra_env={"CODEX_THREAD_ID": "s-other"})
        self.assertFalse(mismatch["hooks"]["hook_active"])
        self.assertEqual(mismatch["hooks"]["session_id"], "s-other")
        self.assertTrue(mismatch["hooks"]["other_active_sessions"])

        resumed_ok = run_cli("resume", "--task", "T-PRE", "--version", str(latest["task"]["version"]), "--session", "s-pre")
        self.assertTrue(resumed_ok["hooks"]["hook_active"])
        self.assertEqual(resumed_ok["hooks"]["hook_host"], "codex")
        self.assertNotIn("hook_warning", resumed_ok["hooks"])

        skills_dir = HERE.parent / "skills"
        for skill_name in ("workflow", "kickoff"):
            skill_text = (skills_dir / skill_name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("check-hooks", skill_text)
            self.assertIn("hooks.hook_active", skill_text)


if __name__ == "__main__":
    unittest.main()
