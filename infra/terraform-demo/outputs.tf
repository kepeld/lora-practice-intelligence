output "instance_id" {
  value = aws_instance.this.id
}

output "public_ip" {
  value = aws_eip.this.public_ip
}

output "elastic_ip" {
  description = "stable public IP — point the domain's A-record at this"
  value       = aws_eip.this.public_ip
}

output "app_url_https" {
  description = "TLS link to send the teachers"
  value       = var.domain != "" ? "https://${var.domain}" : "https://${aws_eip.this.public_ip}.sslip.io"
}

output "app_url" {
  description = "direct, no-TLS fallback"
  value       = "http://${aws_eip.this.public_ip}:8000"
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "upload_payload" {
  description = "stage the demo payload, then apply the instance"
  value = join("\n", [
    "aws s3 cp ML_UNDERGROUND.duckdb        s3://${aws_s3_bucket.data.bucket}/ML_UNDERGROUND.duckdb",
    "aws s3 cp github_repos.snapshot        s3://${aws_s3_bucket.data.bucket}/github_repos.snapshot",
    "aws s3 cp huggingface_models.snapshot  s3://${aws_s3_bucket.data.bucket}/huggingface_models.snapshot",
  ])
}

output "ssm_start_session" {
  description = "shell into the box (no SSH key needed)"
  value       = "aws ssm start-session --target ${aws_instance.this.id} --region ${var.aws_region}"
}
