variable "environment_name" {
  description = "azd environment name, used in resource names."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}[a-z0-9]$", var.environment_name)) && !strcontains(var.environment_name, "--")
    error_message = "Use 3-20 lowercase letters, digits or single hyphens, starting with a letter and ending with a letter or digit."
  }
}

variable "subscription_id" {
  description = "Target Azure subscription; never inferred from the developer's default."
  type        = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be an Azure subscription UUID."
  }
}

variable "location" {
  description = "Azure region for ACA, ACR and logging (for example eastus2)."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]+$", var.location))
    error_message = "Supply an Azure region name without spaces."
  }
}

variable "foundry_location" {
  description = "Azure region supporting both selected Foundry models and deployment SKUs."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]+$", var.foundry_location))
    error_message = "Supply a supported Foundry region name without spaces."
  }
}

variable "chat_model_name" {
  description = "Foundry OpenAI chat model. Verify regional availability before provisioning."
  type        = string
  default     = "gpt-6-luna"
  validation {
    condition     = can(regex("^gpt-[A-Za-z0-9._-]+$", var.chat_model_name))
    error_message = "Use a supported gpt-* Foundry model name."
  }
}

variable "chat_model_version" {
  description = "Explicit chat model version from the target region's Foundry catalog; no guessed default."
  type        = string
  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._-]*$", var.chat_model_version))
    error_message = "Supply the exact nonempty model version from the Foundry catalog."
  }
}

variable "chat_deployment_name" {
  description = "Chat deployment name sent as LLM_MODEL; must match the existing app's gpt-* routing."
  type        = string
  default     = "gpt-6-luna"
  validation {
    condition     = can(regex("^gpt-[A-Za-z0-9._-]+$", var.chat_deployment_name)) && length(var.chat_deployment_name) <= 64
    error_message = "Use a gpt-* deployment name of at most 64 characters."
  }
}

variable "chat_deployment_sku" {
  description = "Chat deployment SKU; must be available in the selected region."
  type        = string
  default     = "GlobalStandard"
  validation {
    condition     = contains(["GlobalStandard", "DataZoneStandard", "Standard"], var.chat_deployment_sku)
    error_message = "Use GlobalStandard, DataZoneStandard or Standard."
  }
}

variable "chat_deployment_capacity" {
  description = "Chat model capacity units; subject to model/SKU/subscription quota."
  type        = number
  default     = 1
  validation {
    condition     = var.chat_deployment_capacity >= 1 && floor(var.chat_deployment_capacity) == var.chat_deployment_capacity
    error_message = "Chat deployment capacity must be a positive integer."
  }
}

variable "sol_model_version" {
  description = "Exact gpt-6.1-sol catalog version; null disables the optional model-picker deployment."
  type        = string
  default     = null
  validation {
    condition = var.sol_model_version == null || (
      can(regex("^[A-Za-z0-9][A-Za-z0-9._-]*$", var.sol_model_version)) &&
      var.chat_deployment_name != "gpt-6.1-sol" && var.decision_deployment_name != "gpt-6.1-sol"
    )
    error_message = "Supply an exact nonempty Sol version and reserve gpt-6.1-sol as its deployment name."
  }
}

variable "sol_deployment_capacity" {
  description = "Optional gpt-6.1-sol capacity units; verify regional quota before enabling."
  type        = number
  default     = 1
  validation {
    condition     = var.sol_deployment_capacity >= 1 && floor(var.sol_deployment_capacity) == var.sol_deployment_capacity
    error_message = "Sol deployment capacity must be a positive integer."
  }
}

variable "decision_deployment_name" {
  description = "Microsoft-Decision-1 deployment name sent as AZURE_DECISION_DEPLOYMENT."
  type        = string
  default     = "Decision-1"
  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", var.decision_deployment_name)) && var.decision_deployment_name != var.chat_deployment_name
    error_message = "Use a deployment name of at most 64 letters, digits, dots, underscores or hyphens, distinct from the chat deployment."
  }
}

variable "decision_deployment_sku" {
  description = "Microsoft-Decision-1 SKU supported in the selected Foundry region."
  type        = string
  default     = "DataZoneStandard"
  validation {
    condition     = contains(["GlobalStandard", "DataZoneStandard"], var.decision_deployment_sku)
    error_message = "Use GlobalStandard or DataZoneStandard."
  }
}

variable "decision_deployment_capacity" {
  description = "Microsoft-Decision-1 model capacity units."
  type        = number
  default     = 1
  validation {
    condition     = var.decision_deployment_capacity >= 1 && floor(var.decision_deployment_capacity) == var.decision_deployment_capacity
    error_message = "Decision deployment capacity must be a positive integer."
  }
}

variable "webiq_api_key" {
  description = "Existing WebIQ API key, retained in local Terraform state; supply TF_VAR_webiq_api_key at runtime."
  type        = string
  sensitive   = true
  validation {
    condition     = length(trimspace(var.webiq_api_key)) > 0
    error_message = "Provide a nonempty WebIQ API key through the runtime environment."
  }
}

variable "webiq_endpoint" {
  description = "Existing WebIQ HTTPS search endpoint."
  type        = string
  default     = "https://api.microsoft.ai/v3/search/web"
  validation {
    condition     = can(regex("^https://[^/?#[:space:]]+(/[^[:space:]]*)?$", var.webiq_endpoint))
    error_message = "WebIQ endpoint must be an HTTPS URL without whitespace."
  }
}

variable "web_resources" {
  description = "Web consumption resources; memory is twice CPU in GiB. State/rate limiting are process-local."
  type = object({
    cpu          = number
    min_replicas = number
    max_replicas = number
  })
  default = { cpu = 0.5, min_replicas = 1, max_replicas = 1 }
  validation {
    condition = contains([0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2], var.web_resources.cpu) && (
      var.web_resources.min_replicas >= 0 && var.web_resources.max_replicas >= 1 &&
      var.web_resources.min_replicas <= var.web_resources.max_replicas &&
      var.web_resources.max_replicas <= 10 &&
      floor(var.web_resources.min_replicas) == var.web_resources.min_replicas &&
      floor(var.web_resources.max_replicas) == var.web_resources.max_replicas
    )
    error_message = "Use CPU 0.25-2 in 0.25 steps and integer replica limits 0 <= min <= max <= 10, max >= 1."
  }
}

variable "agent_resources" {
  description = "Agent consumption resources; memory is twice CPU in GiB. Checkpoints are process-local."
  type = object({
    cpu          = number
    min_replicas = number
    max_replicas = number
  })
  default = { cpu = 1, min_replicas = 1, max_replicas = 1 }
  validation {
    condition = contains([0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2], var.agent_resources.cpu) && (
      var.agent_resources.min_replicas >= 0 && var.agent_resources.max_replicas >= 1 &&
      var.agent_resources.min_replicas <= var.agent_resources.max_replicas &&
      var.agent_resources.max_replicas <= 10 &&
      floor(var.agent_resources.min_replicas) == var.agent_resources.min_replicas &&
      floor(var.agent_resources.max_replicas) == var.agent_resources.max_replicas
    )
    error_message = "Use CPU 0.25-2 in 0.25 steps and integer replica limits 0 <= min <= max <= 10, max >= 1."
  }
}
