resource "random_id" "suffix" {
  byte_length = 4
}

# Staging bucket for the demo payload the operator uploads: the slim warehouse
# (ML_UNDERGROUND.duckdb) and the two Qdrant snapshots. Private — the instance
# role reads it. force_destroy so teardown is clean.
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
