package config

import (
	"fmt"
	"os"
	"time"
)

type Config struct {
	TelegramBotToken string
	TelegramChatID   string
	BrokerAPIKey     string
	BrokerAPISecret  string
	BrokerBaseURL    string
	HTTPPort         string
	RelayURL         string
	ScheduleTime     time.Time
}

func Load() (*Config, error) {
	cfg := &Config{
		TelegramBotToken: os.Getenv("TELEGRAM_BOT_TOKEN"),
		TelegramChatID:   os.Getenv("TELEGRAM_CHAT_ID"),
		BrokerAPIKey:     os.Getenv("BROKER_API_KEY"),
		BrokerAPISecret:  os.Getenv("BROKER_API_SECRET"),
		BrokerBaseURL:    os.Getenv("BROKER_BASE_URL"),
		HTTPPort:         getEnvOrDefault("HTTP_PORT", "8080"),
		RelayURL:         os.Getenv("RELAY_URL"),
	}

	if cfg.TelegramBotToken == "" {
		return nil, fmt.Errorf("TELEGRAM_BOT_TOKEN is required")
	}
	if cfg.TelegramChatID == "" {
		return nil, fmt.Errorf("TELEGRAM_CHAT_ID is required")
	}
	if cfg.RelayURL == "" {
		return nil, fmt.Errorf("RELAY_URL is required")
	}

	schedStr := getEnvOrDefault("SCHEDULE_TIME", "08:45")
	t, err := time.Parse("15:04", schedStr)
	if err != nil {
		return nil, fmt.Errorf("invalid SCHEDULE_TIME: %w", err)
	}
	cfg.ScheduleTime = t

	return cfg, nil
}

func getEnvOrDefault(key, defaultVal string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultVal
}
