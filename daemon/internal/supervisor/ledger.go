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

// Start says the agent is up. False with no error means the hold ran out while this machine
// was setting up — the run belongs to nobody now (FR-058).
func (r Reporting) Start(ctx context.Context, runID, session string) (bool, error) {
	return r.Session.StartRun(ctx, runID, session)
}

// Record sends one batch of events, translating this package's shapes into the wire's.
func (r Reporting) Record(ctx context.Context, runID string, events []Recorded) error {
	batch := make([]client.EventIn, 0, len(events))
	for _, e := range events {
		batch = append(batch, client.EventIn{
			Seq:            e.Seq,
			Type:           e.Type,
			Payload:        e.Payload,
			Truncated:      e.Truncated,
			OriginalBytes:  e.OriginalBytes,
			OmissionReason: e.OmissionReason,
			Redacted:       e.Redacted,
		})
	}
	return r.Session.Record(ctx, runID, batch)
}

// Finish closes the run: the run token dies with it, and the task gets something live pushing
// it again without waiting for a sweep (FR-014b, FR-030a).
func (r Reporting) Finish(ctx context.Context, runID string, done Conclusion) error {
	return r.Session.FinishRun(ctx, runID, client.FinishRequest{
		Status: done.Status,
		Error:  done.Error,
		Usage:  done.Usage,
	})
}
