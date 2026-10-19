# Azure deployment

Deploy Open Generative UI with Terraform and Azure Developer CLI (azd). Terraform
owns infrastructure, ACR remote builds, image references, and ACA revisions.
`azd provision` and `azd up` run that same Terraform deployment; there are no azd
application services and `azd deploy` is not an application-update command.

## Resources and authentication

The stack creates a resource group, Basic ACR, Log Analytics workspace, shared
ACA consumption environment, public HTTPS web app, internal-only HTTPS Python
agent, and a Microsoft Foundry account/project with chat and Decision model
deployments. The web server calls the agent inside the ACA environment; the
browser never needs access to the agent endpoint.

Separate user-assigned identities pull the web and agent images with `AcrPull`.
Only the agent receives Foundry inference access. Foundry local/API-key
authentication and ACR administrator credentials are disabled. Entra ID here
authenticates the agent to Foundry, not visitors to the public web app.

WebIQ must already exist. Its API key is injected into **only the agent** through
an ACA secret; no provider secret goes into an image, build argument, Terraform
output, or public frontend environment variable. No Key Vault is provisioned.

## Prerequisites

Run all tools in the same Linux/WSL environment, from the repository root:

- Terraform 1.9 or later, below 2.0; AzureRM provider 4.81 is the tested baseline.
- Azure CLI, azd (the provision-only workflow supports 1.25.1), Bash and Python 3.
- An Azure subscription permitting ACA, ACR Tasks quick builds, Foundry, and
  resource-scoped role assignments. The deployment principal needs resource
  creation, ACR quick-build/image access, and role assignment permissions, not
  just Foundry inference access.
- Regions, model versions, deployment SKUs, and quota verified against that
  subscription. Foundry can use a different region from ACA/ACR.

No local Docker daemon is needed. Images are built remotely for `linux/amd64`,
even if the WSL host is ARM64. Terraform's `terraform_data` + `local-exec` invokes
`az acr build`; Terraform does not have a built-in `local_resource`.

Authenticate both azd and Terraform through Azure CLI:

```bash
azd config set auth.useAzCliAuth true
az login --tenant "<tenant-id>"
az account show --query '{name:name,id:id,tenantId:tenantId}'
```

Alternatively, authenticate each tool separately with `azd auth login` and
`az login`. An azd-only login is insufficient for the Terraform AzureRM provider
and the remote-build commands. ACR commands explicitly target the configured
subscription; the stack does not silently select this machine's default.

## Configure an environment

Replace the placeholder values before running these commands:

```bash
umask 077
azd env new dev --no-prompt
azd env set AZURE_SUBSCRIPTION_ID "<subscription-id>"
azd env set AZURE_LOCATION "<aca-and-acr-region>"
azd env set AZURE_FOUNDRY_LOCATION "<supported-foundry-region>"
azd env set AZURE_CHAT_MODEL_VERSION "<exact-chat-model-version>"
```

Environment names must be 3-20 lowercase letters, digits or hyphens, start with a
letter, end with a letter or digit, and contain no consecutive hyphens.
Use a different environment name for an independent deployment.

### Resource naming convention

Names start with a resource-type abbreviation followed by the application base
`ogui` (Open Generative UI) and environment:

| Resource | Name pattern |
| --- | --- |
| Resource group | `rg-ogui-<environment>` |
| Web / agent container apps | `aca-ogui-<environment>-web` / `aca-ogui-<environment>-agent` |
| Container Apps environment | `cae-ogui-<environment>` |
| Foundry account and subdomain | `ai-ogui-<environment>-<token>` |
| Foundry project | `proj-ogui-<environment>` |
| Container registry | `acrogui<environment-without-hyphens><token>` |
| Log Analytics workspace | `log-ogui-<environment>` |
| Managed identities | `id-ogui-<environment>-web` / `id-ogui-<environment>-agent` |

ACR names omit separators because Azure permits only alphanumeric characters.
The deterministic eight-character token includes subscription and the full
environment name, preserving globally unique ACR/Foundry naming. If an ACA name
would exceed 32 characters, its application/environment base is shortened and
the same token is appended before the service suffix; `aca-` and `-web`/`-agent`
are retained. Application URLs use these final resource names.

Changing naming rules on an existing deployment can replace resources and change
endpoints; review the provision preview before applying. This convention does
not migrate or rename existing Azure resources in place.

The chat model defaults to `gpt-6-luna`. Its version is deliberately required
rather than guessed. The routing model is `Microsoft-Decision-1`, format
`Microsoft`, version `1`, deployment name `Decision-1`. Both default to
`GlobalStandard`, capacity 1; defaults do **not** prove model availability, access,
or sufficient quota. Check the target region's catalog and subscription quota
before provisioning. Never substitute a different model silently.

`main.tfvars.json` substitutes the five non-secret azd variables above.
Optional Terraform inputs can be exported in the **calling shell**, for example:

```bash
export TF_VAR_chat_deployment_capacity=10
export TF_VAR_decision_deployment_capacity=1
export TF_VAR_web_resources='{"cpu":0.5,"min_replicas":1,"max_replicas":1}'
export TF_VAR_agent_resources='{"cpu":1,"min_replicas":1,"max_replicas":1}'
```

See `variables.tf` for configurable deployment names, chat model, SKUs, WebIQ
endpoint, CPU and replica limits. A custom chat deployment name must start with
`gpt-` because the existing application uses that prefix to select its provider.
Do not rely on `azd env set TF_VAR_*` exporting variables to Terraform; export
them in the process that launches azd.

