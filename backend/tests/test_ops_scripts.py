import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8").lower()


def _isolated_stop_script(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "poker-stop-fixture"
    assets = project / "assets"
    assets.mkdir(parents=True)
    script = assets / "stop.ps1"
    shutil.copy2(ROOT / "assets" / "stop.ps1", script)
    return project, script


def _run_powershell_file(script: Path) -> subprocess.CompletedProcess[bytes]:
    powershell = shutil.which("powershell.exe")
    assert powershell is not None
    return subprocess.run(  # noqa: S603 - resolved executable and fixture-owned script
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        cwd=script.parent.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )


def test_backend_linter_enforces_security_rules_without_production_waiver():
    config = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    lint = config["tool"]["ruff"]["lint"]

    assert "S" in lint["select"]
    assert set(lint["per-file-ignores"]["tests/**/*.py"]) == {"S101", "S105", "S311"}


def _load_e2e_runner() -> ModuleType:
    path = ROOT / "frontend" / "e2e" / "run_e2e.py"
    spec = importlib.util.spec_from_file_location("poker_e2e_runner_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stop_script_only_targets_processes_recorded_by_this_project():
    script = _text("assets/stop.ps1")

    assert ".poker-arena.pids.json" in script
    assert "get-nettcpconnection" not in script
    assert "npm run dev" not in script
    assert "poker\\claude" not in script
    assert "win32_process" not in script
    assert "poker-arena-pids-v1" in script
    assert "assert-plainpidfile" in script
    assert "reparsepoint" in script
    assert "$maxpidfilebytes" in script
    assert "assert-exactproperties" in script
    assert "$records.count -ne 2" in script
    assert "@('backend', 'frontend')" in script
    assert "$allowedexecutables" in script
    assert "commandtype application" in script
    assert "get-verifiedownedtree" in script
    assert "stop-verifiedidentity" in script
    assert "starttime.touniversaltime().ticks" in script
    assert "nativeprocesstree" in script
    assert "createtoolhelp32snapshot" in script


def test_launchers_use_pid_managed_start_and_never_install_at_runtime():
    start = _text("assets/start.ps1")
    subir = _text("subir.bat")
    menu = _text("poker.bat")

    assert "start-process" in start
    assert ".poker-arena.pids.json" in start
    assert "npm install" not in subir
    assert "npm install" not in menu
    assert "assets\\start.ps1" in subir
    assert "assets\\start.ps1" in menu
    assert "assert-loopbackportavailable" in start
    assert "wait-httpready" in start
    assert "--strictport" in start
    assert "initialize-plainlog" in start
    assert "assert-plaindirectory" in start
    assert "reparsepoint" in start
    assert "[io.filemode]::createnew" in start
    assert "poker-arena-pids-v1" in start
    assert "start-isolatedprocess" in start
    assert "hashset[string]" in start
    assert "dictionary[string, string]" in start
    assert "startswith('poker_'" in start
    assert "setenvironmentvariable('vite_api', $frontendapi, 'process')" in start
    assert '$frontendapi = "http://127.0.0.1:$backendport"' in start
    assert "setenvironmentvariable('path', $safepath, 'process')" in start
    assert "pythonnousersite" in start
    assert "pythonsafepath" in start
    assert "/ready" in start
    assert "http://127.0.0.1:5173/?view=capture" in start
    assert "http://127.0.0.1:5173/?view=capture" in menu
    assert "setenvironmentvariable($name, $null, 'process')" in start
    assert "/pid $root.id /t /f" in start
    assert "stop-startedtree" in start
    assert "get-startedtreesnapshot" in start
    assert "choice /c 123450" in menu
    assert "assets\\preflight_banca.ps1" in menu
    assert "set /p" not in menu
    safe_powershell = "%systemroot%\\system32\\windowspowershell\\v1.0\\powershell.exe"
    assert safe_powershell in menu
    assert safe_powershell in subir
    assert "powershell -noprofile" not in menu
    assert "powershell -noprofile" not in subir
    stop_block = menu[menu.index(":stop") : menu.index(":open")]
    assert "if errorlevel 1" in stop_block
    assert "exit /b 1" in stop_block


def test_stop_script_terminates_only_the_verified_recorded_process_tree():
    script = _text("assets/stop.ps1")

    assert "actualexecutable -ine $record.executable" in script
    assert "startticks" in script
    assert "taskkill" in script
    assert "/pid $process.id /t" in script
    assert "readallbytes($pidfile)" in script
    assert "get-sha256hex" in script
    assert "registro de pid mudou durante o encerramento" in script
    fallback = script[script.index("if (-not $process.hasexited)") :]
    assert fallback.index("$ownedtree += @(get-verifiedownedtree $record)") < fallback.index(
        "stop-verifiedidentity $rootidentity"
    )


def test_stop_script_rejects_oversized_pid_file_without_removing_it(tmp_path):
    project, script = _isolated_stop_script(tmp_path)
    pid_file = project / ".poker-arena.pids.json"
    payload = b"x" * ((16 * 1024) + 1)
    pid_file.write_bytes(payload)

    result = _run_powershell_file(script)

    assert result.returncode != 0
    assert pid_file.read_bytes() == payload


def test_stop_script_rejects_executable_outside_role_allowlist(tmp_path):
    project, script = _isolated_stop_script(tmp_path)
    pid_file = project / ".poker-arena.pids.json"
    payload = {
        "schema": "poker-arena-pids-v1",
        "root": str(project.resolve()),
        "processes": [
            {
                "role": "backend",
                "pid": 1,
                "executable": str(project / "malicious.exe"),
                "startTicks": 1,
            },
            {
                "role": "frontend",
                "pid": 2,
                "executable": str(project / "also-malicious.exe"),
                "startTicks": 1,
            },
        ],
    }
    original = json.dumps(payload).encode()
    pid_file.write_bytes(original)

    result = _run_powershell_file(script)

    assert result.returncode != 0
    assert b"allowlist" in result.stdout.lower()
    assert pid_file.read_bytes() == original


def test_gitignore_uses_specific_credential_paths_without_hiding_security_code():
    gitignore = _text(".gitignore")

    assert "*secret*" not in gitignore
    assert "*token*" not in gitignore
    for required in (
        "/kaggle.json",
        "/chave.txt",
        "/modal2.txt",
        "/hf_token.txt",
        "/huggingface_token.txt",
        "/.credentials/",
        "/.secrets/",
    ):
        assert required in gitignore
    assert (ROOT / "backend" / "scripts" / "scan_secrets.py").is_file()
    assert (ROOT / "backend" / "tests" / "scripts" / "test_scan_secrets.py").is_file()


def test_release_metadata_is_coordinated_at_version_0_2_0():
    expected = "0.2.0"
    backend = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "backend" / "uv.lock").read_text(encoding="utf-8"))
    frontend = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    frontend_lock = json.loads(
        (ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8")
    )
    locked_backend = next(
        package for package in lock["package"] if package["name"] == "poker-arena"
    )

    assert backend["project"]["version"] == expected
    assert locked_backend["version"] == expected
    assert frontend["version"] == expected
    assert frontend_lock["version"] == expected
    assert frontend_lock["packages"][""]["version"] == expected
    assert f'__version__ = "{expected}"' in _text("backend/poker_arena/__init__.py")
    assert f'version="{expected}"' in _text("backend/poker_arena/api/app.py")
    assert f"api {expected}" in _text("api-docs/readme.md")


def test_powershell_operational_scripts_parse_without_syntax_errors():
    powershell = shutil.which("powershell.exe")
    assert powershell is not None
    command = (
        "$all=@(); "
        "foreach($p in @('assets\\start.ps1','assets\\stop.ps1','assets\\validar.ps1',"
        "'assets\\preflight_banca.ps1')) { "
        "$e=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $p), "
        "[ref]$null, [ref]$e) | Out-Null; $all += @($e) }; "
        "if($all.Count) { $all | ForEach-Object { $_.Message }; exit 1 }"
    )
    result = subprocess.run(  # noqa: S603 - resolved executable and fixed parser command
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout.decode(errors="replace")


def test_validation_script_runs_static_contract_security_and_test_gates():
    script = _text("assets/validar.ps1")

    for required in (
        "pytest",
        "ruff",
        "mypy",
        "generate.py",
        "$npmcommand test",
        "$npmcommand run build",
        "$npmcommand run lint",
        "$npmcommand audit",
        "pip-audit",
        "scan_secrets.py",
        "notebook security lint",
    ):
        assert required in script
    assert "[guid]::newguid" in script
    assert ".qa-run-" in script
    assert "getdirectoryname($resolvedtemp) -ne $projectroot" in script
    assert "remove-item -literalpath $resolvedtemp" in script
    assert ".qa_tmp\\validation\\pytest" not in script
    assert "poker_api_token" in script
    assert "poker_test_log_dir" in script
    assert "poker_enable_remote_vlm" in script
    assert "poker_model_manifest" in script
    assert "vite_api" in script
    assert 'remove-item -literalpath "env:$name"' in script
    assert "api-docs\\generate.py --check" in script
    assert "environmentsnapshot" in script
    assert "setenvironmentvariable($name, $originalvalue, 'process')" in script
    assert "reparsepoint" in script
    assert "push-location -literalpath" in script
    assert "waitforexit($timeoutseconds * 1000)" in script
    assert "taskkill.exe" in script
    assert "/t /f" in script
    assert "coverage_file" in script
    assert "mypy_cache_dir" in script
    assert "ruff_cache_dir" in script
    assert "vite_out_dir" in script
    assert "cache_dir=" in script
    assert "finally" in script
    assert "[environment]::systemdirectory" in script
    assert "resolve-plainapplication 'git.exe'" in script
    assert "split-path $gitexecutable -parent" in script
    assert "validate_distribution.py" in script and "--release" in script
    assert "$env:comspec = $cmdexecutable" in script
    assert "$cmdexecutable = join-path ([environment]::systemdirectory) 'cmd.exe'" in script
    assert "environmentcarrierpattern" in script
    assert "--select s,f821 --ignore s311" in script
    for credential_family in (
        "aws_",
        "azure_",
        "google_",
        "openrouter_",
        "database_url",
        "connection_string",
        "http_proxy",
        "pip_index_url",
        "npm_config_registry",
        "git_config_",
    ):
        assert credential_family in script


def test_e2e_runner_uses_isolated_logs_and_cleans_owned_runtime():
    runner = _text("frontend/e2e/run_e2e.py")
    config = _text("frontend/playwright.config.ts")
    navigation = _text("frontend/e2e/navigation.spec.ts")

    assert 'temporarydirectory(prefix=".e2e-run-", dir=root)' in runner
    assert "_subprocess_environment()" in runner
    assert "_cleanup_owned_resources" in runner
    assert "runtime.cleanup()" in runner
    assert 'base_env.update({"temp": str(runtime_root), "tmp": str(runtime_root)})' in runner
    assert "vlm_stub.assert_request_received()" in runner
    assert "backend_job: _windowsjob | none = none" in runner
    assert "backend_job.close()" in runner
    assert "process.env.poker_log_dir" not in config
    assert "requiredenvironment('poker_log_dir')" in config
    assert "playwright direto é bloqueado" in config
    assert ".qa_tmp" not in runner
    assert ".qa_tmp" not in config
    assert "_job_object_limit_kill_on_job_close" in runner
    assert "assignprocesstojobobject" in runner
    assert "def _start_owned_process(" in runner
    assert "process_job.assign(process)" in runner
    assert "sys.stdin.buffer.read(1)" in runner
    assert "poker_e2e_guide_dir" in navigation
    assert "navigation-guide" in runner
    assert "--update-navigation-guide" in runner
    assert "docs/assets/navigation-guide" not in navigation


def test_e2e_environment_is_an_allowlist(monkeypatch: pytest.MonkeyPatch):
    runner = _load_e2e_runner()
    monkeypatch.setenv("HF_TOKEN", "must-not-propagate")
    monkeypatch.setenv("POKER_API_TOKEN", "must-not-propagate")
    monkeypatch.setenv("POKER_VLM_URL", "https://remote.invalid")
    monkeypatch.setenv("PATH", "safe-runtime-path")

    child_env = runner._subprocess_environment()

    system_root, system32, comspec, _taskkill = runner._windows_runtime_paths()
    node = runner._find_node()
    assert "safe-runtime-path" not in child_env["PATH"]
    assert child_env["PATH"].split(os.pathsep) == [
        str(node.parent),
        str(system32),
        str(system_root),
    ]
    assert child_env["ComSpec"] == str(comspec)
    assert child_env["PLAYWRIGHT_CHANNEL"] == "msedge"
    assert "TEMP" not in child_env
    assert "TMP" not in child_env
    assert "HF_TOKEN" not in child_env
    assert "POKER_API_TOKEN" not in child_env
    assert "POKER_VLM_URL" not in child_env


def test_e2e_cleanup_attempts_every_owned_resource(monkeypatch: pytest.MonkeyPatch):
    runner = _load_e2e_runner()
    ui = object()
    backend = object()
    calls: list[object] = []

    def failing_stop(process: object) -> None:
        calls.append(process)
        if process is ui:
            raise RuntimeError("ui stop failed")

    class FailingRuntime:
        def cleanup(self) -> None:
            calls.append("runtime")
            raise OSError("runtime cleanup failed")

    monkeypatch.setattr(runner, "_stop_exact_process", failing_stop)

    with pytest.raises(ExceptionGroup) as caught:
        runner._cleanup_owned_resources(ui, backend, FailingRuntime())

    assert calls == [ui, backend, "runtime"]
    assert len(caught.value.exceptions) == 2


def test_e2e_windows_job_object_terminates_owned_descendant_tree():
    runner = _load_e2e_runner()
    if os.name != "nt":
        pytest.skip("Windows Job Object contract is Windows-specific")

    parent_code = (
        "import subprocess,sys,time;"
        "sys.stdin.buffer.readline();"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "print(child.pid,flush=True);"
        "time.sleep(60)"
    )
    parent = subprocess.Popen(  # noqa: S603 - fixed interpreter and test-only source
        [sys.executable, "-c", parent_code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    job = runner._WindowsJob()
    child_pid = 0
    try:
        job.assign(parent)
        assert parent.stdin is not None
        assert parent.stdout is not None
        parent.stdin.write(b"spawn\n")
        parent.stdin.flush()
        child_pid = int(parent.stdout.readline().strip())
        assert child_pid > 0
        job.close()
        parent.wait(timeout=10)

        kernel32 = runner.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (
            runner.wintypes.DWORD,
            runner.wintypes.BOOL,
            runner.wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = runner.wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (runner.wintypes.HANDLE, runner.wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = runner.wintypes.DWORD
        kernel32.CloseHandle.argtypes = (runner.wintypes.HANDLE,)
        child_handle = kernel32.OpenProcess(0x00100000, False, child_pid)
        if child_handle:
            try:
                assert kernel32.WaitForSingleObject(child_handle, 5000) == 0
            finally:
                kernel32.CloseHandle(child_handle)
    finally:
        job.close()
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)


def test_e2e_windows_stop_accepts_successful_exact_process_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    runner = _load_e2e_runner()

    class OwnedProcess:
        pid = 4242

        def __init__(self) -> None:
            self.killed = False
            self.wait_calls = 0

        def poll(self):
            return 9 if self.killed else None

        def wait(self, timeout: float):
            del timeout
            self.wait_calls += 1
            if not self.killed:
                raise subprocess.TimeoutExpired(["owned"], 15)
            return 9

        def kill(self) -> None:
            self.killed = True

    process = OwnedProcess()
    windows = Path("C:/Windows")
    system32 = windows / "System32"
    monkeypatch.setattr(
        runner,
        "_windows_runtime_paths",
        lambda: (windows, system32, system32 / "cmd.exe", system32 / "taskkill.exe"),
    )
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
    )

    runner._stop_exact_process(process)

    assert process.killed is True
    assert process.wait_calls == 2


def test_manual_pytest_runtime_uses_owned_os_temp_not_checkout_acl_directories():
    conftest = _text("backend/tests/conftest.py")

    assert "tempfile.mkdtemp(prefix=_manual_run_prefix)" in conftest
    assert "tempfile.gettempdir()" in conftest
    assert 'manual_run_prefix = "poker-arena-pytest-"' in conftest
    assert ".pytest-run-" not in conftest
