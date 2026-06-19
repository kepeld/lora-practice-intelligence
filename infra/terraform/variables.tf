variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

variable "project" {
  type    = string
  default = "ml-underground"
}

variable "operator_cidr" {
  description = "your public IP as <ip>/32 — restricts the Airflow/Grafana/Prometheus UIs to you"
  type        = string
}

variable "instance_type" {
  description = "8 services incl one torch image build at boot — t3.xlarge (16GB) is the safe demo size"
  type        = string
  default     = "t3.xlarge"
}

variable "root_volume_gb" {
  # torch/CUDA airflow image is ~6.7GB and compose builds it for 3 services;
  # 40GB ran out during unpack, so 100GB for headroom (gp3, pennies/hr)
  type    = number
  default = 100
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

variable "anthropic_model" {
  type    = string
  default = "claude-haiku-4-5"
}

variable "publish_interval_min" {
  description = "how often the cron pushes the DuckDB warehouse to S3"
  type        = number
  default     = 30
}
