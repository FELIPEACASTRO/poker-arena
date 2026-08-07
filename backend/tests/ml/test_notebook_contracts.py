"""Static contracts for research notebooks.

These tests do not claim that an experiment was executed.  They prevent a class of
silent failures that previously made the recorded result irreproducible or unsafe:
unparseable notebooks, credential-bearing clone URLs, unpinned data, accidental
publication and model-name/checkpoint mismatches.
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
NOTEBOOK_DIR = REPO_ROOT / "ml" / "notebooks"
HF_REPO_NOTEBOOKS = (
    "03_train_ppo_selfplay.ipynb",
    "05_pokerbench_warmstart.ipynb",
    "06_selfplay_bb100.ipynb",
    "07_expert_v2_populacao.ipynb",
    "08_vision_agnostic.ipynb",
    "09_vision_finetune.ipynb",
)


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload.get("nbformat") == 4
    assert isinstance(payload.get("cells"), list)
    return payload


def _source(path: Path, *, cell_type: str | None = None) -> str:
    notebook = _load(path)
    cells = notebook["cells"]
    return "\n\n".join(
        "".join(cell.get("source", []))
        for cell in cells
        if cell_type is None or cell.get("cell_type") == cell_type
    )


def _without_ipython_magics(source: str) -> str:
    """Make line-oriented IPython magics inert before a syntax-only compile."""
    return "\n".join(
        "pass" if line.lstrip().startswith(("%", "!")) else line for line in source.splitlines()
    )


@pytest.mark.parametrize("path", sorted(NOTEBOOK_DIR.glob("*.ipynb")), ids=lambda p: p.name)
def test_every_notebook_is_valid_json_and_python(path: Path):
    code = _without_ipython_magics(_source(path, cell_type="code"))
    compile(code, str(path), "exec")


@pytest.mark.parametrize("path", sorted(NOTEBOOK_DIR.glob("*.ipynb")), ids=lambda p: p.name)
def test_notebooks_do_not_embed_credentials_in_urls_or_literal_tokens(path: Path):
    source = _source(path)
    assert re.search(r"https?://[^\s/@:]+:[^\s/@]+@", source) is None
    assert re.search(r"https?://\{[^}]+\}@", source) is None
    assert re.search(r"\b(?:hf_|ghp_|github_pat_)[A-Za-z0-9_-]{16,}\b", source) is None


@pytest.mark.parametrize("path", sorted(NOTEBOOK_DIR.glob("*.ipynb")), ids=lambda p: p.name)
def test_remote_notebooks_pin_private_source_and_require_upload_opt_in(path: Path):
    source = _source(path, cell_type="code")
    if "GH_TOKEN" in source:
        assert "PROJECT_COMMIT" in source
        assert "!git clone" not in source
        assert "git+https://{gh}@" not in source
    if "upload_file" in source:
        assert "POKER_PUBLISH_ARTIFACTS" in source


@pytest.mark.parametrize("name", HF_REPO_NOTEBOOKS)
def test_hf_model_repository_is_explicit_validated_and_not_personal(name: str):
    path = NOTEBOOK_DIR / name
    code = _source(path, cell_type="code")

    assert "HF_MODEL" not in code
    assert "HF_REPO_ID" in code
    assert re.search(r"HF_REPO_ID\s*=\s*['\"]", code) is None
    assert "userdata.get('HF_REPO_ID')" in code or 'userdata.get("HF_REPO_ID")' in code
    assert "HF_REPO_ID_PATTERN" in code
    assert "HF_REPO_ID.isascii()" in code
    assert "len(HF_REPO_ID) > 96" in code
    assert "re.fullmatch(HF_REPO_ID_PATTERN, HF_REPO_ID) is None" in code
    assert "'..' in HF_REPO_ID" in code and "'--' in HF_REPO_ID" in code

    tree = ast.parse(_without_ipython_magics(code), filename=str(path))
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "HF_REPO_ID" for target in node.targets
        )
    ]
    assert assignments
    for assignment in assignments:
        literal_values = {
            node.value
            for node in ast.walk(assignment.value)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert not any(
            re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", value) for value in literal_values
        )

    validation = code.index("HF_REPO_ID deve ser ASCII owner/repo canonico.")
    for remote_call in ("hf_hub_download(", "api.create_repo(", "api.upload_file("):
        positions = [match.start() for match in re.finditer(re.escape(remote_call), code)]
        assert all(validation < position for position in positions)

    if "api.create_repo(" in code:
        assert "api.create_repo(HF_REPO_ID" in code
    if "api.upload_file(" in code:
        assert "repo_id=HF_REPO_ID" in code
    if name in {"07_expert_v2_populacao.ipynb", "09_vision_finetune.ipynb"}:
        assert re.search(r"hf_hub_download\(\s*HF_REPO_ID", code)


@pytest.mark.parametrize(
    "name",
    [
        "03_train_ppo_selfplay.ipynb",
        "05_pokerbench_warmstart.ipynb",
        "06_selfplay_bb100.ipynb",
    ],
)
def test_rejected_historical_training_notebooks_fail_before_side_effects(name: str):
    source = _source(NOTEBOOK_DIR / name, cell_type="code")
    assert "ARCHIVED_NOTEBOOK = True" in source
    block = source.index("raise RuntimeError('ARQUIVADO:")
    assert block < source.index("userdata")
    assert block < source.index("upload_file")
    assert "os.environ['HF_TOKEN']" not in source
    assert "'PIP_CONFIG_FILE': os.devnull" in source
    assert source.index("'pip', 'install'") < source.index("hf_token = userdata.get('HF_TOKEN')")
    assert "stable-baselines3==2.7.0" in source
    assert "huggingface_hub==0.34.3" in source


@pytest.mark.parametrize(
    "name",
    [
        "01_kuhn_cfr_convergence.ipynb",
        "01_kuhn_cfr_single_cell.ipynb",
        "02_nfsp_leduc_single_cell.ipynb",
    ],
)
def test_active_open_spiel_notebooks_use_one_exact_compatible_pin(name: str):
    source = _source(NOTEBOOK_DIR / name, cell_type="code")

    assert "!pip install -q open_spiel==1.6.15" in source
    assert "!pip install -q open_spiel\n" not in source
    assert "receipt de hashes transitivos ainda externo" in source


def test_population_notebook_is_pinned_stratified_and_fail_closed():
    source = _source(NOTEBOOK_DIR / "07_expert_v2_populacao.ipynb", cell_type="code")
    assert "DATA_COMMIT = 'e2ec038d31a1a46a82d147db4bbfdb0910459705'" in source
    assert "DATA_TREE = 'a1c33bedd561407860b2467bffb4257317e9d6ce'" in source
    assert "if tree_payload.get('truncated') is not False:" in source
    assert "git_blob_sha1" in source
    assert "setdefault(" not in source
    assert "if owe > 0" in source
    assert "POKER_PUBLISH_ARTIFACTS" in source
    assert "PROJECT_COMMIT" in source and "HF_BASELINE_REVISION" in source
    assert "re.fullmatch(r'[0-9a-f]{40}', PROJECT_COMMIT)" in source
    assert "re.fullmatch(r'[0-9a-f]{40}', HF_BASELINE_REVISION)" in source
    assert "[0-9a-fA-F]{40}" not in source
    assert "if not HF_BASELINE_REVISION" not in source
    assert "BASELINE_MANIFEST_FILENAME = 'MANIFEST.json'" in source
    assert "revision=HF_BASELINE_REVISION" in source
    assert "baseline_artifact = verify_model_artifact" in source
    assert source.index("baseline_artifact = verify_model_artifact") < source.index("model.learn")
    assert "os.environ['HF_TOKEN']" not in source
    assert "sensitive_env_name.search(inherited_name)" in source
    assert "'status', '--porcelain', '--untracked-files=all'" in source
    assert "'PIP_CONFIG_FILE': os.devnull" in source
    assert source.index("'pip', 'install'") < source.index("hf_token = userdata.get('HF_TOKEN')")
    assert source.index("hf_token = ''") < source.index("model.learn")
    assert "del basic, clone_env, gh" not in source
    assert "github_session.trust_env = False" in source
    assert "response.request.headers.pop('Authorization', None)" in source
    assert source.index("HDRS = {'Authorization': f'Bearer {gh}'") < source.index("gh = ''")
    assert source.index("gh = ''") < source.index("for stratum, item in phh_items")
    assert "PHH_PLAYER_HASH_KEY = bytearray(" in source
    assert "PHH_PLAYER_HASH_KEY[key_index] = 0" in source
    assert source.index("PHH_PLAYER_HASH_KEY[key_index] = 0") < source.index("model.learn")
    for governance_input in (
        "POKER_CANDIDATE_LICENSE_ID",
        "POKER_CANDIDATE_LICENSE_REFERENCE",
        "POKER_CANDIDATE_LINEAGE_ID",
        "POKER_CANDIDATE_LINEAGE_REFERENCE",
    ):
        assert governance_input in source
        assert source.index(governance_input) < source.index("model.learn")
    for phh_governance_input in (
        "POKER_PHH_GOVERNANCE_REVIEW_ID",
        "POKER_PHH_LICENSE_ID",
        "POKER_PHH_LICENSE_STATUS",
        "POKER_PHH_LICENSE_REFERENCE",
        "POKER_PHH_ORIGIN_STATUS",
        "POKER_PHH_ORIGIN_REFERENCE",
        "POKER_PHH_TERMS_STATUS",
        "POKER_PHH_TERMS_REFERENCE",
        "POKER_PHH_TEMPORAL_POLICY_REFERENCE",
        "POKER_PHH_REAL_MONEY",
        "POKER_PHH_PERMITTED_USE",
    ):
        assert phh_governance_input in source
        assert source.index(phh_governance_input) < source.index("model.learn")
    assert "PHH_LICENSE_STATUS != 'verified'" in source
    assert "PHH_ORIGIN_STATUS != 'verified'" in source
    assert "PHH_TERMS_STATUS != 'reviewed-compatible'" in source
    assert "PHH_REAL_MONEY != 'false'" in source
    assert "PHH_PERMITTED_USE != 'model-training'" in source
    assert "'contract': 'poker-arena.phh-corpus-governance/v1'" in source
    assert "'unit_of_analysis': 'multiplayer-hand'" in source
    assert "'real_money': False, 'permitted_use': ['model-training']" in source
    assert "'validated': False" in source
    assert "not representable without falsifying entity-per-file semantics" in source
    assert "phh_corpus_governance_receipt.json" in source
    assert "phh_corpus_governance_receipt_sha256" in source
    assert "require_operator_governance" in source
    assert "port in (None, 443) and not parsed.query and not parsed.fragment" in source
    assert "parsed.path not in ('', '/')" in source
    assert "'state': 'candidate'" in source
    assert "'status': 'verified'" in source
    assert "candidate_artifact = verify_evaluation_candidate" in source
    assert "v2 = battery(EvaluationMLBot, V2_PATH, V2_MANIFEST_PATH, GATE_SEEDS)" in source
    assert "v1 = battery(MLBot, V1_PATH, V1_MANIFEST_PATH, GATE_SEEDS)" in source
    assert "candidate_manifest_sha256" in source and "baseline_manifest_sha256" in source
    assert "path_in_repo=f'{candidate_root}/MANIFEST.json'" in source
    assert "MLBot(V2_PATH" not in source
    assert "paired_bootstrap" in source
    assert "bonferroni" in source.lower()
    assert "GATE_REQUIRED_BLOCKS = 30" in source
    assert "POKER_GATE_POWER_ANALYSIS_ID" in source
    assert "POKER_GATE_MDE_BB100" in source
    assert "POKER_GATE_NONINFERIORITY_MARGIN_BB100" in source
    assert "POKER_GATE_CONTROL_EQUIVALENCE_MARGIN_BB100" in source
    assert "'preregistered_design': preregistered_design" in source
    assert "'baseline_seed_panel_stable'" in source
    assert "control_low >= -GATE_CONTROL_EQUIVALENCE_MARGIN_BB100" in source
    assert "control_high <= GATE_CONTROL_EQUIVALENCE_MARGIN_BB100" in source
    assert "family_size = len(GATE) + 2" in source
    assert "'family_size': family_size" in source
    assert "'family_members': [*GATE.keys(), 'aggregate', 'stability_control']" in source
    assert "aggregate_blocks, simultaneous_confidence" in source
    assert "'simultaneous_ci': [agg_low, agg_high]" in source
    assert "CONTROL_SEEDS = tuple(range(20_000, 20_030))" in source
    assert "set(GATE_SEEDS).isdisjoint(CONTROL_SEEDS)" in source
    assert "CHECKPOINT_SELECTION_SEEDS = tuple(range(30_000, 30_005))" in source
    assert "set(CHECKPOINT_SELECTION_SEEDS).isdisjoint(GATE_SEEDS)" in source
    assert "set(CHECKPOINT_SELECTION_SEEDS).isdisjoint(CONTROL_SEEDS)" in source
    assert "TRAINING_SEED = 20260717" in source
    assert "torch.use_deterministic_algorithms(True)" in source
    assert "seed=TRAINING_SEED" in source
    assert "start_method='spawn'" in source
    assert "start_method='fork'" not in source
    assert "self._np_rng.choice" in source
    assert "np.random.choice" not in source
    assert "pool_rng.sample" in source and "pool_rng.shuffle" in source
    assert "random.sample" not in source and "random.shuffle" not in source
    assert "villain_rng = random.Random(seed ^ 0x5EED5EED5EED5EED)" in source
    assert "if not resolved:" in source
    assert "mao nao resolveu dentro do limite de transicoes" in source
    assert "v2_source = Path('best_pool.onnx')" in source
    assert "else 'expert_v2.onnx'" not in source
    assert "best_pool_receipt.json" in source
    assert "artifact_sha256" in source
    assert "checkpoint_selection_receipt_sha256" in source
    assert "v1_control_repeat" not in source
    assert "assert " not in source
    assert "'precision_supports_mde'" in source
    assert "NONINFERIOR_MARGIN = 5.0" not in source
    assert "path_in_repo='poker_expert.onnx'" not in source
    assert "hf_publish_receipt.json" in source
    assert "artifact_commit.oid" in source
    assert "PLAYER_IDENTITY_SCHEME = 'hmac-sha256'" in source
    assert "PHH_PLAYER_HASH_KEY" in source and "PLAYER_IDENTITY_KEY_VERSION" in source
    assert "PLAYER_IDENTITY_SEPARATION_CONTEXT" in source
    assert "r'kv-[A-Za-z0-9][A-Za-z0-9._-]{2,62}'" in source
    assert "PLAYER_IDENTITY_PURPOSE = 'split-leakage-prevention'" in source
    assert "PHH_TIME_ZONE_MAP_JSON" in source
    assert "['hashed_player_id', 'event_time', 'session', 'split_group']" in source
    assert "player-session-connected-components-temporal-v1" in source
    assert "strict_temporal_order" in source and "overlap_counts" in source
    assert "if record['split'] != 'train':" in source
    assert "'prior_fit_split': 'train'" in source
    assert "phh_split_receipt.json" in source and "assignment_sha256" in source
    assert "no filename, mtime, sequence, or synthetic-date fallback" in source


def test_vision_notebook_keeps_architecture_artifacts_and_claims_aligned():
    path = NOTEBOOK_DIR / "08_vision_agnostic.ipynb"
    code = _source(path, cell_type="code")
    prose = _source(path, cell_type="markdown")
    assert 'ARCH = "yolo11n"' in code
    assert "ULTRALYTICS_VERSION = '8.3.223'" in code
    assert "ultralytics=={ULTRALYTICS_VERSION}" in code
    assert "BASE_WEIGHTS_SHA256" in code
    assert "hashlib.sha256(BASE_WEIGHTS_PATH.read_bytes()).hexdigest()" in code
    assert "model = YOLO(str(BASE_WEIGHTS_PATH))" in code
    assert 'YOLO(f"{ARCH}.pt")' not in code
    assert "shutil.rmtree(ROOT)" in code
    assert "torch.use_deterministic_algorithms(True)" in code
    assert "dataset_inventory_sha256" in code
    assert "candidate_dir = ROOT / 'candidates' / onnx_sha256" in code
    assert "remote_dir = f'candidates/{onnx_sha256}'" in code
    assert "commit.oid" in code and "hf_publish_receipt.json" in code
    assert "canonical_updated': False" in code
    assert 'YOLO("yolo11s.pt")' not in code
    assert "hash(split)" not in code
    assert 'POKER_PUBLISH_ARTIFACTS") == "1"' in code
    assert '"real_world_validated": False' in code
    assert code.index("if PUBLISH_ARTIFACTS:") < code.index("api.upload_file")
    assert "não demonstra" in prose
    assert "não prova" in prose


def test_real_finetune_is_grouped_pinned_and_never_promotes_directly():
    path = NOTEBOOK_DIR / "09_vision_finetune.ipynb"
    code = _source(path, cell_type="code")
    prose = _source(path, cell_type="markdown")
    assert "HF_BASELINE_REVISION" in code
    assert "revision=HF_BASELINE_REVISION" in code
    assert "re.fullmatch(r'[0-9a-f]{40}', HF_BASELINE_REVISION)" in code
    assert "ULTRALYTICS_VERSION = '8.3.223'" in code
    assert "PROJECT_COMMIT" in code and "resolved_project_commit" in code
    assert "'status', '--porcelain', '--untracked-files=all'" in code
    assert "'PIP_CONFIG_FILE': os.devnull" in code
    assert "os.environ.pop('HF_TOKEN', None)" in code
    assert "sensitive_env_name.search(inherited_name)" in code
    assert code.index("baseline_auth_value = ''") < code.index("ft.train(")
    assert "shutil.rmtree(ROOT)" in code
    assert "torch.use_deterministic_algorithms(True)" in code
    assert "validate_manifest(" in code
    assert "requested_use='model-training'" in code
    assert "sample['split']" in code and "sample['split_group']" in code
    assert 'os.path.basename(p).split("_")[0]' not in code
    assert "validate_yolo_label" in code
    assert "difference_hash" in code and ".bit_count() <= 4" in code
    assert "real_data_receipt.json" in code
    assert "real_data_receipt_sha256" in code
    assert "manifest_receipt.as_dict()" in code
    assert "hf_publish_receipt.json" in code and "commit.oid" in code
    assert 'POKER_PUBLISH_ARTIFACTS") == "1"' in code
    assert "len(srcs) < 4" in code
    assert "real_image_stems != real_label_stems" in code
    assert "per_class_floor_pass" in code
    assert "candidates/" in code
    assert "poker_vision.onnx" not in code
    assert "<200" not in prose
    assert "~99%" not in prose


def test_card_reader_notebook_is_deterministic_parity_checked_and_candidate_only():
    path = NOTEBOOK_DIR / "11_card_reader_cnn.ipynb"
    code = _source(path, cell_type="code")
    prose = _source(path, cell_type="markdown")
    assert "FONTTOOLS_VERSION = '4.59.0'" in code
    assert "ONNX_VERSION = '1.18.0'" in code
    assert "ONNXRUNTIME_VERSION = '1.27.0'" in code
    assert "check=True" in code and "check=False" not in code
    assert "POKER_EXPECTED_TORCH_VERSION" in code
    assert "torch.manual_seed(SEED)" in code
    assert "torch.use_deterministic_algorithms(True)" in code
    assert "num_workers=0" in code and "generator=train_generator" in code
    assert "or _FONTS[:1]" not in code
    assert "set(FONTS_TR) & set(FONTS_VA)" in code
    assert "best_checkpoint" in code and "best_card_accuracy" in code
    assert "paridade logits PyTorch/ONNX" in code
    assert "for xb, rb, sb in va:" in code
    assert "candidate_dir = ROOT / 'candidates' / artifact_sha256" in code
    assert "'state': 'candidate'" in code
    assert "MANIFEST.json" in code and "training_receipt.json" in code
    assert "real_world_validated': False" in code
    assert 'files.download("card_reader.onnx")' not in code
    assert "coloque em **`backend/models/`**" not in prose
    assert "canônico" in prose.lower()


def test_remote_vlm_notebook_is_pinned_authenticated_and_has_no_quick_tunnel():
    path = NOTEBOOK_DIR / "10_vlm_server_colab.ipynb"
    source = _source(path)
    code = _source(path, cell_type="code")

    assert "LLAMA_CPP_COMMIT = '86a9c79f866799eb0e7e89c03578ccfbcc5d808e'" in code
    assert "MODEL_REVISION = '00c00da0690c4b14b5539b02c4ea5d7c9102b35e'" in code
    assert "MODEL_FILENAME = 'Qwen3-VL-4B-Instruct-Q4_K_M.gguf'" in code
    assert (
        "MODEL_SHA256 = 'd4dcd426bfba75752a312b266b80fec8136fbaca13c62d93b7ac41fa67f0492b'" in code
    )
    assert "MMPROJ_FILENAME = 'mmproj-F16.gguf'" in code
    assert (
        "MMPROJ_SHA256 = '1b9f4e92f0fbda14d7d7b58baed86039b8a980fe503d9d6a9393f25c0028f1fc'" in code
    )
    assert "CLOUDFLARED_VERSION = '2026.5.2'" in code
    assert (
        "CLOUDFLARED_SHA256 = '5286698547f03df745adb2355f04c12dde52ef425491e81f433642d695521886'"
        in code
    )
    assert "_download_verified" in code and "actual != expected_sha256" in code
    assert "checkout', '--detach', LLAMA_CPP_COMMIT" in code
    assert "poker-llama-source-" in code
    assert "'status', '--porcelain', '--untracked-files=all'" in code
    assert "build_marker" not in code
    assert code.index("server_build_sha256 = _sha256(server_binary)") < code.index(
        "api_token = _required_secret('POKER_VLM_API_TOKEN')"
    )
    assert "LLAMA_API_KEY" in code and "TUNNEL_TOKEN" in code
    assert "CLOUDFLARE_TUNNEL_TOKEN" in code and "POKER_VLM_API_TOKEN" in code
    assert "POKER_VLM_PUBLIC_BASE_URL" in code and "POKER_VLM_ALLOWED_HOSTS" in code
    assert "POKER_VLM_REDACT_REGIONS" in code and "--no-cache-prompt" in code
    assert "releases/latest" not in source
    assert "trycloudflare.com" not in source
    assert "files.upload" not in source
    assert "-hf" not in code
    assert ":Q4_K_M" not in code


def test_remote_vlm_process_lifecycle_is_bounded_isolated_and_fail_safe():
    code = _source(NOTEBOOK_DIR / "10_vlm_server_colab.ipynb", cell_type="code")

    lifecycle_try = code.index("try:\n    runtime_dir = Path(tempfile.mkdtemp(")
    lifecycle_finally = code.index("\nfinally:\n", lifecycle_try)
    popen_positions = [match.start() for match in re.finditer(r"subprocess\.Popen\(", code)]
    assert len(popen_positions) == 2
    assert all(lifecycle_try < position < lifecycle_finally for position in popen_positions)
    assert lifecycle_try < code.index("_wait_health(server,") < lifecycle_finally
    assert lifecycle_try < code.index("_wait_process_stable(tunnel,") < lifecycle_finally
    assert code.index("_cleanup_runtime(processes, log_handles, runtime_dir)") > lifecycle_finally

    assert "os.environ.copy()" not in code
    assert "PROCESS_ENV_ALLOWLIST" in code and "_minimal_process_env" in code
    assert "check=True, env=tool_env" in code
    assert "server_env = _minimal_process_env({'LLAMA_API_KEY': api_token})" in code
    assert "tunnel_env = _minimal_process_env({'TUNNEL_TOKEN': tunnel_token})" in code
    assert "server_env.pop('LLAMA_API_KEY', None)" in code
    assert "tunnel_env.pop('TUNNEL_TOKEN', None)" in code
    assert code.index("api_token = ''", lifecycle_try) < code.index("_wait_health(server,")
    assert code.index("tunnel_token = ''", lifecycle_try) < code.index(
        "_wait_process_stable(tunnel,"
    )

    assert code.count("stdout=subprocess.DEVNULL") == 2
    assert code.count("stderr=subprocess.DEVNULL") == 2
    assert code.count("stdin=subprocess.DEVNULL") == 2
    assert "subprocess.STDOUT" not in code
    assert "server.log" not in code and "tunnel.log" not in code
    assert "STATUS_LOG_LIMIT_BYTES = 4096" in code
    assert "runtime_dir / 'lifecycle.log'" in code
    assert "shutil.rmtree(runtime_dir, ignore_errors=True)" in code
    assert "shutil.rmtree(llama_workspace, ignore_errors=True)" in code
    assert set(re.findall(r"_write_status\([^,]+, '([^']+)'\)", code)) == {
        "server_started",
        "server_healthy",
        "tunnel_started",
        "tunnel_stable",
        "cleanup_started",
    }

    assert "process.terminate()" in code
    assert "process.wait(timeout=10)" in code
    assert "process.kill()" in code
    assert "process.wait(timeout=5)" in code
    assert "if stream is not None and not stream.closed:" in code
    assert "handle.close()" in code


def test_remote_vlm_cleanup_helper_is_idempotent_and_kills_after_timeout(tmp_path: Path):
    code = _source(NOTEBOOK_DIR / "10_vlm_server_colab.ipynb", cell_type="code")
    helper_source = code[code.index("def _stop_process") : code.index("\n\nprocesses: list[")]
    namespace = {"Path": Path, "shutil": shutil, "subprocess": subprocess}
    exec(  # noqa: S102 - execute only a sliced, repository-controlled helper in an isolated namespace
        compile("from __future__ import annotations\n" + helper_source, "<vlm-cleanup>", "exec"),
        namespace,
    )

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = io.StringIO()
            self.stdout = io.StringIO()
            self.stderr = io.StringIO()
            self.terminated = 0
            self.killed = 0
            self.wait_timeouts: list[int] = []

        def poll(self) -> int | None:
            return -9 if self.killed else None

        def terminate(self) -> None:
            self.terminated += 1

        def kill(self) -> None:
            self.killed += 1

        def wait(self, timeout: int) -> int:
            self.wait_timeouts.append(timeout)
            if not self.killed:
                raise subprocess.TimeoutExpired("fake", timeout)
            return -9

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    lifecycle_handle = (runtime_dir / "lifecycle.log").open("w", encoding="ascii")
    process = FakeProcess()
    cleanup = namespace["_cleanup_runtime"]

    cleanup([process], [lifecycle_handle], runtime_dir)
    cleanup([process], [lifecycle_handle], runtime_dir)

    assert process.terminated == 1
    assert process.killed == 1
    assert process.wait_timeouts == [10, 5, 1]
    assert process.stdin.closed and process.stdout.closed and process.stderr.closed
    assert lifecycle_handle.closed
    assert not runtime_dir.exists()


def test_remote_vlm_minimal_env_and_status_log_do_not_inherit_or_record_secrets(
    monkeypatch: pytest.MonkeyPatch,
):
    code = _source(NOTEBOOK_DIR / "10_vlm_server_colab.ipynb", cell_type="code")
    helper_source = code[code.index("PROCESS_ENV_ALLOWLIST =") : code.index("def _wait_health")]
    namespace = {"os": os}
    exec(  # noqa: S102 - execute only a sliced, repository-controlled helper in an isolated namespace
        compile("from __future__ import annotations\n" + helper_source, "<vlm-env>", "exec"),
        namespace,
    )
    monkeypatch.setenv("HF_TOKEN", "must-not-be-inherited")
    monkeypatch.setenv("KAGGLE_KEY", "must-not-be-inherited")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-be-inherited")

    env = namespace["_minimal_process_env"]({"LLAMA_API_KEY": "process-only-secret"})
    allowed = set(namespace["PROCESS_ENV_ALLOWLIST"]) | {"LLAMA_API_KEY"}
    assert set(env) <= allowed
    assert env["LLAMA_API_KEY"] == "process-only-secret"
    assert {"HF_TOKEN", "KAGGLE_KEY", "UNRELATED_SECRET"}.isdisjoint(env)

    status_log = io.StringIO()
    write_status = namespace["_write_status"]
    with pytest.raises(ValueError, match="não permitido"):
        write_status(status_log, "prompt=secret-token")
    for _ in range(1000):
        write_status(status_log, "server_started")
    assert len(status_log.getvalue().encode("ascii")) <= namespace["STATUS_LOG_LIMIT_BYTES"]
    assert "secret-token" not in status_log.getvalue()
