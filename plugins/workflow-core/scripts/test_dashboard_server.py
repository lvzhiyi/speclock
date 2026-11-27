"""本机只读看板 HTTP 边界测试，不代替真实浏览器验证。"""
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, urlopen


class ServerTests(unittest.TestCase):
    def setUp(self):
        import dashboard_server
        self.dashboard_server = dashboard_server
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "ai-workflow.yaml").write_text("version: 1\n")
        self.server = dashboard_server.bind_server(self.root, None, 0)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def test_dashboard_and_foreign_host(self):
        with urlopen(self.url + "/api/dashboard") as response:
            data = json.load(response)
            self.assertIn("mode", data)
            self.assertNotIn("trace", data)
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.url + "/api/dashboard", headers={"Host": "evil.test"}))
        self.assertEqual(caught.exception.code, 403)

    def test_document_escape_and_post_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url + "/api/document?path=../private.md")
        self.assertEqual(caught.exception.code, 400)
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.url + "/api/dashboard", data=b"{}", method="POST"))
        self.assertEqual(caught.exception.code, 405)

    def test_task_first_page(self):
        with urlopen(self.url + "/") as response:
            page = response.read().decode("utf-8")
        self.assertNotIn("流程 · 8 步", page)
        self.assertNotIn("阻塞与待确认</h2>", page)
        self.assertNotIn("执行观测", page)
        for label in ("任务筛选", "双轴评审", "活动未知", "待人工验收"):
            self.assertIn(label, page)
        self.assertNotIn("旧配置 / 数据源未启用", page)
        self.assertNotIn("mode.configured_enabled", page)
        self.assertNotIn("innerHTML", page)
        self.assertIn("if (polling) return", page)
        self.assertIn("setTimeout(refresh,2000)", page)

    def test_bind_server_distinguishes_permission_error_from_port_in_use(self):
        attempts = []

        def fake_server(addr, handler):
            attempts.append(addr[1])
            if addr[1] == 8780:
                raise OSError(errno.EADDRINUSE, "Address already in use")
            raise PermissionError(errno.EPERM, "Operation not permitted")

        with patch.object(self.dashboard_server, "ThreadingHTTPServer", side_effect=fake_server):
            with self.assertRaises(self.dashboard_server.DashboardBlockedError) as caught:
                self.dashboard_server.bind_server(self.root)
        self.assertEqual(caught.exception.code, "SANDBOX_OR_PERMISSION")
        self.assertEqual(attempts, [8780, 8781])

    def test_ping_uses_no_proxy_and_surfaces_loopback_permission_error(self):
        state_file = self.dashboard_server.state_path(self.root)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps({"pid": 12345, "port": 8781, "root": str(self.root.resolve()), "task": None}),
            encoding="utf-8",
        )
        self.assertFalse(any(isinstance(h, ProxyHandler) for h in self.dashboard_server._NO_PROXY_OPENER.handlers))
        real_state = state_file.with_name("real.json")
        real_state.write_text(
            json.dumps({"pid": os.getpid(), "port": self.server.server_port, "root": str(self.root.resolve()), "task": None}),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}):
            self.assertIsNotNone(self.dashboard_server.ping(real_state))

        with patch.object(
            self.dashboard_server._NO_PROXY_OPENER,
            "open",
            side_effect=URLError(PermissionError(errno.EPERM, "Operation not permitted")),
        ):
            with self.assertRaises(self.dashboard_server.DashboardBlockedError) as caught:
                self.dashboard_server.ping(state_file)
        self.assertEqual(caught.exception.code, "SANDBOX_OR_PERMISSION")

        with patch.object(
            self.dashboard_server._NO_PROXY_OPENER,
            "open",
            side_effect=URLError(ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")),
        ):
            self.assertIsNone(self.dashboard_server.ping(state_file))

        self.assertIsNone(self.dashboard_server.ping(state_file.with_name("missing.json")))

    def test_status_and_off_preserve_state_file_on_sandbox_block(self):
        state_file = self.dashboard_server.state_path(self.root)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps({"pid": 12345, "port": 8781, "root": str(self.root.resolve()), "task": None}),
            encoding="utf-8",
        )
        with patch.object(
            self.dashboard_server._NO_PROXY_OPENER,
            "open",
            side_effect=URLError(PermissionError(errno.EPERM, "Operation not permitted")),
        ):
            for action in ("status", "off"):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = self.dashboard_server.main([action, "--root", str(self.root)])
                self.assertEqual(code, 2)
                self.assertIn("code=SANDBOX_OR_PERMISSION", buf.getvalue())
                self.assertTrue(state_file.exists())

    def test_on_surfaces_child_error_and_cleans_up_on_ping_permission_error(self):
        empty_root = Path(self.temp.name).resolve() / "empty-child-err"
        empty_root.mkdir()

        class FakeProc:
            pid = 99999
            stdout = None
            stderr = None

            def poll(self):
                return 2

            def wait(self, timeout=None):
                return 2

        with patch.object(self.dashboard_server.subprocess, "Popen", return_value=FakeProc()), patch.object(
            self.dashboard_server,
            "_read_startup_streams",
            return_value=("status=BLOCKED code=SANDBOX_OR_PERMISSION reason=模拟沙盒禁止绑定\n", ""),
        ):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = self.dashboard_server.main(["on", "--root", str(empty_root)])
            self.assertEqual(code, 2)
            self.assertIn("code=SANDBOX_OR_PERMISSION", buf.getvalue())
            self.assertIn("模拟沙盒禁止绑定", buf.getvalue())

        # 子进程成功绑定端口但回环 ping 被沙盒拦住时，必须终止子进程并清理 dashboard.json
        empty_root2 = Path(self.temp.name).resolve() / "empty-loopback-err"
        empty_root2.mkdir()
        spawned = []
        real_popen = subprocess.Popen

        def tracking_popen(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            spawned.append(proc)
            return proc

        def cleanup_any():
            for proc in spawned:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=2)

        self.addCleanup(cleanup_any)

        with patch.object(self.dashboard_server.subprocess, "Popen", side_effect=tracking_popen), patch.object(
            self.dashboard_server._NO_PROXY_OPENER,
            "open",
            side_effect=URLError(PermissionError(errno.EPERM, "Operation not permitted")),
        ):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = self.dashboard_server.main(["on", "--root", str(empty_root2)])
            self.assertEqual(code, 2)
            self.assertIn("code=SANDBOX_OR_PERMISSION", buf.getvalue())
            self.assertEqual(len(spawned), 1)
            self.assertIsNotNone(spawned[0].poll())
            self.assertFalse(self.dashboard_server.state_path(empty_root2).exists())

    def test_empty_project_on_status_off_lifecycle(self):
        empty_root = Path(self.temp.name).resolve() / "empty-lifecycle"
        empty_root.mkdir()
        self.addCleanup(lambda: self.dashboard_server.main(["off", "--root", str(empty_root)]))

        buf_on = io.StringIO()
        with contextlib.redirect_stdout(buf_on):
            code_on = self.dashboard_server.main(["on", "--root", str(empty_root)])
        self.assertEqual(code_on, 0, buf_on.getvalue())
        self.assertRegex(buf_on.getvalue().strip(), r"^status=ON url=http://127\.0\.0\.1:\d+/$")

        buf_status = io.StringIO()
        with contextlib.redirect_stdout(buf_status):
            code_status = self.dashboard_server.main(["status", "--root", str(empty_root)])
        self.assertEqual(code_status, 0, buf_status.getvalue())
        self.assertEqual(buf_status.getvalue().strip(), buf_on.getvalue().strip())

        buf_off = io.StringIO()
        with contextlib.redirect_stdout(buf_off):
            code_off = self.dashboard_server.main(["off", "--root", str(empty_root)])
        self.assertEqual(code_off, 0, buf_off.getvalue())
        self.assertEqual(buf_off.getvalue().strip(), "status=OFF")

    def test_dashboard_skill_mentions_escalation_guidance(self):
        skill_path = Path(__file__).resolve().parent.parent / "skills" / "dashboard" / "SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        self.assertIn("SANDBOX_OR_PERMISSION", text)
        self.assertIn("require_escalated", text)


if __name__ == "__main__":
    unittest.main()
