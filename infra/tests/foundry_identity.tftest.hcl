# Mock plans only: do not authenticate to Azure or execute build provisioners.
mock_provider "azurerm" {
  override_during = plan

  mock_resource "azurerm_cognitive_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-test/providers/Microsoft.CognitiveServices/accounts/foundry-test"
    }
  }

  mock_resource "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-test/providers/Microsoft.ContainerRegistry/registries/registrytest"
      login_server = "registrytest.azurecr.io"
    }
  }

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000002"
      subscription_id = "00000000-0000-0000-0000-000000000001"
      client_id       = "00000000-0000-0000-0000-000000000003"
      object_id       = "00000000-0000-0000-0000-000000000004"
    }
  }
}

override_resource {
  target          = azurerm_user_assigned_identity.web
  override_during = plan
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/web-test"
    principal_id = "00000000-0000-0000-0000-000000000010"
    client_id    = "00000000-0000-0000-0000-000000000011"
  }
}

override_resource {
  target          = azurerm_user_assigned_identity.agent
  override_during = plan
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/agent-test"
    principal_id = "00000000-0000-0000-0000-000000000020"
    client_id    = "00000000-0000-0000-0000-000000000021"
  }
}

variables {
  environment_name         = "foundry-test"
  subscription_id          = "00000000-0000-0000-0000-000000000001"
  location                 = "eastus2"
  foundry_location         = "westus"
  chat_model_version       = "test-version"
  chat_deployment_capacity = 1
  sol_model_version        = null
  webiq_api_key            = "mock-only-not-a-credential"
}

run "keyless_foundry_and_scoped_runtime_roles" {
  command = plan

  assert {
    condition     = length(azurerm_cognitive_deployment.sol) == 0
    error_message = "Sol must remain optional until an exact catalog version is supplied."
  }

  assert {
    condition = (
      azurerm_cognitive_account.main.kind == "AIServices" &&
      azurerm_cognitive_account.main.sku_name == "S0" &&
      azurerm_cognitive_account.main.project_management_enabled &&
      !azurerm_cognitive_account.main.local_auth_enabled &&
      azurerm_cognitive_account.main.location == var.foundry_location &&
      azurerm_cognitive_account.main.custom_subdomain_name == local.foundry_name &&
      azurerm_cognitive_account.main.identity[0].type == "SystemAssigned"
    )
    error_message = "Foundry must enable projects and Entra authentication without local/key authentication."
  }

  assert {
    condition = (
      azurerm_cognitive_account_project.main.cognitive_account_id == azurerm_cognitive_account.main.id &&
      azurerm_cognitive_account_project.main.location == var.foundry_location &&
      azurerm_cognitive_account_project.main.identity[0].type == "SystemAssigned" &&
      local.foundry_endpoint == "https://${local.foundry_name}.services.ai.azure.com"
    )
    error_message = "The project must belong to the account; runtime inference must use its canonical account endpoint."
  }

  assert {
    condition = (
      azurerm_user_assigned_identity.web.principal_id != azurerm_user_assigned_identity.agent.principal_id &&
      azurerm_user_assigned_identity.web.location == var.location &&
      azurerm_user_assigned_identity.agent.location == var.location &&
      toset(keys(azurerm_role_assignment.acr_pull)) == toset(["web", "agent"]) &&
      azurerm_role_assignment.acr_pull["web"].principal_id == azurerm_user_assigned_identity.web.principal_id &&
      azurerm_role_assignment.acr_pull["agent"].principal_id == azurerm_user_assigned_identity.agent.principal_id &&
      alltrue([for assignment in azurerm_role_assignment.acr_pull :
        assignment.scope == azurerm_container_registry.main.id &&
        assignment.role_definition_name == "AcrPull" &&
        assignment.principal_type == "ServicePrincipal" &&
        assignment.skip_service_principal_aad_check
      ])
    )
    error_message = "Separate web/agent identities must each have only the registry-scoped AcrPull assignment."
  }

  assert {
    condition = (
      toset(keys(azurerm_role_assignment.foundry_inference)) == toset(["openai", "decision"]) &&
      azurerm_role_assignment.foundry_inference["openai"].role_definition_name == "Cognitive Services OpenAI User" &&
      azurerm_role_assignment.foundry_inference["decision"].role_definition_name == "Cognitive Services User" &&
      alltrue([for assignment in azurerm_role_assignment.foundry_inference :
        assignment.scope == azurerm_cognitive_account.main.id &&
        assignment.principal_id == azurerm_user_assigned_identity.agent.principal_id &&
        assignment.principal_type == "ServicePrincipal" &&
        assignment.skip_service_principal_aad_check
      ])
    )
    error_message = "Only the agent may receive account-scoped OpenAI and Decision inference roles."
  }

  assert {
    condition = (
      azurerm_cognitive_deployment.chat.name == "gpt-6-luna" &&
      azurerm_cognitive_deployment.chat.model[0].format == "OpenAI" &&
      azurerm_cognitive_deployment.chat.model[0].name == "gpt-6-luna" &&
      azurerm_cognitive_deployment.chat.model[0].version == var.chat_model_version &&
      azurerm_cognitive_deployment.decision.name == "Decision-1" &&
      azurerm_cognitive_deployment.decision.model[0].format == "Microsoft" &&
      azurerm_cognitive_deployment.decision.model[0].name == "Microsoft-Decision-1" &&
      azurerm_cognitive_deployment.decision.model[0].version == "1" &&
      azurerm_cognitive_deployment.chat.sku[0].name == "GlobalStandard" &&
      azurerm_cognitive_deployment.decision.sku[0].name == "DataZoneStandard" &&
      alltrue([for deployment in [azurerm_cognitive_deployment.chat, azurerm_cognitive_deployment.decision] :
        deployment.cognitive_account_id == azurerm_cognitive_account.main.id &&
        deployment.version_upgrade_option == "NoAutoUpgrade" &&
        deployment.sku[0].capacity == 1
      ])
    )
    error_message = "Both account deployments must preserve the selected models, explicit versions and default SKUs/capacity."
  }
}

