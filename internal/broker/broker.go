package broker

import (
	"errors"
	"fmt"
	"time"
)

type API interface {
	Authenticate(totp string) (string, error)
}

type MockAPI struct{}

func NewMockAPI() *MockAPI {
	return &MockAPI{}
}

func (m *MockAPI) Authenticate(totp string) (string, error) {
	if len(totp) < 4 {
		return "", errors.New("invalid TOTP/PIN — too short")
	}

	sessionToken := fmt.Sprintf("mock-session-%s-%d", totp[:4], time.Now().Unix())
	return sessionToken, nil
}
