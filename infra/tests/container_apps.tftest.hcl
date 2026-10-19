mock_provider "azurerm" {
  override_during = plan

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000002"
      subscription_id = "00000000-0000-0000-0000-000000000001"
      client_id       = "00000000-0000-0000-0000-000000000003"
      object_id       = "00000000-0000-0000-0000-000000000004"
    }
  }

  mock_resource "azurerm_cognitive_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-test/providers/Microsoft.CognitiveServices/accounts/foundrytest"
    }
  }

  mock_resource "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-test/providers/Microsoft.ContainerRegistry/registries/registrytest"
      login_server = "registrytest.azurecr.io"
    }
  }

  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id             = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-test/providers/Microsoft.App/managedEnvironments/environmenttest"
      default_domain = "environmenttest.azurecontainerapps.io"
    }
  }

  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test"
      principal_id = "00000000-0000-0000-0000-000000000010"
      client_id    = "00000000-0000-0000-0000-000000000011"
    }
  }

  mock_resource "azurerm_container_app" {
    defaults = {
      ingress = { fqdn = "agent.internal.environmenttest.azurecontainerapps.io" }
    }
  }
}

override_resource {
  target          = terraform_data.webiq_secret_revision
  override_during = plan
  values          = { id = "non-secret-rotation-token" }
}

variables {
  environment_name   = "test"
  subscription_id    = "00000000-0000-0000-0000-000000000001"
  location           = "eastus2"
  foundry_location   = "westus"
  chat_model_version = "test-version"
  webiq_api_key      = "mock-only-not-a-credential"
}

run "abbreviation_first_resource_names" {
  command = plan
  variables {
    environment_name = "prefix-test"
  }
  assert {
    condition = (
      azurerm_resource_group.main.name == "rg-ogui-prefix-test" &&
      azurerm_container_app.web.name == "aca-ogui-prefix-test-web" &&
      azurerm_container_app.agent.name == "aca-ogui-prefix-test-agent" &&
      azurerm_container_app_environment.main.name == "cae-ogui-prefix-test" &&
      azurerm_log_analytics_workspace.main.name == "log-ogui-prefix-test" &&
      azurerm_user_assigned_identity.web.name == "id-ogui-prefix-test-web" &&
      azurerm_user_assigned_identity.agent.name == "id-ogui-prefix-test-agent" &&
      azurerm_cognitive_account.main.name == "ai-ogui-prefix-test-${local.resource_token}" &&
      azurerm_cognitive_account.main.custom_subdomain_name == azurerm_cognitive_account.main.name &&
      azurerm_cognitive_account_project.main.name == "proj-ogui-prefix-test" &&
      azurerm_container_registry.main.name == "acroguiprefixtest${local.resource_token}" &&
      can(regex("^[a-z0-9]{5,50}$", azurerm_container_registry.main.name))
    )
    error_message = "Resource names must start with their abbreviations; globally unique names must retain the token and ACR must remain alphanumeric."
  }
}

