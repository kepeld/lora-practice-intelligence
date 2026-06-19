# Stable public address so the custom domain's A-record keeps resolving across
# instance restarts/replacements. Free while attached to a running instance.
resource "aws_eip" "this" {
  domain   = "vpc"
  instance = aws_instance.this.id
  tags     = { Project = var.project }
}
