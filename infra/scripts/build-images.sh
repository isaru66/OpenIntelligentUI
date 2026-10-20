#!/usr/bin/env bash
# Terraform reads this one-line JSON policy too. Keep regex syntax RE2/Python
# compatible. Patterns use Terraform fileset syntax (only literal paths and /**).
# CONTEXT_POLICY={"images":{"web":{"dockerfile":"docker/Dockerfile.app","patterns":["package.json","pnpm-lock.yaml","pnpm-workspace.yaml","turbo.json","patches/**","apps/app/package.json","apps/app/tsconfig.json","apps/app/next.config.ts","apps/app/postcss.config.mjs","apps/app/eslint.config.mjs","apps/app/src/**","apps/app/public/**","packages/design-system/package.json","packages/design-system/tsconfig.json","packages/design-system/src/**"]},"agent":{"dockerfile":"infra/Dockerfile.agent","patterns":["apps/agent/main.py","apps/agent/pyproject.toml","apps/agent/uv.lock","apps/agent/src/**","apps/agent/skills/**"]}},"allow":["apps/agent/src/credentials.py"],"exclude":"(?i)(^|/)([.][^/]+|node_modules|__pycache__|__pypackages__|env|venv|site-packages|caches?|coverage|htmlcov|dist|build|out|generated|__generated__|logs?|tmp|temp|tests?|__tests__|secrets?[^/]*|credentials?[^/]*|service[-_]account[^/]*|tfplan[^/]*|tfstate[^/]*|[^/]*[.](env[^/]*|tfstate[^/]*|tfplan[^/]*|tfvars[^/]*|plan[^/]*|pem|key|pfx|p12|crt|cer|log|pyc|pyo|tsbuildinfo|egg-info)|plan[.](json|bin|out)|state[.](json|bin)|env[.](json|yaml|yml)|[^/]*terraform[.-]?plan[^/]*|[^/]*[.]test[.][^/]*|[^/]*[.]spec[.][^/]*|terraform[.]rc|kubeconfig|id_rsa[^/]*|id_ed25519[^/]*|azureProfile[.]json|accessTokens[.]json|msal_token_cache[^/]*)(/|$)"}
set -euo pipefail

for tool in python3; do
  command -v "$tool" >/dev/null || { printf 'Required command missing: %s\n' "$tool" >&2; exit 1; }
done
exec python3 - "$0" "$@" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def fail(message):
    raise RuntimeError(message)


script = Path(sys.argv[1]).resolve()
policy = json.loads(re.search(r"^# CONTEXT_POLICY=(.+)$", script.read_text(), re.M)[1])
root = Path(os.environ.get("BUILD_ROOT", script.parents[2])).resolve()
image = os.environ.get("BUILD_IMAGE", "")
if image not in policy["images"]:
    fail("BUILD_IMAGE must be web or agent.")
config = policy["images"][image]
platform = os.environ.get("BUILD_PLATFORM", "linux/amd64")
if platform != "linux/amd64":
    fail("Only the declared linux/amd64 build platform is supported.")


def context_sources():
    candidates = set()
    for pattern in [*config["patterns"], config["dockerfile"]]:
        if pattern.endswith("/**"):
            candidates.update(p.relative_to(root).as_posix()
                              for p in (root / pattern[:-3]).rglob("*") if p.is_file())
        elif (root / pattern).is_file():
            candidates.add(pattern)
    sources = {}
    for name in sorted(candidates):
        if name not in policy["allow"] and re.search(policy["exclude"], name):
            continue
        if any(char in name for char in "\n\r\\:"):
            fail("Build context contains an unsupported filename.")
        path = root / name
        # Reject links including directory links into ignored/unrelated trees.
        if any(p.is_symlink() for p in [path, *path.parents] if p != root):
            fail(f"Symlinks are not allowed in the build context: {name}")
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    required = {
        "web": ["package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "turbo.json",
                "apps/app/package.json", "packages/design-system/package.json",
                "patches/fast-json-patch@3.1.1.patch"],
        "agent": ["apps/agent/main.py", "apps/agent/pyproject.toml", "apps/agent/uv.lock",
                  "apps/agent/src/credentials.py",
                  "apps/agent/src/db.csv",
                  "apps/agent/skills/advanced-visualization/SKILL.md",
                  "apps/agent/skills/master-playbook/SKILL.md",
                  "apps/agent/skills/svg-diagrams/SKILL.md"],
    }[image]
    for name in [config["dockerfile"], *required]:
        if name not in sources:
            fail(f"Required build input missing: {name}")
    return sources


