package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
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
	"github.com/redis/go-redis/v9"
)

type TradeSignal struct {
	Ticker    string  `json:"ticker"`
	Exchange  string  `json:"exchange"`
	Direction string  `json:"direction"`
	Quantity  int     `json:"quantity"`
	Price     float64 `json:"price"`
	Reason    string  `json:"reason"`
	Timestamp string  `json:"timestamp"`
}

type TradeResult struct {
	OrderID    string  `json:"order_id"`
	Ticker     string  `json:"ticker"`
	Direction  string  `json:"direction"`
	EntryPrice float64 `json:"entry_price"`
	ExitPrice  float64 `json:"exit_price"`
	Quantity   int     `json:"quantity"`
	PnLPct     float64 `json:"pnl_percent"`
	Status     string  `json:"status"`
	Timestamp  string  `json:"timestamp"`
}

type PreTradeQuery struct {
	Ticker      string  `json:"ticker"`
	MarketState struct {
		RSI             float64 `json:"rsi"`
		MACDHistogram   float64 `json:"macd_histogram"`
		VolumeZScore    float64 `json:"volume_z_score"`
		SectorTrend     float64 `json:"sector_trend"`
		PriceVelocity5m float64 `json:"price_velocity_5m"`
		TrendProfile1h  float64 `json:"trend_profile_1h"`
	} `json:"market_state"`
}

type PreTradeResult struct {
	Matched        bool    `json:"matched"`
	Similarity     float64 `json:"similarity"`
	CorrectionRule string  `json:"correction_rule,omitempty"`
	PastMistake    string  `json:"past_mistake,omitempty"`
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	log.Println("StockAI Orchestrator starting...")

	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("Config error: %v", err)
	}

	redisAddr := os.Getenv("REDIS_ADDR")
	if redisAddr == "" {
		redisAddr = "127.0.0.1:6379"
	}
	memoryURL := os.Getenv("MEMORY_URL")
	if memoryURL == "" {
		memoryURL = "http://127.0.0.1:8000"
	}

	tgBot := telegram.NewBot(cfg.TelegramBotToken, cfg.TelegramChatID)
	tokenMgr := token.NewManager()
	brokerAPI := broker.NewMockAPI()

	rdb := redis.NewClient(&redis.Options{
		Addr:     redisAddr,
		Password: os.Getenv("REDIS_PASSWORD"),
		DB:       0,
	})
	ctx := context.Background()

	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Printf("Warning: Redis not available: %v", err)
	} else {
		log.Println("Redis connected")
	}

	h := handler.New(tokenMgr, brokerAPI, tgBot, rdb)

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
	sched.Register(
		"daily-pnl-report",
		15, 30,
		func() {
			log.Println("Generating daily P&L report...")
			sendDailyReport(tgBot, memoryURL)
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

	if err := tgBot.SendStatus("StockAI Orchestrator online. Redis: " + redisAddr); err != nil {
		log.Printf("Warning: Startup notification failed: %v", err)
	}

	go signalLoop(ctx, rdb, tgBot, memoryURL)

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Println("Shutting down...")
	server.Close()
	rdb.Close()
}

func signalLoop(ctx context.Context, rdb *redis.Client, tg *telegram.Bot, memoryURL string) {
	pubsub := rdb.Subscribe(ctx, "trade:result")
	defer pubsub.Close()

	log.Println("Subscribed to trade:result")

	ch := pubsub.Channel()
	for {
		select {
		case msg := <-ch:
			if msg == nil {
				continue
			}
			var result TradeResult
			if err := json.Unmarshal([]byte(msg.Payload), &result); err != nil {
				log.Printf("Invalid trade result: %v", err)
				continue
			}

			if result.Status == "LOSS" {
				log.Printf("Loss detected: %s %.2f%% — running postmortem...", result.Ticker, result.PnLPct)
				runPostMortem(result, memoryURL)
				tg.SendTradeAlert(result.Ticker, result.Direction, result.EntryPrice, result.ExitPrice, result.Quantity, result.PnLPct, result.Status)
			} else if result.Status == "WIN" {
				tg.SendTradeAlert(result.Ticker, result.Direction, result.EntryPrice, result.ExitPrice, result.Quantity, result.PnLPct, result.Status)
			} else {
				log.Printf("Trade: %s %s @ %.2f [%s]", result.Ticker, result.Direction, result.EntryPrice, result.Status)
			}
			pushTradeToDash(result, memoryURL)

		case <-ctx.Done():
			return
		}
	}
}
	pushTradeToDash(result, memoryURL)

	resp.Body.Close()
}

