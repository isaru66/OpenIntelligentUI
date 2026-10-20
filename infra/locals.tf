locals {
  resource_token = substr(sha256("${var.subscription_id}:${var.environment_name}"), 0, 8)
  name_base      = "ogui-${var.environment_name}"
  registry_name  = "acrogui${replace(var.environment_name, "-", "")}${local.resource_token}"
  foundry_name   = "ai-${local.name_base}-${local.resource_token}"

  # Reserve 10 of ACA's 32 characters for "aca-" and "-agent".
  container_app_name_base = length(local.name_base) <= 22 ? local.name_base : "${trimsuffix(substr(local.name_base, 0, 13), "-")}-${local.resource_token}"
  container_app_names = {
    web   = "aca-${local.container_app_name_base}-web"
    agent = "aca-${local.container_app_name_base}-agent"
  }

  tags = {
    "azd-env-name" = var.environment_name
    env            = var.environment_name
    application    = "open-generative-ui"
    managed_by     = "terraform"
  }
}
