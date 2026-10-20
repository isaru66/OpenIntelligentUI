resource "azurerm_cognitive_account" "main" {
  name                          = local.foundry_name
  resource_group_name           = azurerm_resource_group.main.name
  location                      = var.foundry_location
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = local.foundry_name
  project_management_enabled    = true
  local_auth_enabled            = false
  public_network_access_enabled = true
  tags                          = local.tags

  # Foundry projects require an account identity; application inference uses the
  # separate agent user-assigned identity, not this control-plane identity.
  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_account_project" "main" {
  name                 = "proj-${local.name_base}"
  cognitive_account_id = azurerm_cognitive_account.main.id
  location             = azurerm_cognitive_account.main.location
  display_name         = "Open Generative UI"
  description          = "Chat and decision model deployments for Open Generative UI."
  tags                 = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_deployment" "chat" {
  name                   = var.chat_deployment_name
  cognitive_account_id   = azurerm_cognitive_account.main.id
  version_upgrade_option = "NoAutoUpgrade"

  model {
    format  = "OpenAI"
    name    = var.chat_model_name
    version = var.chat_model_version
  }

  sku {
    name     = var.chat_deployment_sku
    capacity = var.chat_deployment_capacity
  }
}

resource "azurerm_cognitive_deployment" "decision" {
  name                   = var.decision_deployment_name
  cognitive_account_id   = azurerm_cognitive_account.main.id
  version_upgrade_option = "NoAutoUpgrade"

  model {
    format  = "Microsoft"
    name    = "Microsoft-Decision-1"
    version = "1"
  }

  sku {
    name     = var.decision_deployment_sku
    capacity = var.decision_deployment_capacity
  }

  # The account API can reject concurrent deployment writes with a conflict.
  depends_on = [azurerm_cognitive_deployment.chat]
}

resource "azurerm_cognitive_deployment" "sol" {
  count                  = var.sol_model_version == null ? 0 : 1
  name                   = "gpt-6.1-sol"
  cognitive_account_id   = azurerm_cognitive_account.main.id
  version_upgrade_option = "NoAutoUpgrade"

  model {
    format  = "OpenAI"
    name    = "gpt-6.1-sol"
    version = var.sol_model_version
  }

  sku {
    name     = var.chat_deployment_sku
    capacity = var.sol_deployment_capacity
  }

  depends_on = [azurerm_cognitive_deployment.decision]
}

locals {
  # Use the account-level AzureCloud endpoint for both /openai/v1 and
  # /providers/microsoft/v1/systemone, not the project's endpoint.
  foundry_endpoint = "https://${azurerm_cognitive_account.main.custom_subdomain_name}.services.ai.azure.com"
}
