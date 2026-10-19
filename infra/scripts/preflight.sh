#!/usr/bin/env bash
# Read-only prerequisites. --before-provision checks *additional* quota and
# subscription-scope build permissions; --before-build checks the created
# registry and the actual, already-allocated model deployments instead.
set -euo pipefail
for tool in az python3 bash; do
  command -v "$tool" >/dev/null || { printf 'Required command missing: %s\n' "$tool" >&2; exit 1; }
done
exec python3 - "$@" <<'PY'
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict


def fail(message):
    raise RuntimeError(message)


def required(name):
    value = os.environ.get(name, "")
    if not value:
        fail(f"Set {name} explicitly; no current-account or model-version defaults are used.")
    return value


def cli(*args):
    result = subprocess.run(["az", *args, "--subscription", subscription,
                             "--only-show-errors", "--output", "json"],
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def permission_list(scope):
    # Documented ARM Permissions - List For Resource / Resource Group / subscription.
    return cli("rest", "--method", "get", "--url",
               f"https://management.azure.com{scope}/providers/Microsoft.Authorization/permissions"
               "?api-version=2022-04-01").get("value", [])


def allows(grants, action):
    action = action.lower()
    return any(any(fnmatch.fnmatchcase(action, p.lower()) for p in g.get("actions", []))
               and not any(fnmatch.fnmatchcase(action, p.lower()) for p in g.get("notActions", []))
               for g in grants)


try:
    mode = sys.argv[1:] or ["--before-provision"]
    if mode not in (["--before-provision"], ["--before-build"]):
        fail("Usage: preflight.sh [--before-provision|--before-build]")
    before_build = mode == ["--before-build"]
    if not before_build and any(not shutil.which(tool) for tool in ("terraform", "azd")):
        fail("The provision-only workflow requires terraform and azd on the same host as az.")
    subscription = required("SUBSCRIPTION_ID")
    if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", subscription):
        fail("SUBSCRIPTION_ID must be a subscription UUID.")
    location = required("FOUNDRY_LOCATION")
    if not re.fullmatch(r"[a-z][a-z0-9]+", location):
        fail("FOUNDRY_LOCATION must be a region name.")
    account = cli("account", "show")
    if account.get("id", "").lower() != subscription.lower() or account.get("state") != "Enabled":
        fail("The explicitly selected subscription is unavailable or not Enabled; az login first.")

    selections = [
        ("chat", "OpenAI", required("CHAT_MODEL_NAME"), required("CHAT_MODEL_VERSION"),
         required("CHAT_DEPLOYMENT_SKU"), int(required("CHAT_DEPLOYMENT_CAPACITY"))),
        ("decision", "Microsoft", "Microsoft-Decision-1", "1",
         required("DECISION_DEPLOYMENT_SKU"), int(required("DECISION_DEPLOYMENT_CAPACITY"))),
    ]
    # These installed Azure CLI commands use the documented regional model and
    # usage APIs, including pagination. Do not invent model versions/quota names.
    catalog = cli("cognitiveservices", "model", "list", "--location", location)
    usages = cli("cognitiveservices", "usage", "list", "--location", location)
    demands = defaultdict(int)
    for label, model_format, name, version, sku, capacity in selections:
        models = [entry.get("model", {}) for entry in catalog
                  if entry.get("model", {}).get("format") == model_format
                  and entry.get("model", {}).get("name") == name
                  and entry.get("model", {}).get("version") == version]
        matches = [item for model in models for item in (model.get("skus") or [])
                   if item.get("name") == sku]
        if not matches:
            fail(f"{label}: exact model version and SKU not present in the selected regional catalog.")
        if capacity < 1:
            fail(f"{label}: capacity must be positive.")
        selected = matches[0]
        limits = selected.get("capacity") or {}
        minimum = limits.get("minimum") or 1
        maximum = limits.get("maximum")
        step = limits.get("step", 1)
        allowed = limits.get("allowedValues")
        if (capacity < minimum or (maximum is not None and capacity > maximum)
                or (step and (capacity - minimum) % step)
                or (allowed and capacity not in allowed)):
            fail(f"{label}: requested capacity does not match the model SKU's capacity rules.")
        if before_build:
            deployment_id = required(label.upper() + "_DEPLOYMENT_ID")
            prefix = f"/subscriptions/{subscription}/"
            if (not deployment_id.lower().startswith(prefix.lower())
                    or not re.fullmatch(r"/[A-Za-z0-9_./()-]+", deployment_id)
                    or any(part in ("", ".", "..") for part in deployment_id.split("/")[1:])):
                fail(f"{label}: invalid deployment ID for the selected subscription.")
            deployed = cli("rest", "--method", "get", "--url",
                           f"https://management.azure.com{deployment_id}?api-version=2024-10-01")
            properties = deployed.get("properties", {})
            actual = properties.get("model", {})
            if (properties.get("provisioningState") != "Succeeded"
                    or any(actual.get(k) != v for k, v in {
                        "format": model_format, "name": name, "version": version}.items())
                    or deployed.get("sku", {}).get("name") != sku
                    or deployed.get("sku", {}).get("capacity", 0) < capacity):
                fail(f"{label}: expected model deployment has not succeeded with the requested settings.")
        usage_name = selected.get("usageName")
        if usage_name:
            # After successful model deployment, capacity is ALREADY reserved.
            # Requiring free quota for it again would reject valid deployments.
            demands[usage_name] += 0 if before_build else capacity
        else:
            print(f"Notice: {label} SKU has no usageName; quota cannot be independently mapped. "
                  "Model deployment admission remains authoritative.", file=sys.stderr)
    for usage_name, needed in demands.items():
        matching = [u for u in usages if u.get("name", {}).get("value") == usage_name]
        if not matching:
            print("Notice: catalog quota metric not returned by the usage API; "
                  "model deployment admission remains authoritative.", file=sys.stderr)
            continue
        usage = matching[0]
        available = usage["limit"] - usage["currentValue"]
        if needed > 0 and needed > available:
            fail("Insufficient unallocated model SKU capacity in the selected subscription/region.")

    registry_name = os.environ.get("REGISTRY_NAME", "")
    scope = f"/subscriptions/{subscription}"
    if before_build:
        registry_id = required("REGISTRY_ID")
        expected = f"/subscriptions/{subscription}/resourceGroups/"
        if (not registry_id.lower().startswith(expected.lower())
                or not re.fullmatch(r"/[A-Za-z0-9_./()-]+", registry_id)
                or any(part in ("", ".", "..") for part in registry_id.split("/")[1:])
                or registry_id.rsplit("/", 1)[-1] != registry_name):
            fail("REGISTRY_ID must identify REGISTRY_NAME in the explicitly selected subscription.")
        registry = cli("acr", "show", "--name", registry_name)
        if (registry.get("id", "").lower() != registry_id.lower()
                or registry.get("provisioningState") != "Succeeded"
                or registry.get("adminUserEnabled") is not False
                or registry.get("publicNetworkAccess") == "Disabled"):
            fail("Registry is not ready for this public-network, Entra-only quick-build workflow.")
        scope = registry_id

    actions = [
        "Microsoft.ContainerRegistry/registries/read",
        "Microsoft.ContainerRegistry/registries/scheduleRun/action",
        "Microsoft.ContainerRegistry/registries/listBuildSourceUploadUrl/action",
        "Microsoft.ContainerRegistry/registries/runs/read",
    ]
    # Bounded retry ONLY for effective role visibility on the newly created
    # registry. No model/API/build failure or arbitrary command is retried.
    attempts = 6 if before_build else 1
    for attempt in range(attempts):
        grants = permission_list(scope)
        if all(allows(grants, action) for action in actions):
            break
        if attempt == attempts - 1:
            fail("Missing effective ACR quick-build permissions. Require registry read, scheduleRun, "
                 "listBuildSourceUploadUrl and runs/read (plus image data read to verify the result). "
                 "If access is scoped below the subscription, run --before-build after provisioning.")
        print("Waiting 10 seconds for newly assigned ACR build permissions to become visible "
              f"({attempt + 1}/{attempts - 1}).", file=sys.stderr, flush=True)
        time.sleep(10)
    if before_build:
        # This read-only data-plane request also checks Entra token exchange.
        # Never use az acr login (Docker), access keys or admin credentials.
        cli("acr", "repository", "list", "--name", registry_name)
    print("Read-only preflight passed. Model admission/build service and image data access "
          "are ultimately enforced by Azure; this check does not reserve capacity.")
except (RuntimeError, KeyError, ValueError, TypeError, OSError, subprocess.CalledProcessError) as error:
    message = str(error) if isinstance(error, RuntimeError) else (
        "A read-only Azure CLI prerequisite check failed. Verify login, target subscription, "
        "catalog/usage read access and ACR permissions; no build was started.")
    print(f"Preflight failed: {message}", file=sys.stderr)
    sys.exit(1)
PY