run "https_ingress_and_scoped_configuration" {
  command = plan

  assert {
    condition = (
      azurerm_container_app.web.ingress[0].external_enabled &&
      !azurerm_container_app.web.ingress[0].allow_insecure_connections &&
      azurerm_container_app.web.ingress[0].target_port == 3000 &&
      !azurerm_container_app.agent.ingress[0].external_enabled &&
      !azurerm_container_app.agent.ingress[0].allow_insecure_connections &&
      azurerm_container_app.agent.ingress[0].target_port == 8123 &&
      azurerm_container_app.web.revision_mode == "Single" &&
      azurerm_container_app.agent.revision_mode == "Single"
    )
    error_message = "Only the web service may be public; both services must use HTTPS-only, single-revision ingress."
  }

  assert {
    condition = (
      azurerm_container_app.web.registry[0].identity == azurerm_user_assigned_identity.web.id &&
      azurerm_container_app.agent.registry[0].identity == azurerm_user_assigned_identity.agent.id &&
      azurerm_container_app.web.template[0].container[0].image == local.built_images.web &&
      azurerm_container_app.agent.template[0].container[0].image == local.built_images.agent &&
      !azurerm_container_registry.main.admin_enabled &&
      azurerm_container_registry.main.azuread_authentication_as_arm_policy_enabled &&
      azurerm_container_registry.main.role_assignment_mode == "LegacyRegistryPermissions" &&
      length(azurerm_container_app.web.secret) == 0
    )
    error_message = "Real content-tagged private images must use managed identity, without web service secrets or registry admin authentication."
  }

  assert {
    condition = (
      one([for env in azurerm_container_app.web.template[0].container[0].env : env.value if env.name == "LANGGRAPH_DEPLOYMENT_URL"]) == "https://${azurerm_container_app.agent.ingress[0].fqdn}" &&
      one([for env in azurerm_container_app.web.template[0].container[0].env : env.value if env.name == "APP_URL"]) == "https://${azurerm_container_app.web.name}.${azurerm_container_app_environment.main.default_domain}" &&
      one([for env in azurerm_container_app.agent.template[0].container[0].env : env.value if env.name == "AZURE_AI_FOUNDRY_ENABLED"]) == "true" &&
      one([for env in azurerm_container_app.agent.template[0].container[0].env : env.value if env.name == "AZURE_AI_FOUNDRY_ENDPOINT"]) == local.foundry_endpoint &&
      one([for env in azurerm_container_app.agent.template[0].container[0].env : env.value if env.name == "AZURE_CLIENT_ID"]) == azurerm_user_assigned_identity.agent.client_id &&
      one([for env in azurerm_container_app.agent.template[0].container[0].env : env.value if env.name == "LLM_MODEL"]) == var.chat_deployment_name &&
      one([for env in azurerm_container_app.agent.template[0].container[0].env : env.value if env.name == "AZURE_DECISION_DEPLOYMENT"]) == var.decision_deployment_name
    )
    error_message = "The web must use internal HTTPS and the agent must select its configured managed identity and actual Foundry deployment names."
  }

  assert {
    condition = (
      one([for env in azurerm_container_app.agent.template[0].container[0].env : env.secret_name if env.name == "WEBIQ_API_KEY"]) == "webiq-api-key" &&
      one([for env in azurerm_container_app.agent.template[0].container[0].env : env.value if env.name == "WEBIQ_SECRET_REVISION"]) == terraform_data.webiq_secret_revision.id &&
      one([for secret in azurerm_container_app.agent.secret : secret.value if secret.name == "webiq-api-key"]) == var.webiq_api_key &&
      alltrue([for env in azurerm_container_app.web.template[0].container[0].env : !strcontains(env.name, "API_KEY")])
    )
    error_message = "WebIQ must use an agent-only ACA secret, with a non-secret template token so rotation rolls out a new revision."
  }

  assert {
    condition = alltrue([for service in [azurerm_container_app.web, azurerm_container_app.agent] :
      service.template[0].min_replicas == 1 &&
      service.template[0].max_replicas == 1 &&
      service.ingress[0].traffic_weight[0].latest_revision &&
      service.ingress[0].traffic_weight[0].percentage == 100 &&
      length(service.template[0].container[0].startup_probe) == 1 &&
      length(service.template[0].container[0].readiness_probe) == 1 &&
      length(service.template[0].container[0].liveness_probe) == 1
    ])
    error_message = "Default deployments must preserve single-instance process-local state and include all health probes and latest-revision routing."
  }
}

run "reject_invalid_cpu_and_replicas" {
  command = plan
  variables {
    agent_resources = { cpu = 0.3, min_replicas = 2, max_replicas = 1 }
  }
  expect_failures = [var.agent_resources]
}

run "reject_blank_secret" {
  command = plan
  variables {
    webiq_api_key = " "
  }
  expect_failures = [var.webiq_api_key]
}

