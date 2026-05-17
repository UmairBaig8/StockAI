package main

import (
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/anomalyco/stockai-relay/internal/broker"
	"github.com/anomalyco/stockai-relay/internal/config"
	"github.com/anomalyco/stockai-relay/internal/handler"
	"github.com/anomalyco/stockai-relay/internal/scheduler"
	"github.com/anomalyco/stockai-relay/internal/telegram"
	"github.com/anomalyco/stockai-relay/internal/token"
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	log.Println("StockAI 2FA Relay starting...")

	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("Config error: %v", err)
	}

	tgBot := telegram.NewBot(cfg.TelegramBotToken, cfg.TelegramChatID)
	tokenMgr := token.NewManager()
	brokerAPI := broker.NewMockAPI()
	h := handler.New(tokenMgr, brokerAPI, tgBot)

	sched := scheduler.New()
	sched.Register(
		"2fa-daily-prompt",
		cfg.ScheduleTime.Hour(),
		cfg.ScheduleTime.Minute(),
		func() {
			log.Println("Triggering daily 2FA notification...")
			if err := tgBot.Send2FANotification(cfg.RelayURL); err != nil {
				log.Printf("Failed to send 2FA notification: %v", err)
			}
		},
	)
	sched.Start()
	defer sched.Stop()

	mux := http.NewServeMux()
	mux.HandleFunc("/", h.ShowForm)
	mux.HandleFunc("/submit", h.SubmitTOTP)
	mux.HandleFunc("/health", h.Health)

	server := &http.Server{
		Addr:    ":" + cfg.HTTPPort,
		Handler: mux,
	}

	go func() {
		log.Printf("HTTP server listening on :%s", cfg.HTTPPort)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("HTTP server error: %v", err)
		}
	}()

	if err := tgBot.SendStatus("StockAI 2FA Relay is online. Awaiting daily schedule."); err != nil {
		log.Printf("Warning: Could not send startup status: %v", err)
	}

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Println("Shutting down...")
	server.Close()
}
