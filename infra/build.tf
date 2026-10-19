locals {
  build_root     = abspath("${path.module}/..")
  build_platform = "linux/amd64"

  # The script and Terraform consume the SAME policy. Only these scoped files
  # are hashed/staged; Docker's ignore rules are defense in depth, not the
  # security boundary for uploading a working directory.
  build_context_policy = jsondecode(regex("# CONTEXT_POLICY=([^\n]+)", file("${path.module}/scripts/build-images.sh"))[0])
  build_sources = {
    for image, config in local.build_context_policy.images : image => {
      for source in sort(distinct(flatten([
        for pattern in concat(config.patterns, [config.dockerfile]) : tolist(fileset(local.build_root, pattern))
      ]))) : source => filesha256("${local.build_root}/${source}")
      if contains(local.build_context_policy.allow, source) || length(regexall(local.build_context_policy.exclude, source)) == 0
    }
  }
  build_hashes = {
    for image, sources in local.build_sources : image => sha256(join("\n", concat(
      [
        local.build_platform,
        filesha256("${path.module}/scripts/build-images.sh"),
        filesha256("${path.module}/scripts/preflight.sh"),
      ],
      [for source in sort(keys(sources)) : "${source}:${sources[source]}"]
    )))
  }
  built_images = {
    for image, hash in local.build_hashes : image => "${azurerm_container_registry.main.login_server}/${image}:${hash}"
  }
}

resource "terraform_data" "image_build" {
  for_each = local.build_sources

  triggers_replace = {
    fingerprint = local.build_hashes[each.key]
    registry_id = azurerm_container_registry.main.id
  }

  # Model access, regional availability and quota admission must succeed BEFORE
  # any paid remote build. Do not replace this with a best-effort CLI check.
  # Establish runtime roles first, giving RBAC the remote-build propagation window.
  depends_on = [
    azurerm_cognitive_deployment.chat,
    azurerm_cognitive_deployment.decision,
    azurerm_role_assignment.acr_pull,
    azurerm_role_assignment.foundry_inference,
  ]

  lifecycle {
    # IDs/names can be identical when a registry is destroyed and recreated.
    replace_triggered_by = [azurerm_container_registry.main]
  }

  provisioner "local-exec" {
    command     = "bash \"$BUILD_SCRIPT\""
    interpreter = ["bash", "-c"]
    working_dir = local.build_root
    environment = {
      BUILD_SCRIPT                 = "${local.build_root}/infra/scripts/build-images.sh"
      BUILD_ROOT                   = local.build_root
      BUILD_IMAGE                  = each.key
      BUILD_PLATFORM               = local.build_platform
      BUILD_FINGERPRINT            = local.build_hashes[each.key]
      BUILD_SOURCES_JSON           = jsonencode(each.value)
      SUBSCRIPTION_ID              = var.subscription_id
      REGISTRY_NAME                = azurerm_container_registry.main.name
      REGISTRY_ID                  = azurerm_container_registry.main.id
      FOUNDRY_LOCATION             = var.foundry_location
      CHAT_MODEL_NAME              = var.chat_model_name
      CHAT_MODEL_VERSION           = var.chat_model_version
      CHAT_DEPLOYMENT_SKU          = var.chat_deployment_sku
      CHAT_DEPLOYMENT_CAPACITY     = tostring(var.chat_deployment_capacity)
      DECISION_DEPLOYMENT_SKU      = var.decision_deployment_sku
      DECISION_DEPLOYMENT_CAPACITY = tostring(var.decision_deployment_capacity)
      CHAT_DEPLOYMENT_ID           = azurerm_cognitive_deployment.chat.id
      DECISION_DEPLOYMENT_ID       = azurerm_cognitive_deployment.decision.id
    }
  }
}
