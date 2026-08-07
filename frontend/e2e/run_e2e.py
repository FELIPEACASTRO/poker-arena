"""Run the browser suite with isolated inputs and deterministic process cleanup.

The supported entry point is ``npm run test:e2e``.  This runner builds the E2E
frontend inside a unique workspace-local runtime, starts the exact backend/UI
processes, passes a small environment allowlist and attempts every cleanup even
when an earlier terminate/kill operation fails.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import winreg
from ctypes import Structure, WinDLL, byref, c_size_t, get_last_error, sizeof, wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

HOST = "127.0.0.1"
API_PORT = 8765
UI_PORT = 4177
RUNNER = Path(os.path.abspath(__file__))
ROOT = RUNNER.parents[2]
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"
PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"

_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "ALLUSERSPROFILE",
        "APPDATA",
        "CI",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "PROCESSOR_ARCHITECTURE",
        "PROGRAMDATA",
        "PUBLIC",
        "USERPROFILE",
    }
)

_LOOPBACK_OPENER = build_opener(ProxyHandler({}))
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_VLM_RESPONSE = json.dumps(
    {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "hole": ["As", "Kd"],
                            "board": ["2h", "6c", "Tc"],
                            "pot": 700,
                            "num_players": 2,
                            "position": "BTN",
                            "stacks": {"0": 1000},
                        },
                        separators=(",", ":"),
                    )
                }
            }
        ]
    },
    separators=(",", ":"),
).encode("utf-8")

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_OWNED_PROCESS_WRAPPER = (
    "import subprocess,sys;"
    "sys.stdin.buffer.read(1);"
    "raise SystemExit(subprocess.call(sys.argv[1:]))"
)


class _IoCounters(Structure):
    _fields_ = [
        ("ReadOperationCount", wintypes.ULARGE_INTEGER),
        ("WriteOperationCount", wintypes.ULARGE_INTEGER),
        ("OtherOperationCount", wintypes.ULARGE_INTEGER),
        ("ReadTransferCount", wintypes.ULARGE_INTEGER),
        ("WriteTransferCount", wintypes.ULARGE_INTEGER),
        ("OtherTransferCount", wintypes.ULARGE_INTEGER),
    ]


class _JobObjectBasicLimitInformation(Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", c_size_t),
        ("MaximumWorkingSetSize", c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JobObjectExtendedLimitInformation(Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", c_size_t),
        ("JobMemoryLimit", c_size_t),
        ("PeakProcessMemoryUsed", c_size_t),
        ("PeakJobMemoryUsed", c_size_t),
    ]


class _WindowsJob:
    """Own a Windows Job Object that kills every assigned process tree on close."""

    def __init__(self) -> None:
        self._kernel32: Any | None = None
        self._handle: int | None = None
        if os.name != "nt":
            return
        kernel32 = WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            wintypes.INT,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(get_last_error(), "CreateJobObjectW failed")
        limits = _JobObjectExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            byref(limits),
            sizeof(limits),
        ):
            error = get_last_error()
            kernel32.CloseHandle(handle)
            raise OSError(error, "SetInformationJobObject failed")
        self._kernel32 = kernel32
        self._handle = int(handle)

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        if self._handle is None:
            return
        process_handle = getattr(process, "_handle", None)
        if process_handle is None:
            raise RuntimeError("Popen Windows handle unavailable for Job Object assignment")
        kernel32 = self._kernel32
        if kernel32 is None or not kernel32.AssignProcessToJobObject(
            wintypes.HANDLE(self._handle), wintypes.HANDLE(int(process_handle))
        ):
            raise OSError(get_last_error(), "AssignProcessToJobObject failed")

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        kernel32 = self._kernel32
        self._kernel32 = None
        if kernel32 is None or not kernel32.CloseHandle(wintypes.HANDLE(handle)):
            raise OSError(get_last_error(), "CloseHandle(job) failed")


def _start_owned_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    process_job: _WindowsJob,
) -> subprocess.Popen[bytes]:
    """Assign a blocked wrapper before it is allowed to create the real child."""

    process = subprocess.Popen(  # noqa: S603 - fixed wrapper and controlled argv
        [str(PYTHON), "-c", _OWNED_PROCESS_WRAPPER, *command],
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
    )
    try:
        process_job.assign(process)
        if process.stdin is None:
            raise RuntimeError("owned process trigger pipe unavailable")
        process.stdin.write(b"1")
        process.stdin.close()
    except BaseException:
        process.kill()
        process.wait(timeout=5)
        raise
    return process


def _assert_regular_path(path: Path, *, directory: bool) -> Path:
    """Reject symlinks/junctions and require an ordinary file or directory."""

    candidate = Path(os.path.abspath(path))
    if not candidate.is_absolute():
        raise RuntimeError(f"Caminho E2E deve ser absoluto: {candidate}")
    chain = list(reversed((candidate, *candidate.parents)))
    for component in chain:
        try:
            metadata = component.lstat()
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Caminho E2E ausente: {component}") from exc
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
        ):
            raise RuntimeError(f"Caminho E2E com reparse point recusado: {component}")
    metadata = candidate.lstat()
    valid = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if not valid:
        kind = "diretorio" if directory else "arquivo"
        raise RuntimeError(f"Caminho E2E nao e {kind} regular: {candidate}")
    return candidate


def _registry_path(key_name: str, value_name: str) -> Path:
    access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_name, 0, access) as key:
        value, _kind = winreg.QueryValueEx(key, value_name)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Registro do Windows invalido: {key_name}::{value_name}")
    return Path(value)


def _known_windows_directories() -> tuple[Path, Path, Path]:
    system_root = _assert_regular_path(
        _registry_path(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "SystemRoot"),
        directory=True,
    )
    current_version = r"SOFTWARE\Microsoft\Windows\CurrentVersion"
    program_files = _assert_regular_path(
        _registry_path(current_version, "ProgramFilesDir"), directory=True
    )
    program_files_x86 = _assert_regular_path(
        _registry_path(current_version, "ProgramFilesDir (x86)"), directory=True
    )
    return system_root, program_files, program_files_x86


def _windows_runtime_paths() -> tuple[Path, Path, Path, Path]:
    system_root, _program_files, _program_files_x86 = _known_windows_directories()
    system32 = _assert_regular_path(system_root / "System32", directory=True)
    comspec = _assert_regular_path(system32 / "cmd.exe", directory=False)
    taskkill = _assert_regular_path(system32 / "taskkill.exe", directory=False)
    return system_root, system32, comspec, taskkill


def _find_node() -> Path:
    _system_root, program_files, program_files_x86 = _known_windows_directories()
    candidates = [
        program_files / "nodejs" / "node.exe",
        program_files_x86 / "nodejs" / "node.exe",
    ]
    for candidate in candidates:
        if os.path.lexists(candidate):
            return _assert_regular_path(candidate, directory=False)
    raise FileNotFoundError("Node.js regular nao encontrado em Program Files.")


def _assert_edge_runtime() -> Path:
    _system_root, program_files, program_files_x86 = _known_windows_directories()
    candidates = [
        program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for candidate in candidates:
        if os.path.lexists(candidate):
            return _assert_regular_path(candidate, directory=False)
    raise FileNotFoundError("Runtime regular do Microsoft Edge nao encontrado.")


def _subprocess_environment() -> dict[str, str]:
    """Build a deterministic environment without inherited Node/Python vectors."""

    node = _find_node()
    _assert_edge_runtime()
    _system_root, program_files, program_files_x86 = _known_windows_directories()
    system_root, system32, comspec, _taskkill = _windows_runtime_paths()
    environment = {
        name: value
        for name in sorted(_ENVIRONMENT_ALLOWLIST)
        if (value := os.environ.get(name))
    }
    environment.update(
        {
            "ComSpec": str(comspec),
            "PATH": os.pathsep.join((str(node.parent), str(system32), str(system_root))),
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "PLAYWRIGHT_CHANNEL": "msedge",
            "ProgramFiles": str(program_files),
            "ProgramFiles(x86)": str(program_files_x86),
            "ProgramW6432": str(program_files),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "SystemRoot": str(system_root),
            "WINDIR": str(system_root),
        }
    )
    return environment


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection((HOST, port), timeout=0.25):
            return True
    except OSError:
        return False


def _wait_for_http(url: str, process: subprocess.Popen[bytes], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Servidor E2E terminou prematuramente com código {process.returncode}."
            )
        try:
            with _LOOPBACK_OPENER.open(  # noqa: S310 - fixed loopback, proxies disabled
                url, timeout=1.0
            ) as response:
                if 200 <= response.status < 300:
                    return
        except (OSError, URLError):
            pass
        time.sleep(0.2)
    raise TimeoutError(f"Servidor E2E não respondeu a tempo em {url}.")


def _stop_exact_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        system_root, system32, comspec, taskkill = _windows_runtime_paths()
        control_env = {
            "ComSpec": str(comspec),
            "PATH": str(system32),
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "SystemRoot": str(system_root),
            "WINDIR": str(system_root),
        }
        try:
            result = subprocess.run(  # noqa: S603 - validated absolute Windows utility
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                env=control_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            raise
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            # Some Windows/Python combinations do not observe taskkill's process
            # signal promptly even after the tree request returned.  Killing the
            # exact Popen handle is a safe, owned fallback; only a failed fallback
            # is a cleanup error.
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"Nao foi possivel encerrar o processo E2E proprio PID {process.pid}; "
                    f"taskkill={result.returncode}."
                ) from exc
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class _VlmStub:
    """Ephemeral no-log OpenAI-compatible loopback used only by protected E2E."""

    def __init__(self, expected_token: str) -> None:
        self._expected_authorization = f"Bearer {expected_token}"
        self._received = threading.Event()
        self._errors: list[str] = []
        self._lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: object) -> None:
                del args

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
                stub._handle_post(self)

            def do_GET(self) -> None:  # noqa: N802 - explicit fail-closed stub
                self.send_error(405)

        self._server = ThreadingHTTPServer((HOST, 0), Handler)
        self._server.daemon_threads = True
        self.port = int(self._server.server_address[1])
        self.url = f"http://{HOST}:{self.port}/v1/chat/completions"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="poker-e2e-vlm-stub",
            daemon=True,
        )
        self._thread.start()

    def _record_error(self, message: str) -> None:
        with self._lock:
            self._errors.append(message)

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        failures: list[str] = []
        if handler.path != "/v1/chat/completions":
            failures.append("path inesperado")
        raw_length = handler.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError:
            length = -1
        if not 0 < length <= 8_000_000:
            failures.append("Content-Length invalido")
            body = b""
        else:
            body = handler.rfile.read(length)
        try:
            payload = json.loads(body)
            content = payload["messages"][0]["content"]
        except (IndexError, KeyError, TypeError, ValueError):
            content = []
            failures.append("payload OpenAI invalido")
        if not isinstance(content, list) or not any(
            isinstance(item, dict) and item.get("type") == "text" for item in content
        ):
            failures.append("prompt textual ausente")
        if not isinstance(content, list) or not any(
            isinstance(item, dict)
            and item.get("type") == "image_url"
            and isinstance(item.get("image_url"), dict)
            and str(item["image_url"].get("url", "")).startswith("data:image/jpeg;base64,")
            for item in content
        ):
            failures.append("imagem redigida ausente")
        if handler.headers.get("Authorization") != self._expected_authorization:
            failures.append("Authorization ausente ou incorreta")
        if handler.headers.get("Cache-Control") != "no-store":
            failures.append("Cache-Control nao e no-store")
        if handler.headers.get("X-Poker-Data-Handling") != "transient-no-store":
            failures.append("politica transiente ausente")
        if not re.fullmatch(
            r"[a-f0-9]{64}", handler.headers.get("X-Poker-Consent-Session-SHA256", "")
        ):
            failures.append("digest de consentimento invalido")
        if handler.headers.get("X-Poker-Redaction") != "configured-mask-v1":
            failures.append("identificador de redacao invalido")

        if failures:
            for failure in failures:
                self._record_error(failure)
            response = b'{"error":"invalid e2e request"}'
            handler.send_response(400)
        else:
            self._received.set()
            response = _VLM_RESPONSE
            handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(response)))
        handler.end_headers()
        handler.wfile.write(response)

    def assert_request_received(self) -> None:
        if not self._received.wait(timeout=2):
            details = ", ".join(self._errors) if self._errors else "nenhum POST recebido"
            raise RuntimeError(f"Stub VLM E2E nao recebeu request valido: {details}.")

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        self._expected_authorization = ""
        if self._thread.is_alive():
            raise RuntimeError("Thread do stub VLM E2E permaneceu ativa.")
        if _port_is_open(self.port):
            raise RuntimeError(f"Porta efemera do stub VLM permaneceu aberta: {self.port}.")


def _cleanup_owned_resources(
    ui_process: subprocess.Popen[bytes] | None,
    backend_process: subprocess.Popen[bytes] | None,
    runtime: tempfile.TemporaryDirectory[str],
    vlm_stub: _VlmStub | None = None,
    process_job: _WindowsJob | None = None,
    backend_job: _WindowsJob | None = None,
) -> None:
    """Attempt every owned cleanup and report all failures together."""

    errors: list[Exception] = []
    for label, process in (("ui", ui_process), ("backend", backend_process)):
        if process is None:
            continue
        try:
            _stop_exact_process(process)
        except Exception as exc:  # cleanup must continue for the other owned resources
            exc.add_note(f"falha ao encerrar processo E2E: {label}")
            errors.append(exc)
    for label, job in (("runtime", process_job), ("backend", backend_job)):
        if job is None:
            continue
        try:
            # KILL_ON_JOB_CLOSE is the authoritative tree-cleanup backstop. It
            # also covers descendants that a blocked taskkill could not reach.
            job.close()
        except Exception as exc:
            exc.add_note(f"falha ao fechar Job Object E2E: {label}")
            errors.append(exc)
    if vlm_stub is not None:
        try:
            vlm_stub.close()
        except Exception as exc:  # cleanup must still remove the isolated runtime
            exc.add_note("falha ao encerrar stub VLM E2E")
            errors.append(exc)
    try:
        runtime.cleanup()
    except Exception as exc:  # cleanup errors remain visible after both process attempts
        exc.add_note("falha ao remover runtime E2E isolado")
        errors.append(exc)
    if errors:
        raise ExceptionGroup("falhas no cleanup E2E", errors)  # noqa: F821


def _run_checked(
    command: list[str], *, env: dict[str, str], process_job: _WindowsJob
) -> None:
    process = _start_owned_process(
        command, cwd=FRONTEND, env=env, process_job=process_job
    )
    returncode = process.wait()
    if returncode != 0:
        raise RuntimeError(f"Build E2E falhou com código {returncode}.")


def main() -> int:
    passthrough_arguments = [
        argument for argument in sys.argv[1:] if argument != "--update-navigation-guide"
    ]
    update_navigation_guide = "--update-navigation-guide" in sys.argv[1:]
    if not PYTHON.is_file():
        raise FileNotFoundError(f"Python do backend não encontrado: {PYTHON}")
    _assert_regular_path(RUNNER, directory=False)
    _assert_regular_path(ROOT, directory=True)
    _assert_regular_path(FRONTEND, directory=True)
    _assert_regular_path(BACKEND, directory=True)
    _assert_regular_path(PYTHON, directory=False)
    node = _find_node()
    _assert_edge_runtime()
    playwright_cli = FRONTEND / "node_modules" / "@playwright" / "test" / "cli.js"
    tsc_cli = FRONTEND / "node_modules" / "typescript" / "bin" / "tsc"
    vite_cli = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
    for cli in (playwright_cli, tsc_cli, vite_cli):
        _assert_regular_path(cli, directory=False)
    if not all(path.is_file() for path in (playwright_cli, tsc_cli, vite_cli)):
        raise FileNotFoundError("Dependências E2E ausentes; execute npm ci no frontend.")

    occupied = [port for port in (API_PORT, UI_PORT) if _port_is_open(port)]
    if occupied:
        raise RuntimeError(f"Portas E2E já estão em uso: {', '.join(map(str, occupied))}.")

    runtime = tempfile.TemporaryDirectory(prefix=".e2e-run-", dir=ROOT)
    runtime_root = _assert_regular_path(Path(runtime.name), directory=True)
    log_dir = runtime_root / "logs"
    dist_dir = runtime_root / "dist"
    guide_dir = (
        ROOT / "docs" / "assets" / "navigation-guide"
        if update_navigation_guide
        else runtime_root / "navigation-guide"
    )
    log_dir.mkdir()
    dist_dir.mkdir()
    if update_navigation_guide:
        _assert_regular_path(guide_dir, directory=True)
    else:
        guide_dir.mkdir()
        _assert_regular_path(guide_dir, directory=True)
    _assert_regular_path(log_dir, directory=True)
    _assert_regular_path(dist_dir, directory=True)

    base_env = _subprocess_environment()
    base_env.update({"TEMP": str(runtime_root), "TMP": str(runtime_root)})
    build_env = {
        **base_env,
        "VITE_API": f"http://{HOST}:{API_PORT}",
        "VITE_CACHE_DIR": str(runtime_root / "vite-cache"),
        "VITE_OUT_DIR": str(dist_dir),
    }
    backend_env = {
        **base_env,
        "POKER_LOG_DIR": str(log_dir),
        "POKER_WARMUP": "0",
    }
    test_env = {
        **base_env,
        "PLAYWRIGHT_OUTPUT_DIR": str(runtime_root / "test-results"),
        "POKER_E2E_DIST_DIR": str(dist_dir),
        "POKER_E2E_GUIDE_DIR": str(guide_dir),
        "POKER_LOG_DIR": str(log_dir),
        "PW_REUSE_EXISTING_SERVER": "1",
    }

    backend_process: subprocess.Popen[bytes] | None = None
    ui_process: subprocess.Popen[bytes] | None = None
    vlm_stub: _VlmStub | None = None
    e2e_api_token = ""
    protected_backend_env: dict[str, str] = {}
    protected_test_env: dict[str, str] = {}
    process_job: _WindowsJob | None = None
    backend_job: _WindowsJob | None = None
    try:
        process_job = _WindowsJob()
        backend_job = _WindowsJob()
        _run_checked(
            [str(node), str(tsc_cli), "--noEmit"],
            env=build_env,
            process_job=process_job,
        )
        _run_checked(
            [
                str(node),
                str(tsc_cli),
                "--noEmit",
                "--target",
                "ES2020",
                "--lib",
                "ES2020,DOM",
                "--module",
                "ESNext",
                "--moduleResolution",
                "bundler",
                "--skipLibCheck",
                "--strict",
                "--noUnusedLocals",
                "--noUnusedParameters",
                "--noFallthroughCasesInSwitch",
                "e2e/navigation.spec.ts",
                "e2e/remote-consent.spec.ts",
            ],
            env=build_env,
            process_job=process_job,
        )
        _run_checked(
            [
                str(node),
                str(vite_cli),
                "build",
                "--configLoader",
                "runner",
                "--mode",
                "e2e",
                "--emptyOutDir",
            ],
            env=build_env,
            process_job=process_job,
        )
        _assert_regular_path(dist_dir, directory=True)
        vite_cache = runtime_root / "vite-cache"
        if os.path.lexists(vite_cache):
            _assert_regular_path(vite_cache, directory=True)
        backend_process = _start_owned_process(
            [
                str(PYTHON),
                "-m",
                "uvicorn",
                "poker_arena.api.app:app",
                "--host",
                HOST,
                "--port",
                str(API_PORT),
            ],
            cwd=BACKEND,
            env=backend_env,
            process_job=backend_job,
        )
        ui_process = _start_owned_process(
            [str(PYTHON), "-m", "http.server", str(UI_PORT), "--bind", HOST],
            cwd=dist_dir,
            env=base_env,
            process_job=process_job,
        )
        _wait_for_http(f"http://{HOST}:{API_PORT}/ready", backend_process)
        _wait_for_http(f"http://{HOST}:{UI_PORT}/", ui_process)

        test_process = _start_owned_process(
            [
                str(node),
                str(playwright_cli),
                "test",
                "e2e/navigation.spec.ts",
                *passthrough_arguments,
            ],
            cwd=FRONTEND,
            env=test_env,
            process_job=process_job,
        )
        test_returncode = test_process.wait()
        if test_returncode != 0:
            return test_returncode

        # O WebSocket de navegador não aceita cabeçalhos arbitrários, enquanto a
        # emissão de consentimento remoto exige autenticação. Reutilize a mesma porta
        # em um segundo ciclo curto e isolado, com credencial efêmera gerada aqui (nunca
        # herdada, persistida ou impressa).
        _stop_exact_process(backend_process)
        backend_job.close()
        backend_job = None
        deadline = time.monotonic() + 10
        while _port_is_open(API_PORT) and time.monotonic() < deadline:
            time.sleep(0.1)
        if _port_is_open(API_PORT):
            raise RuntimeError("Job Object nao liberou a porta do backend publico")
        backend_process = None
        e2e_api_token = secrets.token_urlsafe(32)
        vlm_stub = _VlmStub(e2e_api_token)
        protected_backend_env = {
            **backend_env,
            "POKER_API_TOKEN": e2e_api_token,
            "POKER_ENABLE_REMOTE_VLM": "1",
            "POKER_VLM_API_TOKEN": e2e_api_token,
            "POKER_VLM_URL": vlm_stub.url,
            "POKER_VLM_REDACT_REGIONS": "0,0,1,1",
            "POKER_VLM_TIMEOUT": "2",
        }
        backend_job = _WindowsJob()
        backend_process = _start_owned_process(
            [
                str(PYTHON),
                "-m",
                "uvicorn",
                "poker_arena.api.app:app",
                "--host",
                HOST,
                "--port",
                str(API_PORT),
            ],
            cwd=BACKEND,
            env=protected_backend_env,
            process_job=backend_job,
        )
        _wait_for_http(f"http://{HOST}:{API_PORT}/ready", backend_process)
        protected_test_env = {**test_env, "POKER_E2E_API_TOKEN": e2e_api_token}
        protected_test_process = _start_owned_process(
            [
                str(node),
                str(playwright_cli),
                "test",
                "e2e/remote-consent.spec.ts",
                *passthrough_arguments,
            ],
            cwd=FRONTEND,
            env=protected_test_env,
            process_job=process_job,
        )
        protected_returncode = protected_test_process.wait()
        if protected_returncode == 0:
            vlm_stub.assert_request_received()
        return protected_returncode
    finally:
        for environment in (
            base_env,
            build_env,
            backend_env,
            test_env,
            protected_backend_env,
            protected_test_env,
        ):
            environment.pop("POKER_API_TOKEN", None)
            environment.pop("POKER_VLM_API_TOKEN", None)
            environment.pop("POKER_E2E_API_TOKEN", None)
        e2e_api_token = ""
        _cleanup_owned_resources(
            ui_process,
            backend_process,
            runtime,
            vlm_stub,
            process_job,
            backend_job,
        )


if __name__ == "__main__":
    raise SystemExit(main())
