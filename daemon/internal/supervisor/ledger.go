package supervisor

import (
	"context"

	"github.com/gnust-company/armarius-daemon/internal/client"
)

// Reporting is the Ledger backed by the real server.
//
// The whole of the translation between what a run has to say and how it is said on the wire
// lives in this file, which is why `Recorded` and `Conclusion` are this package's own types
// rather than the client's: adding a field to the wire format should not be able to reach into
// the code that decides what a run does.
type Reporting struct {
	Session client.Session
}

func (r Reporting) Start(ctx context.Context, runID, session string) (bool, error) {
	return r.Session.StartRun(ctx, runID, session)
}

func (r Reporting) Record(ctx context.Context, runID string, events []Recorded) error {
	batch := make([]client.EventIn, 0, len(events))
	for _, e := range events {
		batch = append(batch, client.EventIn{Seq: e.Seq, Type: e.Type, Payload: e.Payload})
	}
	return r.Session.Record(ctx, runID, batch)
}

func (r Reporting) Finish(ctx context.Context, runID string, done Conclusion) error {
	return r.Session.FinishRun(ctx, runID, client.FinishRequest{
		Status: done.Status,
		Error:  done.Error,
		Usage:  done.Usage,
	})
}
