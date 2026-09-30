"""Offline checks for deploy inputs; never load cloud credentials or execute gcloud."""

import importlib.util
import json
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("stage_preparation", ROOT / "scripts/stage.py")
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


def build_fixture(tmp_path):
    root = tmp_path / "checkout"
    for name in stage.FIXED_INPUTS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("build input")
    for name in ("apps/web/src/App.tsx", "apps/web/src/styles.css",
                 "apps/api/src/newsroom_agent/main.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("public source")
    return root


def test_bundle_excludes_credentials_local_config_tests_and_caches(tmp_path):
    root = build_fixture(tmp_path)
    excluded = (
        ".env", ".env.local", ".git/config", ".gcloud/credentials.db",
        "infra/stage-config.local.json", "apps/web/.env.production", "apps/web/src/.env",
        "apps/web/src/service-account.json", "apps/api/src/credentials.json",
        "apps/api/src/local.pem", "apps/api/src/newsroom_agent/__pycache__/main.pyc",
        "apps/web/src/App.test.tsx", "apps/web/src/test/setup.ts", "apps/web/dist/bundle.js",
        "node_modules/package.json", "apps/api/.venv/secret.key",
    )
    for name in excluded:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private-value-must-not-leave-checkout")
    destination = tmp_path / "bundle"
    count = stage.prepare_source(root, destination)
    assert count == len(stage.FIXED_INPUTS) + 3
    assert all(not (destination / name).exists() for name in excluded)
    for path in destination.rglob("*"):
        if path.is_file():
            assert "private-value" not in path.read_text()


def test_bundle_rejects_symlink_to_private_file(tmp_path):
    root = build_fixture(tmp_path)
    secret = tmp_path / "private"
    secret.write_text("private-value")
    (root / "apps/web/src/leak.ts").symlink_to(secret)
    destination = tmp_path / "bundle"
    with pytest.raises(ValueError, match="symlink"):
        stage.prepare_source(root, destination)
    assert not destination.exists()


def test_missing_input_and_existing_destination_are_not_overwritten(tmp_path):
    root = build_fixture(tmp_path)
    destination = tmp_path / "bundle"
    (root / "infra/Dockerfile").unlink()
    with pytest.raises(ValueError):
        stage.prepare_source(root, destination)
    assert not destination.exists()
    destination.mkdir()
    (destination / "keep").write_text("existing")
    with pytest.raises(ValueError, match="already exists"):
        stage.prepare_source(root, destination)
    assert (destination / "keep").read_text() == "existing"


def test_config_and_commands_are_explicit_private_and_pinned():
    config = stage.load_config(ROOT / "infra/stage-config.example.json")
    digest = "sha256:" + "a" * 64
    result = stage.commands(config, ".cache/source with space", "test-image", digest)
    build = shlex.split(result["build"])
    deploy = shlex.split(result["deploy_private"])
    for command in (build, deploy):
        assert "--account=developer@example.com" in command
        assert "--project=your-stage-project" in command
        assert "--region=asia-northeast3" in command
    assert ".cache/source with space" in build
    assert result["runtime_identity"] != result["build_identity"]
    assert "--no-allow-unauthenticated" in deploy
    assert "--min=0" in deploy and "--max-instances=1" in deploy
    assert "--set-secrets=WORKSHOP_ACCESS_CODE=newsroom-workshop-code:1" in deploy
    assert any(arg.endswith("@" + digest) for arg in deploy)
    assert "--env-vars-file=infra/stage.env.yaml" in deploy
    assert "--cpu-throttling" in deploy
    assert stage.commands(config, ".cache/source", "test", None)["deploy_private"] is None


@pytest.mark.parametrize("change", [
    {"gemini_api_key": "private-value"}, {"access_secret_version": "latest"},
    {"project": "--other-project"}, {"account": "person@example.com; echo bad"},
    {"runtime_service_account": "newsroom-build"},
])
def test_config_rejects_secret_fields_unpinned_versions_and_invalid_targets(tmp_path, change):
    config = json.loads((ROOT / "infra/stage-config.example.json").read_text())
    config.update(change)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        stage.load_config(path)


@pytest.mark.parametrize("tag,digest", [("bad tag", None), ("test", "latest"),
                                        ("test", "sha256:123")])
def test_image_arguments_reject_mutable_or_malformed_references(tag, digest):
    config = stage.load_config(ROOT / "infra/stage-config.example.json")
    with pytest.raises(ValueError):
        stage.commands(config, ".cache/source", tag, digest)


def test_real_checkout_bundle_contains_runtime_and_web_inputs_only():
    files = stage.source_files(ROOT)
    assert Path("apps/web/src/App.tsx") in files
    assert Path("apps/api/src/newsroom_agent/main.py") in files
    assert Path("apps/api/src/newsroom_agent/operations.py") in files
    assert len([path for path in files if path.parent.name == "snapshot_data"]) == 2
    assert not any(path.name.startswith(".env") for path in files)


def test_stage_settings_keep_access_required_and_providers_off():
    # Restricted flat YAML, parsed without adding a deployment-only dependency.
    settings = dict(line.split(": ", 1) for line in (ROOT / "infra/stage.env.yaml")
                    .read_text().splitlines() if line and not line.startswith("#"))
    settings = {key: json.loads(value) for key, value in settings.items()}
    assert settings["APP_ENV"] == "stage"
    assert settings["PUBLIC_DATA_MODE"] == "mock"
    for key in ("LIVE_API_ENABLED", "GEMINI_PLANNER_ENABLED", "OPENDART_ENABLED", "KOSIS_ENABLED"):
        assert settings[key] == "false"
    assert settings["FALLBACK_SNAPSHOT_ENABLED"] == "true"
    assert not any("KEY" in key or "CODE" in key for key in settings)


def test_live_plan_pins_image_and_four_secrets_without_changing_public_access():
    config = stage.load_config(ROOT / "infra/stage-config.example.json")
    references = stage.load_provider_secrets(ROOT / "infra/stage-live-secrets.example.json")
    result = stage.live_commands(config, references, "sha256:" + "a" * 64,
                                 "live-test", "newsroom-stage-old")
    candidate = shlex.split(result["deploy_candidate"])
    assert "--no-traffic" in candidate and "--tag=live-check" in candidate
    assert "--concurrency=80" in candidate and "--timeout=210s" in candidate
    assert "--max-instances=1" in candidate
    assert "--env-vars-file=infra/stage-live.env.yaml" in candidate
    assert not any("unauthenticated" in arg for arg in candidate)
    identity = "newsroom-runtime@your-stage-project.iam.gserviceaccount.com"
    assert f"--service-account={identity}" in candidate
    bindings = next(arg for arg in candidate if arg.startswith("--set-secrets=")).split(",")
    assert len(bindings) == 4 and all(binding.endswith(":1") for binding in bindings)
    for name in ("deploy_candidate", "promote", "rollback"):
        args = shlex.split(result[name])
        assert "--account=developer@example.com" in args and "--region=asia-northeast3" in args
        assert "--project=your-stage-project" in args
    assert "--to-revisions=newsroom-stage-live-test=100" in shlex.split(result["promote"])
    assert "--to-revisions=newsroom-stage-old=100" in shlex.split(result["rollback"])
    assert "--remove-tags=live-check" in shlex.split(result["rollback"])


@pytest.mark.parametrize("mutation", ["extra", "missing", "latest", "value", "duplicate", "inject"])
def test_live_secret_references_reject_values_and_unsafe_names(tmp_path, mutation):
    value = json.loads((ROOT / "infra/stage-live-secrets.example.json").read_text())
    if mutation == "extra":
        value["OTHER_KEY"] = {"secret": "other", "version": "1"}
    elif mutation == "missing":
        del value["KOSIS_API_KEY"]
    elif mutation == "latest":
        value["GEMINI_API_KEY"]["version"] = "latest"
    elif mutation == "value":
        value["GEMINI_API_KEY"]["value"] = "must-not-be-a-key-value"
    elif mutation == "duplicate":
        value["KOSIS_API_KEY"] = value["OPENDART_API_KEY"]
    else:
        value["GEMINI_API_KEY"]["secret"] = "secret,OTHER=value"
    path = tmp_path / "refs.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        stage.load_provider_secrets(path)


@pytest.mark.parametrize("digest,suffix,rollback", [
    (None, "live-test", "newsroom-stage-old"),
    ("latest", "live-test", "newsroom-stage-old"),
    ("sha256:" + "a" * 64, "bad suffix", "newsroom-stage-old"),
    ("sha256:" + "a" * 64, "live-test", "different-service-old"),
    ("sha256:" + "a" * 64, "live-test", "newsroom-stage-live-test"),
])
def test_live_plan_rejects_unpinned_image_or_invalid_recovery(digest, suffix, rollback):
    config = stage.load_config(ROOT / "infra/stage-config.example.json")
    references = stage.load_provider_secrets(ROOT / "infra/stage-live-secrets.example.json")
    with pytest.raises(ValueError):
        stage.live_commands(config, references, digest, suffix, rollback)


def test_live_profile_is_separate_and_keeps_limits_snapshot_and_no_credentials():
    settings = dict(line.split(": ", 1) for line in (ROOT / "infra/stage-live.env.yaml")
                    .read_text().splitlines() if line and not line.startswith("#"))
    settings = {key: json.loads(value) for key, value in settings.items()}
    assert settings["APP_ENV"] == "stage" and settings["PUBLIC_DATA_MODE"] == "live"
    for key in ("LIVE_API_ENABLED", "GEMINI_PLANNER_ENABLED", "OPENDART_ENABLED", "KOSIS_ENABLED",
                "FALLBACK_SNAPSHOT_ENABLED", "PUBLIC_DATA_CACHE_ENABLED"):
        assert settings[key] == "true"
    assert settings["GEMINI_AUTH_MODE"] == "api_key"
    assert settings["REQUESTS_PER_MINUTE"] == settings["PUBLIC_DATA_REQUESTS_PER_MINUTE"] == "30"
    assert not any("KEY" in key or "CODE" in key for key in settings)
