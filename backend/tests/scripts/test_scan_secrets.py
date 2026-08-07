from __future__ import annotations

import hashlib
from pathlib import Path

import scripts.scan_secrets as scanner
from scripts.scan_secrets import main, scan


def test_scanner_detects_provider_and_generic_secrets_without_storing_values(tmp_path: Path) -> None:
    provider_secret = "hf_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    generic_secret = "RealCredentialValue987654321"
    source = tmp_path / "leak.txt"
    source.write_text(
        f"token={provider_secret}\nAPI_KEY={generic_secret}\n",
        encoding="utf-8",
    )

    findings = scan(tmp_path)

    assert {(item.kind, item.path, item.line) for item in findings} == {
        ("huggingface_token", "leak.txt", 1),
        ("credential_assignment", "leak.txt", 2),
    }
    assert all(provider_secret not in repr(item) and generic_secret not in repr(item) for item in findings)


def test_scanner_accepts_placeholders_and_ignores_dependency_tree(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "API_KEY=CHANGE-ME-PLACEHOLDER\n"
        "HF_TOKEN=<segredo-obtido-do-ambiente>\n"
        "OPENAI_API_KEY={apiToken}\n"
        "KAGGLE_KEY=(runtime_value)\n"
        "MODAL_TOKEN=userdata.get('MODAL_TOKEN')\n"
        "ANTHROPIC_API_KEY=_required_secret('ANTHROPIC_API_KEY')\n",
        encoding="utf-8",
    )
    dependency = tmp_path / "node_modules" / "package"
    dependency.mkdir(parents=True)
    (dependency / "fixture.txt").write_text(
        "API_KEY=" + "RealDependency" + "Secret12345", encoding="utf-8"
    )
    (tmp_path / "runtime.py").write_text(
        'child_env = {"POKER_API_TOKEN": generated_api_token}\n', encoding="utf-8"
    )

    assert scan(tmp_path) == []
    assert main(["--root", str(tmp_path)]) == 0


def test_scanner_ignores_only_named_generated_runtime_directories(tmp_path: Path) -> None:
    credential_name = "_".join(("POKER", "API", "TOKEN"))
    for name in (".e2e-run-generated", ".poker-arena-runtime"):
        generated = tmp_path / name
        generated.mkdir()
        (generated / "ephemeral.txt").write_text(
            f"{credential_name}=" + "GeneratedRuntime" + "Credential123456",
            encoding="utf-8",
        )

    lookalike = tmp_path / ".e2e-generated-lookalike"
    lookalike.mkdir()
    (lookalike / "source.env").write_text(
        f"{credential_name}=" + "SourceCredential" + "MustBeFound123456",
        encoding="utf-8",
    )

    assert [(item.kind, item.path) for item in scan(tmp_path)] == [
        ("credential_assignment", ".e2e-generated-lookalike/source.env")
    ]


def test_scanner_does_not_skip_cache_lookalike_directories(tmp_path: Path) -> None:
    secret = "CacheLookalikeCredential987654321"
    lookalike = tmp_path / ".npm-cache-malicious"
    lookalike.mkdir()
    (lookalike / "settings.env").write_text(
        f"POKER_API_TOKEN={secret}\n", encoding="utf-8"
    )

    assert ("credential_assignment", ".npm-cache-malicious/settings.env") in {
        (item.kind, item.path) for item in scan(tmp_path)
    }


def test_scanner_reports_only_location_not_secret(tmp_path: Path, capsys) -> None:
    secret = "sk-proj-" + "Z9y8X7w6V5u4T3s2R1q0P9o8"
    (tmp_path / "notebook.ipynb").write_text(f'{{"output":"{secret}"}}', encoding="utf-8")

    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    path_digest = hashlib.sha256(b"notebook.ipynb").hexdigest()[:16]
    assert f"openai_token: path_sha256={path_digest} line=1" in output
    assert secret not in output


def test_scanner_rejects_sensitive_credential_filename_even_when_empty(tmp_path: Path) -> None:
    (tmp_path / "kaggle.json").write_text("{}", encoding="utf-8")

    assert [(item.kind, item.path) for item in scan(tmp_path)] == [
        ("sensitive_filename", "kaggle.json")
    ]


def test_scanner_rejects_environment_npm_and_netrc_credential_files(tmp_path: Path) -> None:
    for name in (".env.staging", ".npmrc", ".netrc", "_netrc"):
        (tmp_path / name).write_text("", encoding="utf-8")

    assert {(item.kind, item.path) for item in scan(tmp_path)} == {
        ("sensitive_filename", ".env.staging"),
        ("sensitive_filename", ".netrc"),
        ("sensitive_filename", ".npmrc"),
        ("sensitive_filename", "_netrc"),
    }


def test_scanner_detects_npmrc_and_netrc_syntax_under_disguised_names(tmp_path: Path) -> None:
    npm_secret = "npm_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    netrc_secret = "NetrcCredential987654321"
    (tmp_path / "registry.conf").write_text(
        f"//registry.npmjs.org/:_authToken={npm_secret}\n", encoding="utf-8"
    )
    (tmp_path / "machine.conf").write_text(
        f"machine api.example.invalid login alice password {netrc_secret}\n",
        encoding="utf-8",
    )

    found = {(item.kind, item.path) for item in scan(tmp_path)}

    assert ("npm_token", "registry.conf") in found
    assert ("credential_assignment", "registry.conf") in found
    assert ("credential_assignment", "machine.conf") in found


