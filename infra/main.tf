resource "azurerm_resource_group" "main" {
  name     = "rg-${local.name_base}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_container_registry" "main" {
  name                                         = local.registry_name
  resource_group_name                          = azurerm_resource_group.main.name
  location                                     = var.location
  sku                                          = "Basic"
  admin_enabled                                = false
  azuread_authentication_as_arm_policy_enabled = true
  role_assignment_mode                         = "LegacyRegistryPermissions"
  tags                                         = local.tags
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${local.name_base}"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${local.name_base}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags
}
