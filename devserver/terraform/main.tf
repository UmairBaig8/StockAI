terraform {
  required_version = ">= 1.5"
  required_providers {
    aws   = { source = "hashicorp/aws", version = "~> 5.0" }
    tls   = { source = "hashicorp/tls" }
    local = { source = "hashicorp/local" }
  }
}

provider "aws" {
  region  = var.aws_region
}

# ── Keypair ──
resource "tls_private_key" "devserver" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "devserver" {
  key_name   = "stockai-devserver-key"
  public_key = tls_private_key.devserver.public_key_openssh
}

resource "local_file" "private_key" {
  content  = tls_private_key.devserver.private_key_pem
  filename = "${path.module}/devserver-key.pem"
}

# ── Security Group ──
resource "aws_security_group" "devserver" {
  name        = "stockai-devserver-sg"
  description = "StockAI DevServer: SSH + Code-Server + App API"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "SSH"
  }

  ingress {
    from_port   = tonumber(var.code_server_port)
    to_port     = tonumber(var.code_server_port)
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Code Server"
  }

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "StockAI Dashboard"
  }

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "StockAI Orchestrator"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "stockai-devserver" }
}

# ── IAM Role (for bot to query instance IP) ──
resource "aws_iam_role" "devserver" {
  name = "stockai-devserver-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "devserver" {
  name = "stockai-devserver-policy"
  role = aws_iam_role.devserver.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ec2:DescribeInstances"]
      Resource = "*"
    }]
  })
}

resource "aws_iam_instance_profile" "devserver" {
  name = "stockai-devserver-profile"
  role = aws_iam_role.devserver.name
}

# ── AMI ──
data "aws_ami" "ubuntu" {
  most_recent = true
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
  owners = ["099720109477"] # Canonical
}

# ── EC2 ──
resource "aws_instance" "devserver" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name              = aws_key_pair.devserver.key_name
  vpc_security_group_ids = [aws_security_group.devserver.id]
  iam_instance_profile   = aws_iam_instance_profile.devserver.name

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
  }

  user_data = templatefile("${path.module}/../scripts/setup.sh", {
    dev_bot_token        = var.dev_bot_token
    allowed_telegram_id  = var.allowed_telegram_id
    auto_stop_minutes    = var.auto_stop_minutes
    code_server_password = var.code_server_password
    code_server_port     = var.code_server_port
    deepseek_api_key     = var.deepseek_api_key
    gemini_api_key       = var.gemini_api_key
    openai_api_key       = var.openai_api_key
    anthropic_api_key    = var.anthropic_api_key
    aws_access_key_id    = var.aws_access_key_id
    aws_secret_access_key = var.aws_secret_access_key
    bedrock_model        = var.bedrock_model
    telegram_bot_token   = var.telegram_bot_token
    telegram_chat_id     = var.telegram_chat_id
  })

  tags = { Name = "stockai-devserver" }
}

# ── Elastic IP ──
resource "aws_eip" "devserver" {
  instance = aws_instance.devserver.id
  tags     = { Name = "stockai-devserver-eip" }
}

# ── Outputs ──
output "public_ip" {
  value = aws_eip.devserver.public_ip
}

output "code_server_url" {
  value = "http://${aws_eip.devserver.public_ip}:${var.code_server_port}"
}

output "stockai_dashboard" {
  value = "http://${aws_eip.devserver.public_ip}:8000"
}

output "ssh_command" {
  value = "ssh -i ${abspath(local_file.private_key.filename)} ubuntu@${aws_eip.devserver.public_ip}"
}

# ═══════════════════════════════════════════════════════
# Market Hours Auto Start/Stop Scheduler
# ═══════════════════════════════════════════════════════

# ── Scheduler Lambda ──
resource "aws_iam_role" "scheduler" {
  name = "stockai-devserver-scheduler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "stockai-devserver-scheduler-policy"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ec2:StartInstances",
          "ec2:StopInstances",
          "ec2:DescribeInstances",
          "ec2:AssociateAddress",
          "ec2:DescribeAddresses",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:CreateSnapshot",
          "ec2:DescribeSnapshots",
          "ec2:DeleteSnapshot",
          "ec2:DescribeVolumes",
          "ec2:CreateTags",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "*"
      },
    ]
  })
}

data "archive_file" "scheduler_zip" {
  type        = "zip"
  source_file = "${path.module}/scheduler.py"
  output_path = "${path.module}/scheduler.zip"
}

resource "aws_lambda_function" "scheduler" {
  filename         = data.archive_file.scheduler_zip.output_path
  function_name    = "stockai-devserver-scheduler"
  role             = aws_iam_role.scheduler.arn
  handler          = "scheduler.handler"
  runtime          = "python3.13"
  timeout          = 120
  source_code_hash = data.archive_file.scheduler_zip.output_base64sha256

  environment {
    variables = {
      INSTANCE_ID             = aws_instance.devserver.id
      EIP_ALLOCATION_ID       = aws_eip.devserver.allocation_id
      SNAPSHOT_RETENTION_DAYS = "30"
    }
  }
}

# ── EventBridge Scheduler ──
resource "aws_iam_role" "scheduler_events" {
  name = "stockai-devserver-scheduler-events-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_events" {
  name = "stockai-devserver-scheduler-events-policy"
  role = aws_iam_role.scheduler_events.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = [aws_lambda_function.scheduler.arn]
    }]
  })
}

# 8:30 AM IST = 3:00 AM UTC (Mon-Fri)
resource "aws_scheduler_schedule" "start" {
  name                = "stockai-devserver-start"
  schedule_expression = "cron(0 3 ? * MON-FRI *)"
  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_lambda_function.scheduler.arn
    role_arn = aws_iam_role.scheduler_events.arn
    input    = jsonencode({ action = "start" })
  }
}

# 3:30 PM IST = 10:00 AM UTC (Mon-Fri)
resource "aws_scheduler_schedule" "stop" {
  name                = "stockai-devserver-stop"
  schedule_expression = "cron(0 10 ? * MON-FRI *)"
  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_lambda_function.scheduler.arn
    role_arn = aws_iam_role.scheduler_events.arn
    input    = jsonencode({ action = "stop" })
  }
}