def test_scanner_rejects_source_reparse_point_without_following_it(
    tmp_path: Path, monkeypatch
) -> None:
    link = tmp_path / "linked.txt"
    link.write_text("safe", encoding="utf-8")
    monkeypatch.setattr(scanner, "_is_reparse_point", lambda path: path.name == "linked.txt")

    assert ("source_reparse_point", "linked.txt") in {
        (item.kind, item.path) for item in scan(tmp_path)
    }


def test_scanner_covers_python_json_xml_jwt_and_utf16(tmp_path: Path) -> None:
    opaque = "OpaquePokerCredential9876543210"
    jwt = "eyJ" + "A" * 12 + "." + "B" * 12 + "." + "C" * 12
    (tmp_path / "settings.py").write_text(
        f'POKER_API_TOKEN = "{opaque}"\n', encoding="utf-8"
    )
    (tmp_path / "settings.json").write_text(
        f'{{"POKER_API_TOKEN":"{opaque}"}}', encoding="utf-8"
    )
    (tmp_path / "settings.xml").write_text(
        f"<config><API_TOKEN>{opaque}</API_TOKEN></config>", encoding="utf-8"
    )
    (tmp_path / "authorization.md").write_text(f"Authorization: Bearer {jwt}", encoding="utf-8")
    (tmp_path / "windows.txt").write_text(
        f"POKER_API_TOKEN={opaque}\n", encoding="utf-16"
    )

    found = {(item.kind, item.path) for item in scan(tmp_path)}

    assert {
        ("credential_assignment", "settings.py"),
        ("credential_assignment", "settings.json"),
        ("credential_assignment", "settings.xml"),
        ("jwt_token", "authorization.md"),
        ("credential_assignment", "windows.txt"),
    } <= found


def test_scanner_fails_closed_for_oversized_text(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(scanner, "MAX_TEXT_BYTES", 16)
    (tmp_path / "large.txt").write_text("x" * 17, encoding="utf-8")

    assert [(item.kind, item.path) for item in scan(tmp_path)] == [
        ("oversized_text_unscanned", "large.txt")
    ]


def test_scanner_fails_closed_when_walk_cannot_read_directory(tmp_path: Path, monkeypatch) -> None:
    locked = tmp_path / "locked"

    def denied_walk(root, *, followlinks, onerror):
        assert root == tmp_path.resolve()
        assert followlinks is False
        onerror(PermissionError(13, "denied", str(locked)))
        return iter(())

    monkeypatch.setattr(scanner.os, "walk", denied_walk)

    assert [(item.kind, item.path) for item in scan(tmp_path)] == [
        ("unreadable_directory", "locked")
    ]


def test_main_never_echoes_secret_embedded_in_filename(tmp_path: Path, capsys) -> None:
    filename_secret = "hf_" + "F1l2E3n4A5m6E7S8e9C0r1E2"
    content_secret = "hf_" + "C1o2N3t4E5n6T7S8e9C0r1E2"
    (tmp_path / f"{filename_secret}.txt").write_text(content_secret, encoding="utf-8")

    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert filename_secret not in output
    assert content_secret not in output
    assert "path_sha256=" in output


def test_scanner_covers_short_provider_js_process_env_and_extensionless_sources(
    tmp_path: Path,
) -> None:
    cloudflare = "AbCd" + "EfGh1234"
    javascript = "JsCred" + "ential12"
    router = "Router" + "Key123"
    database = "postgresql://user:" + "password@db.invalid/app"
    (tmp_path / "Dockerfile").write_text(
        f"ENV CLOUDFLARE_API_TOKEN={cloudflare}\n", encoding="utf-8"
    )
    (tmp_path / "settings.js").write_text(
        f'const API_KEY = "{javascript}";\nprocess.env.OPENROUTER_API_KEY = "{router}";\n',
        encoding="utf-8",
    )
    (tmp_path / "Makefile").write_text(
        f"DATABASE_URL={database}\n", encoding="utf-8"
    )

    found = {(item.kind, item.path, item.line) for item in scan(tmp_path)}

    assert {
        ("credential_assignment", "Dockerfile", 1),
        ("credential_assignment", "settings.js", 1),
        ("credential_assignment", "Makefile", 1),
    } <= found
    assert len([item for item in found if item[1] == "settings.js"]) == 2


def test_scanner_does_not_waive_low_diversity_substrings_or_spoofed_binary_suffix(
    tmp_path: Path,
) -> None:
    repetitive = "T" * 32
    marker_substring = "prod-" + "example-company-credential-42"
    (tmp_path / "repetitive.conf").write_text(
        f"POKER_API_TOKEN={repetitive}\n", encoding="utf-8"
    )
    (tmp_path / "substring.conf").write_text(
        f"API_KEY={marker_substring}\n", encoding="utf-8"
    )
    (tmp_path / "renamed.png").write_text(
        f"CLOUDFLARE_API_TOKEN={repetitive}\n", encoding="utf-8"
    )
    (tmp_path / "real.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    found = {(item.kind, item.path) for item in scan(tmp_path)}

    assert ("credential_assignment", "repetitive.conf") in found
    assert ("credential_assignment", "substring.conf") in found
    assert ("credential_assignment", "renamed.png") in found
    assert all(path != "real.png" for _, path in found)