def fingerprint(sources):
    parts = [platform, hashlib.sha256(script.read_bytes()).hexdigest(),
             hashlib.sha256((script.parent / "preflight.sh").read_bytes()).hexdigest()]
    parts.extend(f"{name}:{sources[name]}" for name in sorted(sources))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def cli_json(args, **kwargs):
    result = subprocess.run(["az", *args, "--subscription", subscription,
                             "--only-show-errors", "--output", "json"],
                            check=True, capture_output=True, text=True, **kwargs)
    return json.loads(result.stdout)


try:
    sources = context_sources()
    digest = fingerprint(sources)
    mode = sys.argv[2:] or ["--build"]
    if mode == ["--manifest"]:
        print(json.dumps(sources, sort_keys=True))
        sys.exit(0)
    if mode == ["--fingerprint"]:
        print(digest)
        sys.exit(0)
    if mode != ["--build"]:
        fail("Usage: build-images.sh [--build|--manifest|--fingerprint]")
    if not shutil.which("az") or not shutil.which("bash"):
        fail("Build requires az, bash and python3 on the same host.")
    if json.loads(os.environ["BUILD_SOURCES_JSON"]) != sources:
        fail("Build inputs changed since Terraform planned. Re-plan before building.")
    if os.environ["BUILD_FINGERPRINT"] != digest:
        fail("Build fingerprint differs from the plan. Re-plan before building.")
    subscription = os.environ["SUBSCRIPTION_ID"]
    registry = os.environ["REGISTRY_NAME"]
    if not re.fullmatch(r"[a-z0-9]{5,50}", registry):
        fail("Invalid REGISTRY_NAME.")
    reference = f"{image}:{digest}"
    # Use a private, short-lived directory, never the shared worktree itself.
    # No .dockerignore is staged: the files hashed are exactly the files sent.
    with tempfile.TemporaryDirectory(prefix="openui-acr-") as directory:
        staging = Path(directory)
        for name, expected in sources.items():
            data = (root / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                fail("Build input changed during staging. Re-plan before building.")
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            # Normalize modes, not host mtimes or executable permissions.
            target.chmod(0o644)
        subprocess.run(["bash", str(script.parent / "preflight.sh"), "--before-build"], check=True)
        print(f"Building {reference} remotely for {platform}.", flush=True)
        # --no-logs still waits, but its JSON status must be checked explicitly.
        # There is deliberately no retry here: it could duplicate a paid build.
        result = cli_json(["acr", "build", "--registry", registry,
                           "--file", config["dockerfile"], "--image", reference,
                           "--platform", platform, "--no-logs", "."], cwd=staging)
        if result.get("status") != "Succeeded":
            fail("ACR build did not succeed; inspect the run in ACR before retrying.")
        metadata = cli_json(["acr", "repository", "show", "--name", registry,
                             "--image", reference])
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", metadata.get("digest", "")):
            fail("ACR did not return the expected image manifest digest.")
        print(f"Verified {reference}.", flush=True)
except (RuntimeError, KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
    # Never echo the inherited environment, CLI output or credential-bearing
    # command lines. Azure CLI diagnostics can contain signed upload URLs.
    message = str(error) if isinstance(error, RuntimeError) else (
        "A build prerequisite/CLI operation failed. Check authentication, permissions "
        "and the ACR run; no fallback build was attempted.")
    print(f"Build failed: {message}", file=sys.stderr)
    sys.exit(1)
PY
