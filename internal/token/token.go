package token

import (
	"fmt"
	"sync"
	"time"
)

type SessionToken struct {
	Token     string    `json:"token"`
	CreatedAt time.Time `json:"created_at"`
	ExpiresAt time.Time `json:"expires_at"`
	Active    bool      `json:"active"`
}

type Manager struct {
	mu     sync.RWMutex
	token  *SessionToken
	status string
}

func NewManager() *Manager {
	return &Manager{}
}

func (m *Manager) Set(token string, ttl time.Duration) {
	m.mu.Lock()
	defer m.mu.Unlock()
	now := time.Now()
	m.token = &SessionToken{
		Token:     token,
		CreatedAt: now,
		ExpiresAt: now.Add(ttl),
		Active:    true,
	}
	m.status = fmt.Sprintf("Session token set at %s, expires %s", now.Format(time.RFC3339), now.Add(ttl).Format(time.RFC3339))
}

func (m *Manager) Get() (string, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if m.token == nil {
		return "", fmt.Errorf("no session token available")
	}
	if time.Now().After(m.token.ExpiresAt) {
		m.token.Active = false
		return "", fmt.Errorf("session token expired at %s", m.token.ExpiresAt.Format(time.RFC3339))
	}
	if !m.token.Active {
		return "", fmt.Errorf("session token is inactive")
	}
	return m.token.Token, nil
}

func (m *Manager) Status() string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if m.token == nil {
		return "No session token. Waiting for 2FA."
	}
	if time.Now().After(m.token.ExpiresAt) {
		return "Session token EXPIRED."
	}
	if !m.token.Active {
		return "Session token inactive."
	}
	return fmt.Sprintf("Session active. Created: %s, Expires: %s",
		m.token.CreatedAt.Format(time.RFC3339),
		m.token.ExpiresAt.Format(time.RFC3339))
}

func (m *Manager) Invalidate() {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.token != nil {
		m.token.Active = false
	}
	m.status = "Session invalidated"
}
