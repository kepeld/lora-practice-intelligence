# Admin UIs (Airflow/Grafana/Prometheus, all default creds) reachable only from the
# operator IP. No public ports; SSH is via SSM Session Manager (no port 22, no key).
resource "aws_security_group" "ec2" {
  name        = "${var.project}-sg"
  description = "ML Underground pipeline + monitoring"
  vpc_id      = data.aws_vpc.default.id

  dynamic "ingress" {
    for_each = toset([8081, 3000, 9090])
    content {
      description = "admin UI ${ingress.value} (operator only)"
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = [var.operator_cidr]
    }
  }

  egress {
    description = "all (GitHub / HuggingFace / Anthropic / image pulls / S3)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = var.project }
}
