resource "terraform_data" "webiq_secret_revision" {
  triggers_replace = sha256(var.webiq_api_key)
}

resource "azurerm_container_app" "agent" {
  name                         = local.container_app_names.agent
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = merge(local.tags, { "azd-service-name" = "agent" })

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.agent.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.agent.id
  }

  secret {
    name  = "webiq-api-key"
    value = var.webiq_api_key
  }

  ingress {
    external_enabled           = false
    allow_insecure_connections = false
    target_port                = 8123
    transport                  = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas                     = var.agent_resources.min_replicas
    max_replicas                     = var.agent_resources.max_replicas
    termination_grace_period_seconds = 30

    container {
      name   = "agent"
      image  = local.built_images.agent
      cpu    = var.agent_resources.cpu
      memory = "${var.agent_resources.cpu * 2}Gi"

      dynamic "env" {
        for_each = {
          PORT                      = "8123"
          AZURE_AI_FOUNDRY_ENABLED  = "true"
          AZURE_AI_FOUNDRY_ENDPOINT = local.foundry_endpoint
          AZURE_SUBSCRIPTION_ID     = var.subscription_id
          AZURE_TENANT_ID           = data.azurerm_client_config.current.tenant_id
          AZURE_CLIENT_ID           = azurerm_user_assigned_identity.agent.client_id
          LLM_MODEL                 = var.chat_deployment_name
          AZURE_DECISION_DEPLOYMENT = var.decision_deployment_name
          WEBIQ_ENDPOINT            = var.webiq_endpoint
          WEBIQ_SECRET_REVISION     = terraform_data.webiq_secret_revision.id
        }
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name        = "WEBIQ_API_KEY"
        secret_name = "webiq-api-key"
      }

      startup_probe {
        transport               = "HTTP"
        port                    = 8123
        path                    = "/health"
        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 30
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 8123
        path                    = "/health"
        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 5
        success_count_threshold = 1
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = 8123
        path                    = "/health"
        initial_delay           = 30
        interval_seconds        = 30
        timeout                 = 5
        failure_count_threshold = 3
      }
    }
  }

  depends_on = [
    terraform_data.image_build["agent"],
    azurerm_role_assignment.acr_pull["agent"],
    azurerm_role_assignment.foundry_inference,
  ]
}

resource "azurerm_container_app" "web" {
  name                         = local.container_app_names.web
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = merge(local.tags, { "azd-service-name" = "web" })

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.web.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.web.id
  }

  ingress {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 3000
    transport                  = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas                     = var.web_resources.min_replicas
    max_replicas                     = var.web_resources.max_replicas
    termination_grace_period_seconds = 30

    container {
      name   = "web"
      image  = local.built_images.web
      cpu    = var.web_resources.cpu
      memory = "${var.web_resources.cpu * 2}Gi"

      env {
        name  = "LANGGRAPH_DEPLOYMENT_URL"
        value = "https://${azurerm_container_app.agent.ingress[0].fqdn}"
      }

      env {
        name  = "APP_URL"
        value = "https://${local.container_app_names.web}.${azurerm_container_app_environment.main.default_domain}"
      }

      startup_probe {
        transport               = "HTTP"
        port                    = 3000
        path                    = "/api/health"
        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 30
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 3000
        path                    = "/api/health"
        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 5
        success_count_threshold = 1
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = 3000
        path                    = "/api/health"
        initial_delay           = 30
        interval_seconds        = 30
        timeout                 = 5
        failure_count_threshold = 3
      }
    }
  }

  depends_on = [
    terraform_data.image_build["web"],
    azurerm_role_assignment.acr_pull["web"],
  ]
}
