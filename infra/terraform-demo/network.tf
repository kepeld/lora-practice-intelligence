# Public demo: the dashboard/API on :8000 is open to everyone (teachers click a
# link). It is read-only over the marts; the only write-ish path is /ask, which
# is rate-limited by using a cheap model. Qdrant (6333) stays internal — only the
# app container talks to it over the compose network. Shell access is via SSM.
resource "aws_security_group" "ec2" {
  name        = "${var.project}-sg"
  description = "ML Underground demo - public app, internal qdrant"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "public dashboard + API (direct, no TLS)"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP (ACME challenge + redirect to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS (Caddy TLS termination)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "all (GitHub / HuggingFace model / Anthropic / image pulls / S3)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = var.project }
}