run "reject_insecure_webiq" {
  command = plan
  variables {
    webiq_endpoint = "http://api.microsoft.ai/v3/search/web"
  }
  expect_failures = [var.webiq_endpoint]
}

run "reject_missing_model_version" {
  command = plan
  variables {
    chat_model_version = ""
  }
  expect_failures = [var.chat_model_version]
}

run "reject_colliding_deployments" {
  command = plan
  variables {
    decision_deployment_name = "gpt-6-luna"
  }
  expect_failures = [var.decision_deployment_name]
}

run "reject_unsafe_environment_name" {
  command = plan
  variables {
    environment_name = "bad;echo"
  }
  expect_failures = [var.environment_name]
}

run "reject_double_hyphen_environment_name" {
  command = plan
  variables {
    environment_name = "bad--name"
  }
  expect_failures = [var.environment_name]
}

run "maximum_length_names_and_custom_resources" {
  command = plan
  variables {
    environment_name = "abcdefghijklmnopqrst"
    web_resources    = { cpu = 0.25, min_replicas = 0, max_replicas = 3 }
    agent_resources  = { cpu = 2, min_replicas = 1, max_replicas = 2 }
  }
  assert {
    condition = (
      azurerm_container_app.web.name == "aca-ogui-abcdefgh-${local.resource_token}-web" &&
      azurerm_container_app.agent.name == "aca-ogui-abcdefgh-${local.resource_token}-agent" &&
      length(azurerm_container_app.agent.name) == 32 &&
      one([for env in azurerm_container_app.web.template[0].container[0].env : env.value if env.name == "APP_URL"]) == "https://${azurerm_container_app.web.name}.${azurerm_container_app_environment.main.default_domain}" &&
      azurerm_container_app.web.template[0].container[0].memory == "0.5Gi" &&
      azurerm_container_app.agent.template[0].container[0].memory == "4Gi" &&
      azurerm_container_app.web.template[0].min_replicas == 0 &&
      azurerm_container_app.web.template[0].max_replicas == 3
    )
    error_message = "Names must remain ACA-valid at maximum length and custom consumption resources must retain valid CPU/memory ratios."
  }
}

run "longest_unshortened_container_app_names" {
  command = plan
  variables {
    environment_name = "abcdefghijklmnopq"
  }
  assert {
    condition = (
      azurerm_container_app.agent.name == "aca-ogui-abcdefghijklmnopq-agent" &&
      azurerm_container_app.web.name == "aca-ogui-abcdefghijklmnopq-web" &&
      length(azurerm_container_app.agent.name) == 32
    )
    error_message = "Container app names that fit exactly must preserve the full environment name."
  }
}

run "long_names_trim_separator_before_hash" {
  command = plan
  variables {
    environment_name = "abcdefg-hijklmnopqrs"
  }
  assert {
    condition = alltrue([for service in [azurerm_container_app.web, azurerm_container_app.agent] :
      startswith(service.name, "aca-ogui-abcdefg-${local.resource_token}-") &&
      length(service.name) <= 32 &&
      !strcontains(service.name, "--")
    ])
    error_message = "Shortening at a separator must not introduce a consecutive hyphen or exceed ACA's length limit."
  }
}

run "long_environments_with_shared_prefix_have_distinct_names" {
  command = plan
  variables {
    environment_name = "abcdefghijklmnopqrsu"
  }
  assert {
    condition = (
      azurerm_container_app.agent.name != "aca-ogui-abcdefgh-${substr(sha256("${var.subscription_id}:abcdefghijklmnopqrst"), 0, 8)}-agent" &&
      azurerm_container_app.web.name != "aca-ogui-abcdefgh-${substr(sha256("${var.subscription_id}:abcdefghijklmnopqrst"), 0, 8)}-web"
    )
    error_message = "Long environments that share a shortened prefix must remain distinguished by the full-environment token."
  }
}
