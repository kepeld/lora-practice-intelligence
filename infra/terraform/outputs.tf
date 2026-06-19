output "instance_id" {
  value = aws_instance.this.id
}

output "public_ip" {
  value = aws_instance.this.public_ip
}

output "airflow_url" {
  value = "http://${aws_instance.this.public_ip}:8081"
}

output "grafana_url" {
  value = "http://${aws_instance.this.public_ip}:3000"
}

output "prometheus_url" {
  value = "http://${aws_instance.this.public_ip}:9090"
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "ssm_start_session" {
  description = "shell into the box (no SSH key needed)"
  value       = "aws ssm start-session --target ${aws_instance.this.id} --region ${var.aws_region}"
}

output "presign_duckdb" {
  description = "run this to get a 7-day download link to send Dmytro"
  value       = "aws s3 presign s3://${aws_s3_bucket.data.bucket}/data/ML_UNDERGROUND.duckdb --expires-in 604800"
}
