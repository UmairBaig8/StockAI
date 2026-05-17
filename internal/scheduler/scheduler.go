package scheduler

import (
	"fmt"
	"log"
	"sync"
	"time"
)

type Schedule struct {
	Hour   int
	Minute int
}

type Scheduler struct {
	mu     sync.Mutex
	tasks  map[string]Task
	loc    *time.Location
	stopCh chan struct{}
}

type Task struct {
	Schedule Schedule
	Fn       func()
}

func New() *Scheduler {
	loc, err := time.LoadLocation("Asia/Kolkata")
	if err != nil {
		loc = time.FixedZone("IST", 5*3600+30*60)
	}
	return &Scheduler{
		tasks:  make(map[string]Task),
		loc:    loc,
		stopCh: make(chan struct{}),
	}
}

func (s *Scheduler) Register(name string, hour, minute int, fn func()) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.tasks[name] = Task{
		Schedule: Schedule{Hour: hour, Minute: minute},
		Fn:       fn,
	}
	log.Printf("Registered task %q at %02d:%02d IST", name, hour, minute)
}

func (s *Scheduler) Start() {
	go s.loop()
}

func (s *Scheduler) Stop() {
	close(s.stopCh)
}

func (s *Scheduler) loop() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-s.stopCh:
			return
		case now := <-ticker.C:
			s.checkAndRun(now.In(s.loc))
		}
	}
}

func (s *Scheduler) checkAndRun(now time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()

	currentKey := now.Format("1504")

	for name, task := range s.tasks {
		taskKey := fmt.Sprintf("%02d%02d", task.Schedule.Hour, task.Schedule.Minute)
		if currentKey == taskKey {
			log.Printf("Scheduler: triggering task %q at %s", name, now.Format(time.RFC3339))
			go task.Fn()
		}
	}
}
