"""Local-only build/context tests. All Azure operations use an executable mock.

Run from WSL at the repository root:
    python3 -m unittest discover -s infra/tests -p 'test_acr_builds.py' -v
No Docker daemon, provider credentials, network, or third-party packages required.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/scripts/build-images.sh"
PREFLIGHT = ROOT / "infra/scripts/preflight.sh"
POLICY = json.loads(re.search(r"^# CONTEXT_POLICY=(.+)$", SCRIPT.read_text(), re.M)[1])
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
REGISTRY_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-test/providers/Microsoft.ContainerRegistry/registries/acrtest"
ACCOUNT_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-test/providers/Microsoft.CognitiveServices/accounts/ai-test"


# This mock deliberately records CLI arguments and staged filenames, NEVER the
# real process environment. Test values below are synthetic, not user secrets.
MOCK_AZ = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
args = sys.argv[1:]
with open(os.environ["MOCK_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
assert args[args.index("--subscription") + 1] == os.environ["SUBSCRIPTION_ID"]
def emit(value):
    print(json.dumps(value))
def model(label):
    if label == "chat":
        return {"format": "OpenAI", "name": os.environ["CHAT_MODEL_NAME"],
                "version": os.environ["CHAT_MODEL_VERSION"]}
    return {"format": "Microsoft", "name": "Microsoft-Decision-1", "version": "1"}
scenario = os.environ.get("MOCK_SCENARIO", "")
if args[:2] == ["account", "show"]:
    emit({"id": os.environ["SUBSCRIPTION_ID"], "state": "Disabled" if scenario == "disabled" else "Enabled"})
elif args[:3] == ["cognitiveservices", "model", "list"]:
    models = []
    for label in ("chat", "decision"):
        m = model(label)
        m["skus"] = [{"name": os.environ[label.upper() + "_DEPLOYMENT_SKU"],
                      "usageName": label, "capacity": {"minimum": 1, "maximum": 10, "step": 1}}]
        models.append({"model": m})
    emit([] if scenario == "missing-model" else models)
elif args[:3] == ["cognitiveservices", "usage", "list"]:
    emit([{"name": {"value": label}, "limit": 10 if scenario == "available-quota" else 1,
           "currentValue": 2 if scenario == "over-quota" else 1}
          for label in ("chat", "decision")])
elif args[:2] == ["acr", "show"]:
    emit({"id": os.environ["REGISTRY_ID"], "provisioningState": "Succeeded",
          "adminUserEnabled": False, "publicNetworkAccess": "Enabled"})
elif args[:2] == ["rest", "--method"]:
    url = args[args.index("--url") + 1]
    if "/Microsoft.Authorization/permissions" in url:
        calls = sum("Microsoft.Authorization/permissions" in line
                    for line in Path(os.environ["MOCK_LOG"]).read_text().splitlines())
        denied = scenario == "permissions" or (scenario == "propagation" and calls <= 2)
        emit({"value": [{"actions": [] if denied else ["*"], "notActions": []}]})
    else:
        label = "chat" if "/deployments/chat?" in url else "decision"
        emit({"properties": {"provisioningState": "Failed" if scenario == "deployment" else "Succeeded",
                              "model": model(label)},
              "sku": {"name": os.environ[label.upper() + "_DEPLOYMENT_SKU"], "capacity": 1}})
elif args[:3] == ["acr", "repository", "list"]:
    emit([])
elif args[:2] == ["acr", "build"]:
    files = sorted(str(p.relative_to(Path.cwd())) for p in Path.cwd().rglob("*") if p.is_file())
    Path(os.environ["MOCK_CONTEXT"]).write_text(json.dumps(files))
    assert args[args.index("--platform") + 1] == "linux/amd64"
    assert Path(args[args.index("--file") + 1]).is_file()
    assert "--no-wait" not in args and "--no-push" not in args
    assert "--build-arg" not in args and "--secret-build-arg" not in args
    assert "--no-logs" in args
    if scenario == "build-exit":
        print("synthetic-sensitive-output", file=sys.stderr)
        sys.exit(9)
    emit({"status": "Failed" if scenario == "build-status" else "Succeeded"})
elif args[:3] == ["acr", "repository", "show"]:
    emit({"digest": "" if scenario == "missing-image" else "sha256:" + "a" * 64})
else:
    raise AssertionError("Unexpected Azure CLI command")
'''


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="openui-build-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source with spaces"
        self.root.mkdir()
        for image, config in POLICY["images"].items():
            files = [config["dockerfile"]]
            files += ({
                "web": ["package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "turbo.json",
                        "apps/app/package.json", "apps/app/src/index.ts",
                        "packages/design-system/package.json", "packages/design-system/src/index.ts",
                        "patches/fast-json-patch@3.1.1.patch"],
                "agent": ["apps/agent/main.py", "apps/agent/pyproject.toml", "apps/agent/uv.lock",
                          "apps/agent/src/db.csv", "apps/agent/src/plan.py", "apps/agent/src/credentials.py",
                          "apps/agent/skills/advanced-visualization/SKILL.md",
                          "apps/agent/skills/master-playbook/SKILL.md",
                          "apps/agent/skills/svg-diagrams/SKILL.md"],
            }[image])
            for name in files:
                self.write(name, "test input\n")
        self.bin = Path(self.temporary.name) / "bin"
        self.bin.mkdir()
        mock = self.bin / "az"
        mock.write_text(MOCK_AZ)
        mock.chmod(0o755)
        # No cloud-capable real executables are used by the tests.
        for command in ("azd", "terraform"):
            stub = self.bin / command
            stub.write_text("#!/bin/sh\nexit 0\n")
            stub.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "BUILD_ROOT": str(self.root), "BUILD_IMAGE": "agent", "BUILD_PLATFORM": "linux/amd64",
            "SUBSCRIPTION_ID": SUBSCRIPTION, "REGISTRY_NAME": "acrtest", "REGISTRY_ID": REGISTRY_ID,
            "FOUNDRY_LOCATION": "eastus2", "CHAT_MODEL_NAME": "gpt-6-luna",
            "CHAT_MODEL_VERSION": "exact-test-version", "CHAT_DEPLOYMENT_SKU": "GlobalStandard",
            "CHAT_DEPLOYMENT_CAPACITY": "1", "DECISION_DEPLOYMENT_SKU": "GlobalStandard",
            "DECISION_DEPLOYMENT_CAPACITY": "1",
            "CHAT_DEPLOYMENT_ID": ACCOUNT_ID + "/deployments/chat",
            "DECISION_DEPLOYMENT_ID": ACCOUNT_ID + "/deployments/decision",
            "MOCK_LOG": str(Path(self.temporary.name) / "cli-log"),
            "MOCK_CONTEXT": str(Path(self.temporary.name) / "staged-files"),
            "WEBIQ_API_KEY": "synthetic-sensitive-output",
        }

    def write(self, name, contents):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    def run_script(self, mode, *, script=SCRIPT, check=True):
        result = subprocess.run(["bash", str(script), mode], env=self.env, text=True,
                                capture_output=True, timeout=15)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def manifest(self, image="agent"):
        self.env["BUILD_IMAGE"] = image
        return json.loads(self.run_script("--manifest").stdout)

    def fingerprint(self, image="agent"):
        self.env["BUILD_IMAGE"] = image
        return self.run_script("--fingerprint").stdout.strip()

    def plan(self, image="agent"):
        self.env["BUILD_SOURCES_JSON"] = json.dumps(self.manifest(image))
        self.env["BUILD_FINGERPRINT"] = self.fingerprint(image)

    def commands(self):
        path = Path(self.env["MOCK_LOG"])
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_required_agent_runtime_skills_and_sample_data(self):
        sources = self.manifest()
        self.assertIn("apps/agent/src/db.csv", sources)
        self.assertIn("apps/agent/src/plan.py", sources)
        self.assertIn("apps/agent/src/credentials.py", sources)
        self.assertEqual(sum(name.endswith("SKILL.md") for name in sources), 3)
        self.assertIn("infra/Dockerfile.agent", sources)
        self.assertNotIn("docker/Dockerfile.app", sources)

    def test_web_contains_manifests_and_patches_not_agent(self):
        sources = self.manifest("web")
        self.assertIn("patches/fast-json-patch@3.1.1.patch", sources)
        self.assertIn("docker/Dockerfile.app", sources)
        self.assertFalse(any(name.startswith("apps/agent/") for name in sources))

    @unittest.skipUnless(shutil.which("terraform"), "Terraform not installed")
    def test_web_build_inputs_do_not_traverse_generated_workspace_trees(self):
        for name in ("apps/app/next.config.ts", "apps/app/tsconfig.json",
                     "apps/app/postcss.config.mjs", "packages/design-system/tsconfig.json"):
            self.write(name, "build configuration\n")
        self.write("apps/app/public/icon.svg", "<svg/>")
        for folder in ("apps/app/.next", "apps/app/node_modules",
                       "packages/design-system/node_modules", "packages/design-system/dist"):
            self.write(folder + "/generated.js", "generated output")
            (self.root / folder / "broken-link").symlink_to(self.root / "missing")
        sources = self.manifest("web")
        self.assertIn("apps/app/next.config.ts", sources)
        self.assertIn("apps/app/public/icon.svg", sources)
        self.assertIn("packages/design-system/tsconfig.json", sources)
        self.assertFalse(any("generated.js" in name for name in sources))
        self.assertFalse(any("broken-link" in name for name in sources))
        block = (ROOT / "infra/build.tf").read_text().split("  built_images = {")[0] + "}\n"
        block = block.replace('abspath("${path.module}/..")', json.dumps(str(self.root)))
        block = block.replace('${path.module}/scripts/', str(ROOT / "infra/scripts") + "/")
        path = Path(self.temporary.name) / "terraform-root"
        path.mkdir()
        (path / "main.tf").write_text(block)
        result = subprocess.run(["terraform", f"-chdir={path}", "console"], check=True,
                                input="jsonencode(local.build_sources.web)\n", text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(json.loads(json.loads(result.stdout.strip())), sources)

    def test_nested_sensitive_generated_and_cache_files_do_not_affect_context(self):
        names = [".env", ".env.production", ".env.test.local", "nested/.azure/env/config.json",
                 "nested/.terraform/terraform.tfstate", "nested/cache.tfstate.backup",
                 "nested/terraform.tfplan", "nested/plan.json", "nested/terraform-plan.json",
                 "nested/app.env.example", "nested/secret.json", "nested/credentials.json",
                 "nested/cert.pem", "nested/private.key", "nested/identity.pfx",
                 "nested/node_modules/package/index.js", "nested/__pycache__/main.pyc",
                 "nested/.next/cache/a.json", "nested/.venv/lib/a.py",
                 "nested/generated/assets.json", "nested/__generated__/assets.json",
                 "nested/cache/cache.json", "nested/caches/cache.json",
                 "nested/.git/config", "nested/accessTokens.json", "nested/tfplan",
                 "nested/service-account.json", "nested/saved.plan.json", "nested/state.json",
                 "nested/azureProfile.json", "nested/msal_token_cache.json",
                 "nested/tests/test_runtime.py", "nested/state.tfvars.json"]
        for image, folder in (("web", "apps/app/src/"), ("agent", "apps/agent/src/")):
            original = self.manifest(image)
            before = self.fingerprint(image)
            for name in names:
                self.write(folder + name, "synthetic-sensitive-output")
            self.assertEqual(self.manifest(image), original)
            self.assertEqual(self.fingerprint(image), before)

    def test_fingerprints_change_only_for_relevant_inputs(self):
        agent, web = self.fingerprint(), self.fingerprint("web")
        for name in ("apps/agent/main.py", "apps/agent/uv.lock",
                     "apps/agent/skills/master-playbook/SKILL.md", "infra/Dockerfile.agent"):
            with self.subTest(name=name):
                path = self.root / name
                previous = path.read_text()
                path.write_text(previous + "changed")
                self.assertNotEqual(self.fingerprint(), agent)
                self.assertEqual(self.fingerprint("web"), web)
                path.write_text(previous)
        for name in ("pnpm-lock.yaml", "patches/fast-json-patch@3.1.1.patch",
                     "apps/app/src/index.ts", "packages/design-system/src/index.ts",
                     "docker/Dockerfile.app"):
            with self.subTest(name=name):
                path = self.root / name
                previous = path.read_text()
                path.write_text(previous + "changed")
                self.assertNotEqual(self.fingerprint("web"), web)
                self.assertEqual(self.fingerprint(), agent)
                path.write_text(previous)

    def test_symlinks_are_rejected_instead_of_uploading_unrelated_files(self):
        secret = Path(self.temporary.name) / "outside.txt"
        secret.write_text("synthetic-sensitive-output")
        (self.root / "apps/agent/src/linked.py").symlink_to(secret)
        result = self.run_script("--manifest", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Symlinks", result.stderr)

    def test_changed_inputs_refuse_build_before_any_cloud_call(self):
        self.plan()
        self.write("apps/agent/main.py", "changed after planning")
        result = self.run_script("--build", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Re-plan", result.stderr)
        self.assertEqual(self.commands(), [])

    def test_success_stages_exact_hashed_files_and_verifies_image(self):
        for image in ("web", "agent"):
            with self.subTest(image=image):
                self.plan(image)
                self.write(("apps/app/" if image == "web" else "apps/agent/src/") + ".env",
                           "synthetic-sensitive-output")
                self.run_script("--build")
                staged = json.loads(Path(self.env["MOCK_CONTEXT"]).read_text())
                self.assertEqual(staged, sorted(json.loads(self.env["BUILD_SOURCES_JSON"])))
                self.assertEqual(self.commands()[-1][:3], ["acr", "repository", "show"])
                args = next(c for c in reversed(self.commands()) if c[:2] == ["acr", "build"])
                self.assertIn(f"{image}:{self.env['BUILD_FINGERPRINT']}", args)
                self.assertNotIn("synthetic-sensitive-output", json.dumps(self.commands()))

    def test_build_failure_is_not_retried_or_verified(self):
        for scenario in ("build-exit", "build-status"):
            with self.subTest(scenario=scenario):
                self.env["MOCK_SCENARIO"] = scenario
                self.plan()
                log = Path(self.env["MOCK_LOG"])
                log.unlink(missing_ok=True)
                result = self.run_script("--build", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sum(c[:2] == ["acr", "build"] for c in self.commands()), 1)
                self.assertFalse(any(c[:3] == ["acr", "repository", "show"] for c in self.commands()))
                self.assertNotIn("synthetic-sensitive-output", result.stdout + result.stderr)

    def test_missing_image_fails_after_successful_build(self):
        self.env["MOCK_SCENARIO"] = "missing-image"
        self.plan()
        result = self.run_script("--build", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("manifest digest", result.stderr)

    def test_model_or_subscription_failure_happens_before_build(self):
        for scenario in ("missing-model", "deployment", "disabled"):
            with self.subTest(scenario=scenario):
                self.env["MOCK_SCENARIO"] = scenario
                self.plan()
                Path(self.env["MOCK_LOG"]).unlink(missing_ok=True)
                result = self.run_script("--build", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c[:2] == ["acr", "build"] for c in self.commands()))

    def test_before_provision_checks_free_quota_before_build_permissions(self):
        result = self.run_script("--before-provision", script=PREFLIGHT, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Insufficient unallocated", result.stderr)
        self.assertFalse(any(c[:2] == ["acr", "build"] for c in self.commands()))

    def test_build_allows_quota_already_consumed_by_successful_deployments(self):
        for scenario in ("", "over-quota"):
            self.env["MOCK_SCENARIO"] = scenario
            self.run_script("--before-build", script=PREFLIGHT)
        self.assertFalse(any(c[:2] == ["acr", "build"] for c in self.commands()))

    def test_before_provision_success_uses_only_read_only_operations(self):
        self.env["MOCK_SCENARIO"] = "available-quota"
        self.run_script("--before-provision", script=PREFLIGHT)
        self.assertEqual(self.commands()[-1][:3], ["rest", "--method", "get"])
        self.assertFalse(any(c[:2] == ["acr", "build"] for c in self.commands()))

    def test_role_visibility_retries_are_bounded_and_never_start_a_build(self):
        # Omit real delays in this isolated test copy; production stays 5 x 10s.
        original = PREFLIGHT.read_text()
        self.assertIn("time.sleep(10)", original)
        fast = Path(self.temporary.name) / "preflight-fast.sh"
        fast.write_text(original.replace("time.sleep(10)", "time.sleep(0)"))
        for scenario, expected_calls, success in (("permissions", 6, False), ("propagation", 3, True)):
            with self.subTest(scenario=scenario):
                self.env["MOCK_SCENARIO"] = scenario
                Path(self.env["MOCK_LOG"]).unlink(missing_ok=True)
                result = self.run_script("--before-build", script=fast, check=False)
                self.assertEqual(result.returncode == 0, success, result.stderr)
                reads = [c for c in self.commands() if c[:3] == ["rest", "--method", "get"]
                         and "Microsoft.Authorization/permissions" in " ".join(c)]
                self.assertEqual(len(reads), expected_calls)
                self.assertFalse(any(c[:2] == ["acr", "build"] for c in self.commands()))


class RepositoryPackagingTests(unittest.TestCase):
    def test_dockerfile_pnpm_pin_patches_before_install_and_agent_runtime(self):
        dockerfile = (ROOT / "docker/Dockerfile.app").read_text()
        pin = json.loads((ROOT / "package.json").read_text())["packageManager"]
        self.assertEqual(dockerfile.count("corepack prepare " + pin), 2)
        self.assertNotIn("pnpm@latest", dockerfile)
        self.assertLess(dockerfile.index("COPY patches"), dockerfile.index("RUN pnpm install"))
        agent = (ROOT / "infra/Dockerfile.agent").read_text()
        self.assertIn("--locked --no-dev", agent)
        self.assertIn("python:3.12-slim", agent)
        self.assertIn("USER agent", agent)
        self.assertIn('"main:app"', agent)
        self.assertNotIn("--reload", agent)
        ignore = (ROOT / ".dockerignore").read_text()
        for skill in ("master-playbook", "advanced-visualization", "svg-diagrams"):
            self.assertIn(f"!apps/agent/skills/{skill}/SKILL.md", ignore)

    @unittest.skipUnless(shutil.which("terraform"), "Terraform not installed")
    def test_terraform_and_script_fingerprints_are_equivalent(self):
        # A standalone, local-only Terraform root evaluates the real locals
        # against this checkout. No provider, backend, Azure or tfvars involved.
        source = (ROOT / "infra/build.tf").read_text()
        block = source[:source.index('  built_images = {')] + "}\n"
        block = block.replace('abspath("${path.module}/..")', json.dumps(str(ROOT)))
        block = block.replace('${path.module}/scripts/', str(ROOT / "infra/scripts") + "/")
        with tempfile.TemporaryDirectory(prefix="openui-fingerprint-") as directory:
            path = Path(directory)
            (path / "main.tf").write_text(block)
            value = subprocess.run(["terraform", f"-chdir={directory}", "console"], check=True,
                                   input="jsonencode(local.build_hashes)\n", text=True,
                                   capture_output=True, timeout=30).stdout.strip()
            expected = json.loads(json.loads(value))
            for image in ("web", "agent"):
                result = subprocess.run(["bash", str(SCRIPT), "--fingerprint"], check=True,
                                        env={**os.environ, "BUILD_IMAGE": image,
                                             "BUILD_ROOT": str(ROOT)},
                                        text=True, capture_output=True, timeout=15)
                self.assertEqual(result.stdout.strip(), expected[image])


if __name__ == "__main__":
    unittest.main()
