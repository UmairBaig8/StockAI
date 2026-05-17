package handler

import (
	"html/template"
	"net/http"
	"strings"
	"time"

	"github.com/anomalyco/stockai-relay/internal/broker"
	"github.com/anomalyco/stockai-relay/internal/telegram"
	"github.com/anomalyco/stockai-relay/internal/token"
)

type Handler struct {
	tokenMgr  *token.Manager
	brokerAPI broker.API
	tgBot     *telegram.Bot
	tmpl      *template.Template
}

func New(tokenMgr *token.Manager, brokerAPI broker.API, tgBot *telegram.Bot) *Handler {
	tmpl := template.Must(template.New("totp").Parse(totpFormHTML))
	return &Handler{
		tokenMgr:  tokenMgr,
		brokerAPI: brokerAPI,
		tgBot:     tgBot,
		tmpl:      tmpl,
	}
}

func (h *Handler) ShowForm(w http.ResponseWriter, r *http.Request) {
	data := map[string]string{
		"Status": h.tokenMgr.Status(),
	}
	h.tmpl.Execute(w, data)
}

func (h *Handler) SubmitTOTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	totp := strings.TrimSpace(r.FormValue("totp"))
	if totp == "" {
		h.tmpl.Execute(w, map[string]string{
			"Error":  "TOTP/PIN is required",
			"Status": h.tokenMgr.Status(),
		})
		return
	}

	h.tokenMgr.Invalidate()

	go func() {
		h.tgBot.SendStatus("TOTP received. Authenticating with broker...")
	}()

	sessionToken, err := h.brokerAPI.Authenticate(totp)
	if err != nil {
		h.tgBot.SendStatus("Authentication FAILED: " + err.Error())
		h.tmpl.Execute(w, map[string]string{
			"Error":  "Broker authentication failed: " + err.Error(),
			"Status": h.tokenMgr.Status(),
		})
		return
	}

	h.tokenMgr.Set(sessionToken, 8*time.Hour)
	h.tgBot.SendStatus("Session active. Trading agent unlocked until 15:30 IST.")

	h.tmpl.Execute(w, map[string]string{
		"Success": "Session token acquired. Trading agent is now unlocked.",
		"Status":  h.tokenMgr.Status(),
	})
}

func (h *Handler) Health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"status":"ok","session":`))
	w.Write([]byte(`"` + h.tokenMgr.Status() + `"`))
	w.Write([]byte(`}`))
}

const totpFormHTML = `<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StockAI — 2FA Relay</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0f;
            color: #e4e4e7;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; padding: 20px;
        }
        .container {
            background: #16161e; border: 1px solid #2a2a3a;
            border-radius: 12px; padding: 32px; width: 100%; max-width: 420px;
        }
        h1 { font-size: 1.4rem; font-weight: 600; margin-bottom: 4px; color: #fff; }
        .subtitle { font-size: 0.85rem; color: #71717a; margin-bottom: 24px; }
        .status {
            background: #1a1a26; border: 1px solid #2a2a3a;
            border-radius: 8px; padding: 12px; margin-bottom: 20px;
            font-size: 0.8rem; color: #a1a1aa;
        }
        .status strong { color: #22c55e; }
        label { display: block; font-size: 0.85rem; color: #a1a1aa; margin-bottom: 6px; }
        input[type="text"] {
            width: 100%; padding: 10px 14px; background: #1a1a26;
            border: 1px solid #2a2a3a; border-radius: 8px;
            color: #e4e4e7; font-size: 1.1rem; letter-spacing: 4px;
            margin-bottom: 16px; outline: none;
        }
        input[type="text"]:focus { border-color: #3b82f6; }
        button {
            width: 100%; padding: 12px; background: #3b82f6;
            border: none; border-radius: 8px; color: #fff;
            font-size: 1rem; font-weight: 600; cursor: pointer;
        }
        button:hover { background: #2563eb; }
        .error { color: #ef4444; font-size: 0.85rem; margin-bottom: 12px; }
        .success { color: #22c55e; font-size: 0.85rem; margin-bottom: 12px; }
        .footer { margin-top: 24px; font-size: 0.7rem; color: #52525b; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>StockAI Relay</h1>
        <p class="subtitle">SEBI 2FA Session Unlock</p>

        <div class="status">
            <strong>Session:</strong> {{.Status}}
        </div>

        {{if .Error}}
        <div class="error">{{.Error}}</div>
        {{end}}

        {{if .Success}}
        <div class="success">{{.Success}}</div>
        {{end}}

        <form method="POST" action="/submit">
            <label for="totp">Enter TOTP or PIN</label>
            <input type="text" id="totp" name="totp"
                   placeholder="000000" maxlength="10" autofocus autocomplete="off">
            <button type="submit">Unlock Agent</button>
        </form>

        <p class="footer">StockAI Relay v0.1.0 &middot; Session valid for 1 trading day</p>
    </div>
</body>
</html>`
