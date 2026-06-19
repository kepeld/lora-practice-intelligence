variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

variable "project" {
  type    = string
  default = "mlu-demo"
}

variable "instance_type" {
  description = "serves app (torch for /search) + qdrant; t3.medium (4GB) keeps both comfortable"
  type        = string
  default     = "t3.medium"
}

variable "root_volume_gb" {
  # the app image builds torch/sentence-transformers (~6GB) at boot
  type    = number
  default = 40
}

variable "repo_url" {
  description = "repo to clone on the instance, without scheme (token is prepended)"
  type        = string
  default     = "github.com/AvdieienkoDmytro/ua-palantir.git"
}

variable "repo_branch" {
  type    = string
  default = "main"
}

variable "rag_model" {
  description = "model for /ask; haiku is cheap for a public URL, set claude-opus-4-8 for richer answers"
  type        = string
  default     = "claude-haiku-4-5"
}

variable "domain" {
  description = "custom domain for TLS (e.g. ml-underground.xyz); empty falls back to <ip>.sslip.io"
  type        = string
  default     = ""
}
