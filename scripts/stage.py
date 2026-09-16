"""Prepare an allowlisted build bundle and reviewable commands; no cloud mutations."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED_INPUTS = (
    ".dockerignore", ".gcloudignore", "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml",
    "infra/Dockerfile", "infra/cloudbuild.yaml", "apps/web/package.json", "apps/web/index.html",
    "apps/web/tsconfig.json", "apps/web/tsconfig.app.json", "apps/web/tsconfig.node.json",
    "apps/web/vite.config.ts", "apps/api/pyproject.toml", "apps/api/uv.lock", "apps/api/README.md",
    "apps/api/src/newsroom_agent/snapshot_data/kosis-youth-employment-2020-2024.json",
    "apps/api/src/newsroom_agent/snapshot_data/opendart-samsung-revenue-2022-2024.json",
)
CONFIG_PATTERNS = {
    "account": r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "project": r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
    "region": r"[a-z]+-[a-z]+[0-9]+",
    "service": r"[a-z][a-z0-9-]{0,47}[a-z0-9]",
    "repository": r"[a-z][a-z0-9-]{0,47}[a-z0-9]",
    "runtime_service_account": r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
    "build_service_account": r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
    "access_secret": r"[a-z][a-z0-9-]{0,62}",
    "access_secret_version": r"[1-9][0-9]*",
}


def source_files(root: Path) -> list[Path]:
    selected = {Path(name) for name in FIXED_INPUTS}
    for directory, suffixes in (("apps/web/src", {".ts", ".tsx", ".css"}),
                                ("apps/api/src", {".py"})):
        for path in (root / directory).rglob("*"):
            relative = path.relative_to(root)
            if path.is_symlink():
                raise ValueError("Build source must not contain symlinks")
            if (path.suffix in suffixes and "test" not in relative.parts
                and not path.name.endswith((".test.ts", ".test.tsx"))):
                selected.add(relative)
    for relative in selected:
        path = root / relative
        if not path.is_file() or path.is_symlink() or root not in path.resolve().parents:
            raise ValueError("A required build input is missing or not a regular local file")
    return sorted(selected)


def prepare_source(root: Path, destination: Path) -> int:
    # Refuse overwrites: no rm -rf and no accidental mutation of a prior build bundle.
    if destination.exists():
        raise ValueError("Build destination already exists; use a new directory")
    paths = source_files(root)
    destination.mkdir(parents=True, exist_ok=False)
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
    return len(paths)


def load_config(path: Path) -> dict[str, str]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) != set(CONFIG_PATTERNS):
        raise ValueError("Use only the public fields from stage-config.example.json")
    for field, pattern in CONFIG_PATTERNS.items():
        if not isinstance(value[field], str) or not re.fullmatch(pattern, value[field]):
            raise ValueError(f"Invalid public configuration field: {field}")
    if value["runtime_service_account"] == value["build_service_account"]:
        raise ValueError("Build and runtime identities must be separate")
    return value


def commands(config: dict[str, str], source: str, tag: str, digest: str | None) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", tag):
        raise ValueError("Invalid image tag")
    if digest is not None and not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Deploy with an immutable sha256 image digest")
    project, region = config["project"], config["region"]
    image = f"{region}-docker.pkg.dev/{project}/{config['repository']}/newsroom-agent"
    runtime = f"{config['runtime_service_account']}@{project}.iam.gserviceaccount.com"
    builder = f"{config['build_service_account']}@{project}.iam.gserviceaccount.com"
    common = [f"--account={config['account']}", f"--project={project}", f"--region={region}"]
    build = ["gcloud", "builds", "submit", source, *common,
             "--config=infra/cloudbuild.yaml", "--ignore-file=.gcloudignore",
             f"--service-account=projects/{project}/serviceAccounts/{builder}",
             f"--gcs-source-staging-dir=gs://{project}-stage-build/source",
             f"--substitutions=_REGION={region},_REPOSITORY={config['repository']},_IMAGE_TAG={tag}"]
    deploy = None if digest is None else [
        "gcloud", "run", "deploy", config["service"], *common, f"--image={image}@{digest}",
        f"--service-account={runtime}", "--execution-environment=gen2", "--port=8080",
        "--cpu=1", "--memory=512Mi", "--concurrency=8", "--min=0", "--max-instances=1",
        "--cpu-throttling", "--no-cpu-boost", "--timeout=60s", "--ingress=all",
        "--no-allow-unauthenticated", "--env-vars-file=infra/stage.env.yaml",
        f"--set-secrets=WORKSHOP_ACCESS_CODE={config['access_secret']}:{config['access_secret_version']}",
        "--startup-probe=httpGet.path=/health,httpGet.port=8080,periodSeconds=10,failureThreshold=12,timeoutSeconds=2",
    ]
    return {"image_tag": f"{image}:{tag}", "runtime_identity": runtime, "build_identity": builder,
            "build": shlex.join(build), "deploy_private": shlex.join(deploy) if deploy else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    package = sub.add_parser("package", help="Copy only build inputs; never read .env")
    package.add_argument("--output", type=Path, required=True)
    plan = sub.add_parser("plan", help="Print commands only; never invoke gcloud")
    plan.add_argument("--config", type=Path, required=True)
    plan.add_argument("--source", default=".cache/stage-source")
    plan.add_argument("--tag", required=True)
    plan.add_argument("--image-digest")
    args = parser.parse_args()
    try:
        if args.action == "package":
            print(json.dumps({"build_files": prepare_source(ROOT, args.output)}))
        else:
            print(json.dumps(commands(load_config(args.config), args.source, args.tag,
                                      args.image_digest), indent=2))
    except (OSError, ValueError):
        parser.exit(1, "Stage preparation failed. Check public config and build input paths.\n")


if __name__ == "__main__":
    main()