run "custom_deployment_settings" {
  command = plan

  variables {
    chat_model_name              = "gpt-test"
    chat_model_version           = "custom-test-version"
    chat_deployment_name         = "gpt-chat-test"
    chat_deployment_sku          = "Standard"
    chat_deployment_capacity     = 7
    decision_deployment_name     = "decision-test"
    decision_deployment_sku      = "GlobalStandard"
    decision_deployment_capacity = 3
  }

  assert {
    condition = (
      azurerm_cognitive_deployment.chat.name == var.chat_deployment_name &&
      azurerm_cognitive_deployment.chat.model[0].name == var.chat_model_name &&
      azurerm_cognitive_deployment.chat.model[0].version == var.chat_model_version &&
      azurerm_cognitive_deployment.chat.sku[0].name == var.chat_deployment_sku &&
      azurerm_cognitive_deployment.chat.sku[0].capacity == var.chat_deployment_capacity &&
      azurerm_cognitive_deployment.decision.name == var.decision_deployment_name &&
      azurerm_cognitive_deployment.decision.sku[0].name == var.decision_deployment_sku &&
      azurerm_cognitive_deployment.decision.sku[0].capacity == var.decision_deployment_capacity
    )
    error_message = "Deployment names, model version, SKU and capacity must honor the caller's explicit inputs."
  }
}

run "optional_sol_model_picker_deployment" {
  command = plan

  variables {
    sol_model_version       = "sol-test-version"
    sol_deployment_capacity = 7
  }

  assert {
    condition = (
      azurerm_cognitive_deployment.sol[0].name == "gpt-6.1-sol" &&
      azurerm_cognitive_deployment.sol[0].model[0].name == "gpt-6.1-sol" &&
      azurerm_cognitive_deployment.sol[0].model[0].version == "sol-test-version" &&
      azurerm_cognitive_deployment.sol[0].sku[0].name == var.chat_deployment_sku &&
      azurerm_cognitive_deployment.sol[0].sku[0].capacity == 7 &&
      azurerm_cognitive_deployment.sol[0].version_upgrade_option == "NoAutoUpgrade"
    )
    error_message = "The Sol picker must resolve to its own pinned, quota-configured model deployment."
  }
}

run "reject_blank_sol_model_version" {
  command = plan
  variables {
    sol_model_version = ""
  }
  expect_failures = [var.sol_model_version]
}
