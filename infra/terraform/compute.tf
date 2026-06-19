resource "aws_instance" "this" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  vpc_security_group_ids = [aws_security_group.ec2.id]

  root_block_device {
    volume_size = var.root_volume_gb
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    aws_region           = var.aws_region
    github_token_secret  = aws_secretsmanager_secret.github_token.name
    anthropic_secret     = aws_secretsmanager_secret.anthropic_api_key.name
    airflow_key_secret   = aws_secretsmanager_secret.airflow_secret_key.name
    repo_url             = var.repo_url
    repo_branch          = var.repo_branch
    anthropic_model      = var.anthropic_model
    data_bucket          = aws_s3_bucket.data.bucket
    publish_interval_min = var.publish_interval_min
  })
  user_data_replace_on_change = true

  tags = { Name = var.project, Project = var.project }
}
