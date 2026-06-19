data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${var.project}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# SSM Session Manager (shell access without SSH / a key pair)
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Read-only on the data bucket: the box fetches the slim warehouse and presigns
# the Qdrant snapshots so Qdrant can pull them over HTTP.
data "aws_iam_policy_document" "app" {
  statement {
    sid     = "ReadSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.github_token.arn,
      aws_secretsmanager_secret.anthropic_api_key.arn,
    ]
  }
  statement {
    sid       = "DataBucket"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "${var.project}-app"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project}-profile"
  role = aws_iam_role.ec2.name
}
