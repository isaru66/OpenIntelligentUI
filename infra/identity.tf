resource "azurerm_user_assigned_identity" "web" {
  name                = "id-${local.name_base}-web"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "agent" {
  name                = "id-${local.name_base}-agent"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  for_each = {
    web   = azurerm_user_assigned_identity.web.principal_id
    agent = azurerm_user_assigned_identity.agent.principal_id
  }

  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = each.value
  principal_type       = "ServicePrincipal"

  # Newly created managed identities may not yet be visible in Entra ID.
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "foundry_inference" {
  for_each = {
    openai   = "Cognitive Services OpenAI User"
    decision = "Cognitive Services User"
  }

  # Inference is granted only to the agent and only on this Foundry account.
  # Decision requires Cognitive Services User; no Contributor/Owner runtime role
  # is needed. Local authentication remains disabled even though that built-in
  # role includes listKeys permission.
  scope                            = azurerm_cognitive_account.main.id
  role_definition_name             = each.value
  principal_id                     = azurerm_user_assigned_identity.agent.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}
