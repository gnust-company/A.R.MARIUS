package client

import (
	"context"
	"net/http"
	"time"
)

// tasksPerAsk is how many names one request carries, matching the server's ceiling
// (MAX_TASKS_PER_ASK). Split here rather than by the caller so the number is agreed on in one
// place and a sweep never has to know a request has a size at all.
const tasksPerAsk = 200

// TaskStatesRequest names the directories a machine has, so it can be told which of them
// nobody needs any more.
type TaskStatesRequest struct {
	TaskIDs []string `json:"task_ids"`
}

// TaskState is one task the server could account for.
type TaskState struct {
	TaskID string `json:"task_id"`
	Closed bool   `json:"closed"`
	// LastActivity is when anything last happened to the task. It only decides anything once
	// Closed is true — an open task is kept whatever this says.
	LastActivity time.Time `json:"last_activity"`
}

// TaskStatesResponse carries only the tasks that were found. A name missing from it is the
// answer to that name: the server cannot account for it (FR-021a).
type TaskStatesResponse struct {
	Tasks []TaskState `json:"tasks"`
}

// TaskStates asks what this workspace knows about each of these tasks, in as many requests as
// it takes (FR-021).
//
// The map holds only what came back, keyed by task id. A name that is absent stays absent —
// filling in a zero value would hand the caller a task that claims to be open and never
// closes, which is the one shape that makes a directory immortal.
//
// A failed request fails the whole lookup rather than returning what did arrive. A partial map
// is worse than no map: absence means *the server does not know this task*, so a batch that
// never reached the server would put its directories on the orphan clock for a reason that has
// nothing to do with them.
func (s Session) TaskStates(ctx context.Context, taskIDs []string) (map[string]TaskState, error) {
	states := make(map[string]TaskState, len(taskIDs))
	for _, batch := range inBatches(taskIDs, tasksPerAsk) {
		var out TaskStatesResponse
		_, err := sendJSON(
			ctx, s.client(), http.MethodPost,
			endpoint(s.Server, "/daemon/tasks/states"), s.Token,
			TaskStatesRequest{TaskIDs: batch}, &out,
		)
		if err != nil {
			return nil, err
		}
		for _, task := range out.Tasks {
			states[task.TaskID] = task
		}
	}
	return states, nil
}

// inBatches cuts a list into runs of at most size. An empty list yields no batches at all, so
// a sweep that found nothing on disk makes no call.
func inBatches(names []string, size int) [][]string {
	var batches [][]string
	for start := 0; start < len(names); start += size {
		end := start + size
		if end > len(names) {
			end = len(names)
		}
		batches = append(batches, names[start:end])
	}
	return batches
}