Read the existing WebIQ key without putting its literal value in shell history:

```bash
read -rsp "Existing WebIQ API key: " TF_VAR_webiq_api_key
printf '\n'
export TF_VAR_webiq_api_key
```

Do not enable shell tracing, `TF_LOG`, or debug logging while handling secrets.
Do not save the key with `azd env set`, paste it into command arguments, or
include it in a committed variable file.

## Provision and update

These commands **create billable Azure resources and run billable ACR builds**:

```bash
azd provision --preview
azd provision
# Equivalent full workflow for this provision-only project:
azd up
unset TF_VAR_webiq_api_key
```

Preview performs Azure reads and saves a Terraform plan containing sensitive
values, but does not run local-exec builds. Review the plan before provisioning.
The first apply provisions the registry and model deployments, remotely builds
the application images, and deploys those images to ACA. Model-deployment failure
stops dependent builds. Runtime identities and pull/inference roles precede ACA
creation, avoiding a placeholder-image bootstrap and a second deployment owner.

Each image is built from a private temporary staging directory containing only
its explicitly scoped, fingerprinted inputs, not an upload of the working tree.
The build refuses changed inputs after planning. It includes agent skills and
sample data and web workspace patches, but excludes environment/credential files,
state, caches and tests. Before a paid build, a read-only preflight checks the
explicit subscription, catalog settings, actual successful model deployments,
registry readiness, and effective build/image-read access. Missing effective
build permissions receive bounded retries; paid builds are never automatically
retried. Successful run status and the tagged image manifest are verified before
Terraform can create the corresponding ACA application.

On updates, rerun `azd provision` or `azd up` from the same environment and supply
the WebIQ key again. Source-derived image tags change when relevant build inputs
change. An unchanged configuration must not enqueue another build. Terraform
tracks the real image and registry identity; it does not ignore image drift.
Rotating the WebIQ key changes a non-secret template token, rolling out an agent
revision so running replicas receive the new value; it does not rebuild images.
Terraform cannot detect a manually deleted ACR image just from a recorded
successful build resource: restore it by deliberately replacing the corresponding
build resource in a reviewed Terraform operation.

Defaults keep one replica of each service. Memory scales with the consumption
CPU allocation (2 GiB per vCPU). Agent checkpoints and frontend rate limits are
process-local; restarting, scaling to zero, or using multiple replicas can lose
or split conversation state and alter effective rate limits. This stack adds no
durable shared state. Readiness/liveness endpoints check process health, not
provider authentication or inference availability.

Deployment outputs include the public web URL, internal agent URL, resource
group, registry and Foundry endpoint. The agent URL is deliberately not reachable
from the public internet. Do not print or export raw Terraform state to discover
outputs.

## State and secret handling

azd keeps each environment's state, plans, resolved inputs, and provider data
under `.azure/<environment>/infra`. This directory, Terraform artifacts and
environment/credential files are excluded from Git and ACR upload contexts.
The provider lockfile is intentionally committed.

**The WebIQ key is still stored in Terraform state and saved plans.** The
`sensitive` flag redacts normal presentation; it does not encrypt local files.
Protect the complete `.azure` directory, its backups, your user account and disk;
WSL files on a Windows-mounted volume also depend on Windows ACLs. Do not upload,
share, log, or commit these files. Run one deployment at a time per environment.
Before team/CI use, configure a secured remote backend and deliberately migrate
existing state; do not casually reinitialize or apply against an empty state.

Use azd consistently after initial provisioning. Bare `terraform apply` defaults
to a different local state path and can attempt duplicate resources. Advanced
direct Terraform use must explicitly preserve azd's environment-specific
`TF_DATA_DIR`, state path, and resolved variable file.

Deleting an environment's local files does not delete its cloud resources; it
removes Terraform's record of them. Destruction through `azd down` is a separate,
explicitly destructive operation, not a validation or migration step.

## Local validation and live acceptance

From WSL, static checks can run without provisioning:

```bash
terraform -chdir=infra init -input=false
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
terraform -chdir=infra test
python3 -m unittest discover -s infra/tests -p 'test_*.py'
```

The configured backend is local. `init` here installs/validates providers and
does not provision Azure resources. Terraform tests use plan-only mock providers;
build script tests use mocked Azure CLI calls, never paid quick builds. Do not
switch these Terraform tests to apply: resource overrides do not suppress
`local-exec` provisioners.

A real release still requires a separately authorized deployment: verify both
model deployments and quota, complete the remote builds, check the web health
endpoint and internal agent health from inside the environment, then exercise a
real chat response, Decision routing, WebIQ grounding, streamed interactive UI,
and a deliberate follow-up through the public web app. Repeat with an unchanged
apply to confirm builds are not requeued. Never equate a rendered shell or health
response with working provider authentication.

## References

- [Azure resource naming rules](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/resource-name-rules)
- [azd with Terraform](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/use-terraform-for-azd)
- [azure.yaml schema and workflows](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/azd-schema)
- [Create Microsoft Foundry using Terraform](https://learn.microsoft.com/en-us/azure/foundry/how-to/create-resource-terraform)
- [Microsoft-Decision-1 deployment](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision)
- [Managed identity image pulls in ACA](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity-image-pull)
- [ACR remote builds](https://learn.microsoft.com/en-us/cli/azure/acr#az-acr-build)
