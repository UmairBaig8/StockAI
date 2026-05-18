package telegram

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"
)

type Bot struct {
	token  string
	chatID string
	client *http.Client
}

type SendMessageRequest struct {
	ChatID    string `json:"chat_id"`
	Text      string `json:"text"`
	ParseMode string `json:"parse_mode,omitempty"`
}

type Update struct {
	UpdateID int     `json:"update_id"`
	Message  Message `json:"message"`
}

type Message struct {
	MessageID int    `json:"message_id"`
	Chat      Chat   `json:"chat"`
	Text      string `json:"text"`
}

type Chat struct {
	ID int64 `json:"id"`
}

type GetUpdatesResponse struct {
	OK     bool     `json:"ok"`
	Result []Update `json:"result"`
}

func NewBot(token, chatID string) *Bot {
	return &Bot{
		token:  token,
		chatID: chatID,
		client: &http.Client{Timeout: 10 * time.Second},
	}
}

func (b *Bot) apiURL(method string) string {
	return fmt.Sprintf("https://api.telegram.org/bot%s/%s", b.token, method)
}

func (b *Bot) SendMessage(text string) error {
	body := SendMessageRequest{
		ChatID:    b.chatID,
		Text:      text,
		ParseMode: "HTML",
	}
	payload, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("marshal message: %w", err)
	}

	resp, err := b.client.Post(b.apiURL("sendMessage"), "application/json", bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("send message: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("telegram API error %d: %s", resp.StatusCode, string(respBody))
	}
	return nil
}

func (b *Bot) Send2FANotification(relayURL string) error {
	msg := fmt.Sprintf(
		"<b>SEBI 2FA Relay — Market Pre-Open</b>\n\n"+
			"Your trading agent needs the daily session unlock.\n\n"+
			"<a href=\"%s\">Click here to enter your TOTP/PIN</a>\n\n"+
			"<i>This link expires in 10 minutes. Session required before 0915 IST.</i>",
		relayURL,
	)
	return b.SendMessage(msg)
}

func (b *Bot) SendStatus(status string) error {
	msg := fmt.Sprintf("<b>2FA Relay Status:</b> %s", status)
	return b.SendMessage(msg)
}

func (b *Bot) SendTradeAlert(ticker, direction string, entryPrice, exitPrice float64, qty int, pnlPct float64, status string) {
	emoji := "🟢"
	if status == "LOSS" {
		emoji = "🔴"
	} else if status == "OPEN" {
		emoji = "🔵"
	}
	pnlSign := "+"
	if pnlPct < 0 {
		pnlSign = ""
	}

	msg := fmt.Sprintf(
		"%s <b>%s %s</b>\n"+
			"Qty: %d | Entry: ₹%.2f | Exit: ₹%.2f\n"+
			"P&L: %s%.2f%% | Status: %s\n"+
			"<i>StockAI — %s</i>",
		emoji, ticker, direction,
		qty, entryPrice, exitPrice,
		pnlSign, pnlPct, status,
		time.Now().Format("15:04 IST"),
	)
	b.SendMessage(msg)
}

func (b *Bot) SendDailyReport(totalTrades, wins, losses int, netPnL float64, netPnLPct float64, bestTrade, worstTrade string, rulesLearned int) {
	winRate := 0.0
	if totalTrades > 0 {
		winRate = float64(wins) / float64(totalTrades) * 100
	}
	pnlEmoji := "🟢"
	pnlSign := "+"
	if netPnL < 0 {
		pnlEmoji = "🔴"
		pnlSign = ""
	}

	msg := fmt.Sprintf(
		"<b>📊 Daily P&L Report</b>\n\n"+
			"Trades: %d | Wins: %d | Losses: %d\n"+
			"Win Rate: %.0f%%\n\n"+
			"%s <b>Net P&L: %s₹%.2f (%s%.2f%%)</b>\n\n"+
			"Best: %s | Worst: %s\n"+
			"Evolution rules: %d\n\n"+
			"<i>StockAI — %s</i>",
		totalTrades, wins, losses,
		winRate,
		pnlEmoji, pnlSign, netPnL, pnlSign, netPnLPct,
		bestTrade, worstTrade,
		rulesLearned,
		time.Now().Format("02 Jan 2006 15:04 IST"),
	)
	b.SendMessage(msg)
}

func (b *Bot) GetUpdates(offset int) ([]Update, error) {
	u, err := url.Parse(b.apiURL("getUpdates"))
	if err != nil {
		return nil, fmt.Errorf("parse URL: %w", err)
	}
	q := u.Query()
	if offset > 0 {
		q.Set("offset", fmt.Sprintf("%d", offset))
	}
	q.Set("timeout", "5")
	u.RawQuery = q.Encode()

	resp, err := b.client.Get(u.String())
	if err != nil {
		return nil, fmt.Errorf("get updates: %w", err)
	}
	defer resp.Body.Close()

	var result GetUpdatesResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode updates: %w", err)
	}
	return result.Result, nil
}
