#!/usr/bin/env python3
"""单项目只读流程看板；服务状态写本机，不修改项目或引擎数据库。"""
import argparse
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import ProxyHandler, build_opener

from dashboard_data import build_dashboard, read_document
from dashboard_page import page_html
from workflow_engine.model import EngineError
from workflow_engine.state_dir import STATE_DIRNAME, ensure_state_dir, is_internal_state, state_dir

APP = "workflow-dashboard"
_PERMISSION_ERRNOS = {errno.EPERM, errno.EACCES, errno.EROFS}
_NO_PROXY_OPENER = build_opener(ProxyHandler({}))


class DashboardBlockedError(OSError):
    """带结构化原因码的看板受阻异常。"""

    def __init__(self, reason, code=None):
        super().__init__(reason)
        self.reason = reason
        self.code = code


def _permission_cause(error):
    """沿异常链剥离 URLError 等包装，识别沙盒或权限类系统错误。"""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, PermissionError) or getattr(current, "errno", None) in _PERMISSION_ERRNOS:
            return current
        if isinstance(current, URLError):
            current = current.reason
            continue
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, value, html=False):
        body = (value if html else json.dumps(value, ensure_ascii=False)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.reply(405, {"error": "read_only"})

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST

    def do_GET(self):
        port = self.server.server_port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return self.reply(403, {"error": "host"})
        parsed = urlparse(self.path)
        if parsed.path == "/api/ping":
            return self.reply(200, {"app": APP, "pid": os.getpid(), "root": str(self.root), "task": self.task})
        if parsed.path == "/":
            return self.reply(200, page_html(), html=True)
        try:
            if parsed.path == "/api/dashboard":
                return self.reply(200, build_dashboard(self.root, self.task))
            if parsed.path == "/api/document":
                path = parse_qs(parsed.query).get("path", [""])[0]
                # 只允许当前看板已登记的文档，不能把接口当成任意文件读取器。
                allowed = {item["path"] for item in build_dashboard(self.root, self.task)["documents"]}
                if path not in allowed:
                    return self.reply(400, {"error": "document_not_registered"})
                return self.reply(200, {"path": path, "content": read_document(self.root, path)})
        except (OSError, ValueError):
            return self.reply(400, {"error": "document_unavailable"})
        except Exception:
            return self.reply(503, {"error": "dashboard_unavailable"})
        self.reply(404, {"error": "path"})


def bind_server(root, task=None, port=None):
    handler = type("BoundDashboard", (Handler,), {"root": Path(root).resolve(), "task": task})
    candidates = [port] if port is not None else range(8780, 8790)
    for candidate in candidates:
        try:
            return ThreadingHTTPServer(("127.0.0.1", candidate), handler)
        except OSError as error:
            if port is None and error.errno == errno.EADDRINUSE:
                continue
            cause = _permission_cause(error)
            if cause is not None:
                raise DashboardBlockedError(
                    f"本机端口绑定被沙盒或权限拒绝（127.0.0.1:{candidate}: {cause}）",
                    code="SANDBOX_OR_PERMISSION",
                ) from error
            raise DashboardBlockedError(f"无法绑定本机看板端口 127.0.0.1:{candidate}（{error}）") from error
    raise DashboardBlockedError("没有可用看板端口（8780-8789 均已被占用）")


def state_path(root):
    return state_dir(root) / "dashboard.json"


def ping(path):
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as error:
        cause = _permission_cause(error)
        if cause is not None:
            raise DashboardBlockedError(
                f"无法读取看板状态文件 {path}（{cause}）",
                code="SANDBOX_OR_PERMISSION",
            ) from error
        return None
    try:
        state = json.loads(raw)
        port = state["port"]
        pid = state["pid"]
        root = state["root"]
    except (ValueError, KeyError, TypeError):
        return None
    try:
        with _NO_PROXY_OPENER.open(f"http://127.0.0.1:{port}/api/ping", timeout=1) as response:
            active = json.load(response)
    except OSError as error:
        cause = _permission_cause(error)
        if cause is not None:
            raise DashboardBlockedError(
                f"沙盒或权限禁止访问本机回环端口 127.0.0.1:{port}（{cause}）",
                code="SANDBOX_OR_PERMISSION",
            ) from error
        return None
    except ValueError:
        return None
    if active == {"app": APP, "pid": pid, "root": root, "task": state.get("task")}:
        return state
    return None


def _read_startup_streams(proc, timeout=5.0):
    """读取后台 serve 启动阶段的 stdout/stderr，直到子进程脱离或退出。"""
    selector = selectors.DefaultSelector()
    buffers = {}
    stdout_fd = proc.stdout.fileno() if proc.stdout is not None else None
    stderr_fd = proc.stderr.fileno() if proc.stderr is not None else None
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            buffers[stream.fileno()] = bytearray()
            selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            events = selector.select(timeout=remaining)
            if not events:
                break
            for key, _ in events:
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffers[key.fd].extend(chunk)
    finally:
        selector.close()
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
    out_bytes = buffers.get(stdout_fd, b"") if stdout_fd is not None else b""
    err_bytes = buffers.get(stderr_fd, b"") if stderr_fd is not None else b""
    return out_bytes.decode("utf-8", errors="replace"), err_bytes.decode("utf-8", errors="replace")


def _cleanup_spawned(proc, path):
    """清理本次启动失败遗留的后台进程及对应 PID 的状态文件。"""
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(state, dict) and state.get("pid") == proc.pid:
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def _parse_child_blocked(stdout_text, stderr_text):
    """提取子进程输出的 status=BLOCKED 结构化原因或最后一条错误文本。"""
    lines = [*stdout_text.splitlines(), *stderr_text.splitlines()]
    for line in lines:
        if line.startswith("status=BLOCKED "):
            match = re.match(r"^status=BLOCKED\s+(?:code=([^\s]+)\s+)?reason=(.+)$", line.strip())
            if match:
                return match.group(1), match.group(2)
    non_empty = [line.strip() for line in lines if line.strip()]
    return None, (non_empty[-1] if non_empty else None)


def _has_ready_marker(stdout_text):
    for line in stdout_text.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("ready") is True:
            return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("on", "off", "status", "serve"), nargs="?", default="status")
    parser.add_argument("--root", default=".")
    parser.add_argument("--task", default=os.environ.get("WORKFLOW_TASK_ID"))
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    path = state_path(root)
    try:
        if not root.is_dir():
            raise OSError("项目根目录不存在")
        if args.action == "serve":
            server = bind_server(root, args.task)
            try:
                try:
                    if (root / STATE_DIRNAME).is_symlink() or is_internal_state(root, path):
                        ensure_state_dir(root)
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    fd = os.open(str(path), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump({"pid": os.getpid(), "port": server.server_port, "root": str(root), "task": args.task}, handle)
                except OSError as error:
                    cause = _permission_cause(error)
                    if cause is not None:
                        raise DashboardBlockedError(
                            f"无法写入看板状态目录 {path.parent}（{cause}）",
                            code="SANDBOX_OR_PERMISSION",
                        ) from error
                    raise
            except BaseException:
                server.server_close()
                raise
            if os.environ.get("WORKFLOW_DASHBOARD_DETACH") == "1":
                sys.stdout.write(json.dumps({"ready": True, "port": server.server_port, "pid": os.getpid()}) + "\n")
                sys.stdout.flush()
                sys.stderr.flush()
                devnull = os.open(os.devnull, os.O_RDWR)
                try:
                    os.dup2(devnull, 1)
                    os.dup2(devnull, 2)
                finally:
                    if devnull > 2:
                        os.close(devnull)
            server.serve_forever()
            return 0
        active = ping(path)
        if args.action == "off":
            if active:
                try:
                    os.kill(active["pid"], signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except PermissionError as error:
                    raise DashboardBlockedError(
                        f"无权限停止看板进程 {active['pid']}（{error}）",
                        code="SANDBOX_OR_PERMISSION",
                    ) from error
            path.unlink(missing_ok=True)
            print("status=OFF")
            return 0
        if args.action == "on" and active and active.get("task") != args.task:
            print("status=BLOCKED reason=同项目已启动其他任务，请先off再on")
            return 2
        if args.action == "on" and not active:
            command = [sys.executable, str(Path(__file__).resolve()), "serve", "--root", str(root)]
            if args.task:
                command += ["--task", args.task]
            env = {**os.environ, "WORKFLOW_DASHBOARD_DETACH": "1"}
            proc = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=env,
            )
            try:
                stdout_text, stderr_text = _read_startup_streams(proc, timeout=5.0)
            except BaseException:
                _cleanup_spawned(proc, path)
                raise
            if not _has_ready_marker(stdout_text):
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                _cleanup_spawned(proc, path)
                code, reason = _parse_child_blocked(stdout_text, stderr_text)
                if reason:
                    raise DashboardBlockedError(reason, code=code)
                raise DashboardBlockedError("看板启动超时")
            for _ in range(10):
                try:
                    active = ping(path)
                except BaseException:
                    _cleanup_spawned(proc, path)
                    raise
                if active:
                    break
                time.sleep(0.05)
            if not active:
                _cleanup_spawned(proc, path)
                raise DashboardBlockedError("看板服务已拉起但本机回环校验未通过")
        print(f'status=ON url=http://127.0.0.1:{active["port"]}/' if active else "status=OFF")
        return 0
    except DashboardBlockedError as error:
        if error.code:
            print(f"status=BLOCKED code={error.code} reason={error.reason}")
        else:
            print(f"status=BLOCKED reason={error.reason}")
        return 2
    except (OSError, EngineError) as error:
        cause = _permission_cause(error)
        if cause is not None:
            print(f"status=BLOCKED code=SANDBOX_OR_PERMISSION reason=权限或沙盒受限（{cause}）")
        else:
            print(f"status=BLOCKED reason={error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
