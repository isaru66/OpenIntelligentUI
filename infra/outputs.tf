output "AZURE_RESOURCE_GROUP" {
  description = "Resource group managed by this environment."
  value       = azurerm_resource_group.main.name
}

output "AZURE_CONTAINER_REGISTRY_NAME" {
  description = "ACR that builds and stores both application images."
  value       = azurerm_container_registry.main.name
}

output "AZURE_CONTAINER_REGISTRY_ENDPOINT" {
  description = "Private image registry login server."
  value       = azurerm_container_registry.main.login_server
}

output "SERVICE_WEB_ENDPOINT_URL" {
  description = "Public HTTPS Open Generative UI endpoint."
  value       = "https://${azurerm_container_app.web.ingress[0].fqdn}"
}

output "SERVICE_AGENT_ENDPOINT_URL" {
  description = "Agent HTTPS endpoint; reachable only inside the ACA environment."
  value       = "https://${azurerm_container_app.agent.ingress[0].fqdn}"
}

output "AZURE_AI_FOUNDRY_ENDPOINT" {
  description = "Foundry base endpoint used by the agent with Entra ID."
  value       = local.foundry_endpoint
}

output "AZURE_CHAT_DEPLOYMENT" {
  description = "Foundry chat deployment name sent as LLM_MODEL."
  value       = azurerm_cognitive_deployment.chat.name
}

output "AZURE_DECISION_DEPLOYMENT" {
  description = "Foundry Microsoft-Decision-1 deployment name."
  value       = azurerm_cognitive_deployment.decision.name
}