func sendDailyReport(tg *telegram.Bot, memoryURL string) {
	resp, err := http.Get(memoryURL + "/api/v1/dash")
	if err != nil {
		log.Printf("Daily report fetch error: %v", err)
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	var dash struct {
		Summary struct {
			TotalTrades int     `json:"total_trades"`
			Wins        int     `json:"wins"`
			Losses      int     `json:"losses"`
			PnL         float64 `json:"pnl"`
			PnLPercent  float64 `json:"pnl_percent"`
		} `json:"summary"`
		Trades []struct {
			Ticker string  `json:"ticker"`
			Pnl    float64 `json:"pnl"`
		} `json:"trades"`
		Entries int `json:"entries"`
	}

	if err := json.Unmarshal(body, &dash); err != nil {
		log.Printf("Daily report parse error: %v", err)
		return
	}

	best := ""
	worst := ""
	bestPnl := 0.0
	worstPnl := 0.0
	for _, t := range dash.Trades {
		if t.Pnl > bestPnl {
			bestPnl = t.Pnl
			best = t.Ticker
		}
		if t.Pnl < worstPnl {
			worstPnl = t.Pnl
			worst = t.Ticker
		}
	}

	tg.SendDailyReport(
		dash.Summary.TotalTrades,
		dash.Summary.Wins,
		dash.Summary.Losses,
		dash.Summary.PnL,
		dash.Summary.PnLPercent,
		best,
		worst,
		dash.Entries,
	)
	log.Println("Daily P&L report sent")
}
	}
}

func fetchMarketState(ticker string, memoryURL string) map[string]float64 {
	resp, err := http.Get(fmt.Sprintf("%s/api/v1/quote/%s", memoryURL, ticker))
	if err != nil {
		log.Printf("Quote fetch failed for %s: %v", ticker, err)
		return nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil
	}

	body, _ := io.ReadAll(resp.Body)
	var quote struct {
		LastPrice float64 `json:"last_price"`
		Bid       float64 `json:"bid"`
		Ask       float64 `json:"ask"`
		Volume    float64 `json:"volume"`
		Trend     string  `json:"trend"`
	}
	if err := json.Unmarshal(body, &quote); err != nil {
		return nil
	}

	mid := (quote.Bid + quote.Ask) / 2
	spread := math.Abs(quote.Ask-quote.Bid) / mid

	trendVal := 0.0
	if quote.Trend == "up" {
		trendVal = 0.3
	} else {
		trendVal = -0.3
	}

	volScore := 0.0
	if quote.Volume > 0 {
		volScore = math.Min(math.Log10(quote.Volume)/7.0, 1.0)
	}

	return map[string]float64{
		"rsi":               50.0,
		"macd_histogram":    spread * 100,
		"volume_z_score":    volScore,
		"sector_trend":      trendVal,
		"price_velocity_5m": spread * 10,
		"trend_profile_1h":  trendVal,
	}
}

func runPostMortem(result TradeResult, memoryURL string) {
	dir := result.Direction
	if dir == "BUY" {
		dir = "LONG"
	} else if dir == "SELL" {
		dir = "SHORT"
	}

	marketState := fetchMarketState(result.Ticker, memoryURL)
	if marketState == nil {
		marketState = map[string]float64{
			"rsi": 50, "macd_histogram": 0, "volume_z_score": 0,
			"sector_trend": 0, "price_velocity_5m": 0, "trend_profile_1h": 0,
		}
	}

	payload := map[string]any{
		"market_state":    marketState,
		"trade_execution": map[string]any{
			"ticker":      result.Ticker,
			"exchange":    "NSE",
			"direction":   dir,
			"entry_price": result.EntryPrice,
			"exit_price":  result.ExitPrice,
			"quantity":    result.Quantity,
			"pnl_percent": result.PnLPct,
		},
		"strategy_intent": map[string]any{
			"core_rule":       "Breakout buy above previous day high",
			"indicators_used": []string{"RSI", "MACD", "Volume"},
		},
	}

	body, _ := json.Marshal(payload)
	resp, err := http.Post(memoryURL+"/api/v1/postmortem", "application/json", bytes.NewReader(body))

	if err != nil {
		log.Printf("Postmortem HTTP error: %v", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusOK {
		log.Printf("Postmortem submitted for %s", result.Ticker)
	} else {
		log.Printf("Postmortem failed: %d", resp.StatusCode)
	}
}

func pushTradeToDash(result TradeResult, memoryURL string) {
	payload := map[string]any{
		"time":        result.Timestamp,
		"ticker":      result.Ticker,
		"dir":         result.Direction,
		"qty":         result.Quantity,
		"entry_price": result.EntryPrice,
		"pnl":         result.PnLPct,
		"status":      result.Status,
	}
	body, _ := json.Marshal(payload)
	resp, err := http.Post(memoryURL+"/api/v1/dash/trade", "application/json", bytes.NewReader(body))
	if err != nil {
		return
	}
	resp.Body.Close()
}
