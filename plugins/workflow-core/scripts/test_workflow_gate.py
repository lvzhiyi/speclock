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
                               ("mcp__filesystem__write_file", {"path": "x.py"})):
                with self.subTest(host=host, tool=tool):
                    result = self.hook("PreToolUse", host, tool_name=tool, tool_input=data)
                    self.assertEqual(result.returncode, 0)
                    value = json.loads(result.stdout)["hookSpecificOutput"]
                    self.assertEqual(value["permissionDecision"], "deny")
                    self.assertIn("ENGINE_TASK_UNBOUND", value["permissionDecisionReason"])
                    self.assertNotIn('"ask"', result.stdout)

    def test_readonly_and_unconfigured_project_are_allowed(self):
        for host in ("claude", "codex"):
            for tool, data in (
                ("Read", {"file_path": "rules.md"}),
                ("Bash", {"command": "git status --short"}),
                ("Bash", {"command": "apifox --help"}),
                ("Bash", {"command": "apifox api list --help"}),
                ("mcp__apifox__get_api", {"path": "/api/v1/courses"}),
                ("mcp__pixso__get_node_dsl", {}),
                ("browser_navigate", {"url": "https://apifox.com"}),
            ):
                with self.subTest(host=host, tool=tool, data=data):
                    self.assertEqual(self.hook("PreToolUse", host, tool_name=tool, tool_input=data).stdout, "")
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

                # 未导出当前版本审阅稿前，发起原生审批卡片必须被拒绝。
                event = dict(session_id=session, tool_name=tool, tool_input={"questions": [question]}, tool_use_id="call-approve")
                no_review_pre = self.hook("PreToolUse", host, **event)
                no_review_reason = json.loads(no_review_pre.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("ENGINE_APPROVAL_REVIEW_REQUIRED", no_review_reason)

                cli_env = {k: v for k, v in os.environ.items() if not k.startswith("WORKFLOW_")}
                cli_env["WORKFLOW_ENGINE_HOME"] = self.tmp.name
                cli = str(HERE / "workflow_engine_cli.py")
                before_git = subprocess.run(["git", "status", "--short"], cwd=self.project, text=True, capture_output=True, check=True).stdout
                render_res = subprocess.run(
                    [sys.executable, cli, "--root", str(self.project), "render-md", "--task", task_id, "--save", "--json"],
                    text=True, capture_output=True, env=cli_env,
                )
                self.assertEqual(render_res.returncode, 0, render_res.stdout + render_res.stderr)
                render_payload = json.loads(render_res.stdout)
                self.assertTrue(Path(render_payload["path"]).is_file())
                self.assertEqual(
                    subprocess.run(["git", "status", "--short"], cwd=self.project, text=True, capture_output=True, check=True).stdout,
                    before_git,
                )

                self.assertEqual(self.hook("PreToolUse", host, **event).stdout, "")
                self.assertIn("REJECTED", self.hook("PostToolUse", host, **event, tool_response=reject_answer).stdout)
                self.assertIn("approval", engine.status(task_id)["missing"])

                # 修改方案后控制摘要与版本变更，重新定档后旧审阅稿仍必须失效直到重新 render-md --save。
                updated = engine.update_task(
                    task_id,
                    task["version"],
                    task_id + "-update",
                    {"proposal": dict(proposal, design="补充技术设计细节")},
                )
                updated = engine.confirm_tier(task_id, updated["version"], task_id + "-tier-v2", "用户", "full")
                new_marker = f"workflow-confirm:{task_id}:{updated['current_round']}:{updated['control_digest']}:approval"
                new_question = dict(question, question="请确认是否批准完整档实施方案 " + new_marker)
                if host == "claude":
                    accept_answer = {"answers": {new_question["question"]: "批准方案"}}
                new_event = dict(session_id=session, tool_name=tool, tool_input={"questions": [new_question]}, tool_use_id="call-approve-v2")
                stale_pre = self.hook("PreToolUse", host, **new_event)
                self.assertIn("ENGINE_APPROVAL_REVIEW_REQUIRED", json.loads(stale_pre.stdout)["hookSpecificOutput"]["permissionDecisionReason"])

                render_v2 = subprocess.run(
                    [sys.executable, cli, "--root", str(self.project), "render-md", "--task", task_id, "--save"],
                    text=True, capture_output=True, env=cli_env,
                )
                self.assertEqual(render_v2.returncode, 0, render_v2.stdout + render_v2.stderr)
                self.assertIn("补充技术设计细节", render_v2.stdout)

                self.assertEqual(self.hook("PreToolUse", host, **new_event).stdout, "")
                self.assertIn("RECORDED", self.hook("PostToolUse", host, **new_event, tool_response=accept_answer).stdout)
                approved = engine.status(task_id)
                self.assertEqual(approved["version"], updated["version"] + 1)
                self.assertNotIn("approval", approved["missing"])

                # 同一回执重放必须被拒绝。
                self.assertIn("REJECTED", self.hook("PostToolUse", host, **new_event, tool_response=accept_answer).stdout)
                self.assertEqual(engine.status(task_id)["version"], approved["version"])

    def test_codex_async_question_reply_and_sync_recommended_suffix(self):
        from workflow_engine.engine import Engine
        from workflow_engine_cli import default_db
        from unittest.mock import patch

        def wrap_reply(call_id, question, answer):
            payload = [{"questionItemId": json.dumps(["request_user_input_async", call_id, 0]), "question": question, "answer": answer}]
            return "<send_user_message_question_reply>\n" + json.dumps(payload, ensure_ascii=False) + "\n</send_user_message_question_reply>\n"

        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        with patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": self.tmp.name}):
            engine = Engine(self.project, default_db(self.project))
        plan = {"version": 1, "checks": [{"id": "check", "argv": ["true"], "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"], "acceptance": ["A"]}]}
        proposal = {"goal": "目标", "scope": "仅改 src", "impact": "无", "risk": "低", "rollback": "回退提交", "acceptance": ["A"]}
        details = {"goal": "目标", "scope": ["src"], "source": "用户", "dependencies": [], "baseline": [], "steps": [{"id": "s1", "title": "步骤一"}, {"id": "s2", "title": "步骤二"}, {"id": "s3", "title": "步骤三"}], "proposal": proposal}
        task = engine.create("T-ASYNC", "light", ["A"], plan, "async-create", details=details)
        session = "session-async-codex"
        task = engine.bind_executor("T-ASYNC", task["version"], "async-bind", "agent", session)

        # 0. 无 workflow-confirm 标记的普通异步提问与回执必须放行/忽略。
        plain_event = dict(session_id=session, tool_name="request_user_input_async", tool_input={"questions": [{"title": "补充背景？", "options": ["是", "否"]}]}, tool_use_id="call-plain-async")
        self.assertEqual(self.hook("PreToolUse", "codex", **plain_event).stdout, "")
        self.assertEqual(self.hook("UserPromptSubmit", "codex", session_id=session, prompt=wrap_reply("call-plain-async", "补充背景？", "是")).stdout, "")
        self.assertEqual(engine.status("T-ASYNC")["version"], task["version"])

        # 1. request_user_input_async 定档：PostToolUse 返回等待与 clock.sleep 指引，UserPromptSubmit 消费 <send_user_message_question_reply>。
        tier_marker = f"workflow-confirm:T-ASYNC:{task['current_round']}:{task['control_digest']}:tier_confirmation"
        tier_title = f"请选择档位。 {tier_marker} "
        async_tier_input = {"questions": [{"title": tier_title, "options": ["完整档 (Recommended)", "标准档", "轻量档"]}]}
        async_tier_event = dict(session_id=session, tool_name="request_user_input_async", tool_input=async_tier_input, tool_use_id="call-async-tier")
        self.assertEqual(self.hook("PreToolUse", "codex", **async_tier_event).stdout, "")
        pending_out = self.hook("PostToolUse", "codex", **async_tier_event, tool_response={"accepted": True}).stdout
        self.assertIn("ENGINE_CONFIRMATION_PENDING", pending_out)
        self.assertIn("clock.sleep", pending_out)
        for wait_tool in ("clocksleep", "clock.sleep", "sleep", "wait"):
            self.assertEqual(self.hook("PreToolUse", "codex", session_id=session, tool_name=wait_tool, tool_input={"duration_ms": 30000}, tool_use_id=f"call-{wait_tool}").stdout, "")

        # 错误 call_id 的回执必须被拒绝且不入库。
        bad_call_res = self.hook("UserPromptSubmit", "codex", session_id=session, prompt=wrap_reply("call-wrong", tier_title, "完整档 (Recommended)")).stdout
        self.assertIn("ENGINE_CONFIRMATION_REJECTED", bad_call_res)
        self.assertEqual(engine.status("T-ASYNC")["version"], task["version"])

        # 合法 call_id + 含标记 question + 推荐后缀选项成功登记。
        good_tier_res = self.hook("UserPromptSubmit", "codex", session_id=session, prompt=wrap_reply("call-async-tier", tier_title.strip(), "完整档 (Recommended)")).stdout
        self.assertIn("ENGINE_CONFIRMATION_RECORDED", good_tier_res)
        selected = engine.status("T-ASYNC")
        self.assertEqual(selected["tier"], "full")
        self.assertNotIn("tier_confirmation", selected["missing"])
        self.assertIn("approval", selected["missing"])

        # 重放同一 call_id 回执必须被拒绝。
        self.assertIn("ENGINE_CONFIRMATION_REJECTED", self.hook("UserPromptSubmit", "codex", session_id=session, prompt=wrap_reply("call-async-tier", tier_title.strip(), "完整档 (Recommended)")).stdout)

        # 2. request_user_input_async 方案批准：未导出审阅稿前被拒，导出后选不批准项被拒，选「批准方案（推荐）」入库。
        cli_env = {k: v for k, v in os.environ.items() if not k.startswith("WORKFLOW_")}
        cli_env["WORKFLOW_ENGINE_HOME"] = self.tmp.name
        cli = str(HERE / "workflow_engine_cli.py")
        app_marker = f"workflow-confirm:T-ASYNC:{selected['current_round']}:{selected['control_digest']}:approval"
        app_title = f"请审批方案 {app_marker}"
        async_app_input = {"questions": [{"title": app_title, "options": ["批准方案（推荐）", "需要修改"]}]}
        async_app_event = dict(session_id=session, tool_name="request_user_input_async", tool_input=async_app_input, tool_use_id="call-async-app")
        self.assertIn("ENGINE_APPROVAL_REVIEW_REQUIRED", self.hook("PreToolUse", "codex", **async_app_event).stdout)
        self.assertEqual(subprocess.run([sys.executable, cli, "--root", str(self.project), "render-md", "--task", "T-ASYNC", "--save"], text=True, capture_output=True, env=cli_env).returncode, 0)
        self.assertEqual(self.hook("PreToolUse", "codex", **async_app_event).stdout, "")
        app_pending_out = self.hook("PostToolUse", "codex", **async_app_event, tool_response={"accepted": True}).stdout
        self.assertIn("ENGINE_CONFIRMATION_PENDING", app_pending_out)
        self.assertIn("clock.sleep", app_pending_out)

        self.assertIn("ENGINE_CONFIRMATION_REJECTED", self.hook("UserPromptSubmit", "codex", session_id=session, prompt=wrap_reply("call-async-app", app_title, "需要修改")).stdout)
        self.assertIn("approval", engine.status("T-ASYNC")["missing"])
        self.assertIn("ENGINE_CONFIRMATION_RECORDED", self.hook("UserPromptSubmit", "codex", session_id=session, prompt=wrap_reply("call-async-app", app_title, "批准方案（推荐）")).stdout)
        self.assertNotIn("approval", engine.status("T-ASYNC")["missing"])

        # 3. 同步阻塞的 request_user_input 同样兼容 (Recommended) / （推荐） 后缀。
        sync_session = "session-sync-codex"
        sync_task = engine.create("T-SYNC", "light", ["A"], plan, "sync-create", details=details)
        sync_task = engine.bind_executor("T-SYNC", sync_task["version"], "sync-bind", "agent", sync_session)
        sync_tier_marker = f"workflow-confirm:T-SYNC:{sync_task['current_round']}:{sync_task['control_digest']}:tier_confirmation"
        sync_tier_input = {
            "questions": [{
                "id": "tier",
                "header": "档位",
                "question": f"请选择档位。 {sync_tier_marker} ",
                "options": [
                    {"label": "完整档 (Recommended)", "description": "全量方案与审批"},
                    {"label": "标准档", "description": "短计划"},
                    {"label": "轻量档", "description": "最小改动"},
                ],
            }]
        }
        tier_event = dict(session_id=sync_session, tool_name="request_user_input", tool_input=sync_tier_input, tool_use_id="call-sync-tier")
        self.assertEqual(self.hook("PreToolUse", "codex", **tier_event).stdout, "")
        self.assertIn("ENGINE_CONFIRMATION_RECORDED", self.hook("PostToolUse", "codex", **tier_event, tool_response={"answers": {"tier": {"answers": ["完整档 (Recommended)"]}}}).stdout)
        sync_selected = engine.status("T-SYNC")
        self.assertEqual(sync_selected["tier"], "full")

        sync_app_marker = f"workflow-confirm:T-SYNC:{sync_selected['current_round']}:{sync_selected['control_digest']}:approval"
        sync_app_input = {
            "questions": [{
                "id": "approval",
                "header": "审批",
                "question": f"请审批方案 {sync_app_marker}",
                "options": [
                    {"label": "批准方案（推荐）", "description": "按方案实施"},
                    {"label": "需要修改", "description": "退回调整"},
                ],
            }]
        }
        app_event = dict(session_id=sync_session, tool_name="request_user_input", tool_input=sync_app_input, tool_use_id="call-sync-app")
        self.assertEqual(subprocess.run([sys.executable, cli, "--root", str(self.project), "render-md", "--task", "T-SYNC", "--save"], text=True, capture_output=True, env=cli_env).returncode, 0)
        self.assertEqual(self.hook("PreToolUse", "codex", **app_event).stdout, "")
        self.assertIn("ENGINE_CONFIRMATION_RECORDED", self.hook("PostToolUse", "codex", **app_event, tool_response=json.dumps({"answers": {"approval": {"answers": ["批准方案（推荐）"]}}}, ensure_ascii=False)).stdout)
        self.assertNotIn("approval", engine.status("T-SYNC")["missing"])

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
        workflow_skill = (skills_dir / "workflow" / "SKILL.md").read_text(encoding="utf-8")
        tiering_skill = (skills_dir / "tiering" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("render-md", workflow_skill)
        self.assertIn("ENGINE_APPROVAL_REVIEW_REQUIRED", workflow_skill)
        self.assertIn("render-md", tiering_skill)

    def test_claude_session_start_persists_env_and_english_end_to_end(self):
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        (self.project / "rules.md").write_text("Standards body", encoding="utf-8")
        (self.project / "ai-workflow.yaml").write_text(
            "version: 1\n"
            "baseline:\n"
            "  required:\n"
            "    - rules.md\n"
            "verify:\n"
            f"  light: {sys.executable} -c pass\n"
            "  full: git status --short\n",
            encoding="utf-8",
        )
        unconfigured = Path(self.tmp.name) / "unconfigured_repo"
        unconfigured.mkdir()
        env_file = Path(self.tmp.name) / "claude.env"
        env_file.write_text("", encoding="utf-8")

        base_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("WORKFLOW_") and k not in {"CODEX_THREAD_ID", "CLAUDE_SESSION_ID", "CURSOR_PROJECT_DIR", "CURSOR_PLUGIN_ROOT", "CURSOR_CONVERSATION_ID", "CURSOR_AGENT", "CURSOR_TRACE_ID", "CLAUDE_PLUGIN_ROOT", "CLAUDECODE"}
        }
        claude_env = {**base_env, "WORKFLOW_ENGINE_HOME": self.tmp.name, "CLAUDE_ENV_FILE": str(env_file)}

        # 未接入项目 SessionStart 仍静默放行且不创建 .speclock/，但会写入 CLAUDE_ENV_FILE 供 /init 使用。
        unconf_proc = subprocess.run(
            [sys.executable, str(HERE / "workflow_gate.py")],
            input=json.dumps({"session_id": "cc-unconf", "cwd": str(unconfigured), "hook_event_name": "SessionStart"}),
            text=True, capture_output=True, env=claude_env,
        )
        self.assertEqual(unconf_proc.returncode, 0, unconf_proc.stderr)
        self.assertEqual(unconf_proc.stdout, "")
        self.assertFalse((unconfigured / ".speclock").exists())
        env_text = env_file.read_text(encoding="utf-8")
        self.assertIn("export WORKFLOW_HOST=claude", env_text)
        self.assertIn("export CLAUDE_SESSION_ID=cc-unconf", env_text)

        # 已接入项目 SessionStart 注入 Claude session_id 并写入最新会话到 CLAUDE_ENV_FILE。
        env_file.write_text("", encoding="utf-8")
        session = "cc-sess-e2e"
        start_proc = subprocess.run(
            [sys.executable, str(HERE / "workflow_gate.py")],
            input=json.dumps({"session_id": session, "cwd": str(self.project), "hook_event_name": "SessionStart"}),
            text=True, capture_output=True, env=claude_env,
        )
        self.assertEqual(start_proc.returncode, 0, start_proc.stderr)
        start_ctx = json.loads(start_proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"Claude session_id: {session}", start_ctx)
        self.assertIn("export CLAUDE_SESSION_ID=cc-sess-e2e", env_file.read_text(encoding="utf-8"))

        self.assertEqual(self.hook("UserPromptSubmit", "claude", session_id=session, prompt="Run T-CC").returncode, 0)
        cli = str(HERE / "workflow_engine_cli.py")
        cli_env = {**base_env, "WORKFLOW_HOST": "claude", "CLAUDE_SESSION_ID": session, "WORKFLOW_ENGINE_HOME": self.tmp.name}

        def run_cli(*args):
            proc = subprocess.run([sys.executable, cli, "--root", str(self.project), *args], text=True, capture_output=True, env=cli_env)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            return json.loads(proc.stdout)

        checked = run_cli("check-hooks")
        self.assertTrue(checked["hooks"]["hook_active"])
        self.assertEqual(checked["hooks"]["hook_host"], "claude")
        self.assertEqual(checked["hooks"]["session_id"], session)

        details = {"goal": "Implement auth", "scope": ["src"], "source": "PRD", "dependencies": [], "steps": [{"id": "s1", "title": "Step 1"}]}
        prep = run_cli("prepare", "--task", "T-CC", "--tier", "light", "--acceptance", "A1", "--details-json", json.dumps(details), "--executor", "claude", "--session", session)
        task = prep["task"]
        self.assertTrue(prep["hooks"]["hook_active"])

        tier_marker = f"workflow-confirm:T-CC:{task['current_round']}:{task['control_digest']}:tier_confirmation"
        tier_q = {
            "question": f"Choose tier {tier_marker}",
            "header": "Tier",
            "multiSelect": False,
            "options": [{"label": "Light Tier"}, {"label": "Standard Tier"}, {"label": "Full Tier (Recommended)"}],
        }
        tier_ev = dict(session_id=session, tool_name="AskUserQuestion", tool_input={"questions": [tier_q]}, tool_use_id="cc-tier-1")
        self.assertEqual(self.hook("PreToolUse", "claude", **tier_ev).stdout, "")
        self.assertIn("ENGINE_CONFIRMATION_RECORDED", self.hook("PostToolUse", "claude", **tier_ev, tool_response={"answers": {"Tier": "Full Tier (Recommended)"}}).stdout)

        selected = run_cli("status", "--task", "T-CC")["task"]
        self.assertEqual(selected["tier"], "full")

        proposal = {k: "Detail" for k in ("goal", "design", "scope", "impact", "risk", "rollback", "acceptance")}
        full_plan = {"version": 1, "checks": [{"id": "check-1", "argv": ["git", "status", "--short"], "cwd": ".", "timeout": 10, "covers": ["format", "analyze", "test"], "acceptance": ["A1"]}]}
        updated = run_cli("update-task", "--task", "T-CC", "--version", str(selected["version"]), "--file-json", json.dumps({"proposal": proposal, "plan": full_plan}))["task"]
        self.assertEqual(run_cli("render-md", "--task", "T-CC", "--save", "--json")["task_id"], "T-CC")

        app_marker = f"workflow-confirm:T-CC:{updated['current_round']}:{updated['control_digest']}:approval"
        app_q = {
            "question": f"Approve proposal {app_marker}",
            "header": "Approval",
            "multiSelect": False,
            "options": [{"label": "Approve Proposal (Recommended)"}, {"label": "Request Changes"}],
        }
        app_ev = dict(session_id=session, tool_name="AskUserQuestion", tool_input={"questions": [app_q]}, tool_use_id="cc-app-1")
        self.assertEqual(self.hook("PreToolUse", "claude", **app_ev).stdout, "")
        self.assertIn("ENGINE_CONFIRMATION_RECORDED", self.hook("PostToolUse", "claude", **app_ev, tool_response=json.dumps({"answers": {"Approval": "Approve Proposal (Recommended)"}})).stdout)
        approved = run_cli("status", "--task", "T-CC")["task"]
        self.assertNotIn("approval", approved["missing"])

    def test_claude_and_codex_clarify_planning_and_question_flow(self):
        import shlex
        planning_cli = str(HERE / "workflow_planning_cli.py")
        check_docs = str(HERE / "check_docs.py")
        card_rel = "docs/product/任务/账户.md"
        for host, q_tool, edit_tool in (
            ("claude", "AskUserQuestion", "MultiEdit"),
            ("codex", "request_user_input", "apply_patch"),
        ):
            session = f"clarify-{host}"
            with self.subTest(host=host):
                q_input = {"questions": [{"id": "q1", "question": "Q01 token rotation policy?", "multiSelect": False, "options": [{"label": "Invalidate immediately (Recommended)"}, {"label": "Grace period"}]}]}
                self.assertEqual(self.hook("PreToolUse", host, session_id=session, tool_name=q_tool, tool_input=q_input, tool_use_id=f"{host}-q1").stdout, "")
                self.assertEqual(self.hook("PostToolUse", host, session_id=session, tool_name=q_tool, tool_input=q_input, tool_use_id=f"{host}-q1", tool_response={"answers": {"q1": "Invalidate immediately (Recommended)"}}).stdout, "")

                cli_env = {k: v for k, v in os.environ.items() if not k.startswith("WORKFLOW_")}
                cli_env["WORKFLOW_ENGINE_HOME"] = self.tmp.name

                open_cmd = shlex.join(["python3", planning_cli, "open", "--root", str(self.project), "--session", session, "--operation", "clarify", "--path", card_rel])
                self.assertEqual(self.hook("PreToolUse", host, session_id=session, tool_name="Bash", tool_input={"command": open_cmd}).stdout, "")
                opened = subprocess.run(["python3", planning_cli, "open", "--root", str(self.project), "--session", session, "--operation", "clarify", "--path", card_rel], text=True, capture_output=True, env=cli_env)
                self.assertEqual(opened.returncode, 0, opened.stdout + opened.stderr)

                edit_input = {"file_path": card_rel} if edit_tool != "apply_patch" else {"patch": f"*** Begin Patch\n*** Add File: {card_rel}\n+clarified\n*** End Patch"}
                self.assertEqual(self.hook("PreToolUse", host, session_id=session, tool_name=edit_tool, tool_input=edit_input).stdout, "")

                bad_edit = json.loads(self.hook("PreToolUse", host, session_id=session, tool_name="Edit", tool_input={"file_path": "src/a.py"}).stdout)
                self.assertIn("ENGINE_PLANNING_TARGET_DENIED", bad_edit["hookSpecificOutput"]["permissionDecisionReason"])

                check_cmd = shlex.join(["python3", check_docs, "--root", str(self.project)])
                self.assertEqual(self.hook("PreToolUse", host, session_id=session, tool_name="Bash", tool_input={"command": check_cmd}).stdout, "")

                close_cmd = shlex.join(["python3", planning_cli, "close", "--root", str(self.project), "--session", session])
                self.assertEqual(self.hook("PreToolUse", host, session_id=session, tool_name="Bash", tool_input={"command": close_cmd}).stdout, "")
                closed = subprocess.run(["python3", planning_cli, "close", "--root", str(self.project), "--session", session], text=True, capture_output=True, env=cli_env)
                self.assertEqual(closed.returncode, 0, closed.stdout + closed.stderr)

                after_close = json.loads(self.hook("PreToolUse", host, session_id=session, tool_name="Edit", tool_input={"file_path": card_rel}).stdout)
                self.assertIn("ENGINE_TASK_UNBOUND", after_close["hookSpecificOutput"]["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
