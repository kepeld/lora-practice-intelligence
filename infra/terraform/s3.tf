resource "random_id" "suffix" {
  byte_length = 4
}

# The pipeline publishes ML_UNDERGROUND.duckdb here; Dmytro downloads it (presigned URL).
# Persists cheaply across EC2 teardown so the last snapshot stays downloadable.
resource "aws_s3_bucket" "data" {
  bucket        = "${var.project}-data-${random_id.suffix.hex}"
  force_destroy = true
  tags          = { Project = var.project }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
