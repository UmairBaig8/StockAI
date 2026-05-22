variable "aws_region" {
  default = "us-east-1"
}

variable "instance_type" {
  default = "t3.medium"
}

variable "allowed_telegram_id" {
  description = "Telegram user ID allowed to control the bot"
  sensitive   = true
}

variable "dev_bot_token" {
  description = "Telegram bot token for dev control"
  sensitive   = true
}

variable "auto_stop_minutes" {
  default = "30"
}

variable "code_server_password" {
  default = "stockai"
}

variable "code_server_port" {
  default = "8443"
}

# StockAI app env vars

variable "deepseek_api_key" {
  default   = ""
  sensitive = true
}

variable "gemini_api_key" {
  default   = ""
  sensitive = true
}

variable "openai_api_key" {
  default   = ""
  sensitive = true
}

variable "anthropic_api_key" {
  default   = ""
  sensitive = true
}

variable "aws_access_key_id" {
  default   = ""
  sensitive = true
}

variable "aws_secret_access_key" {
  default   = ""
  sensitive = true
}

variable "bedrock_model" {
  default = "us.anthropic.claude-sonnet-4-20250514-v1:0"
}

variable "telegram_bot_token" {
  default   = ""
  sensitive = true
}

variable "telegram_chat_id" {
  default = ""
}
