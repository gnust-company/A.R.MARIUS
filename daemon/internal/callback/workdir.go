package callback

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/gnust-company/armarius-daemon/internal/execenv"
)

// defaultChangeLimit is how many files are listed when the agent does not say.
//
// Enough to see a piece of work, small enough that a directory with a cloned repository in it
// does not become the answer. The count of everything found comes back regardless, so an agent
// that has more than this is told so rather than left thinking it has fifty files.
const defaultChangeLimit = 50

// howManyFiles describes the one parameter, in both faces at once.
var howManyFiles = fmt.Sprintf(
	"how many files to list, most recently written first (default %d)", defaultChangeLimit,
)

// workdirCommands are the ones answered from this machine's own disk.
//
// **They do not go to the server, and they carry no credential** — there is nothing to
// authenticate, because nothing leaves the machine. That is not a shortcut: this is the one
// question in the whole set whose answer is not the server's to give. What is in a working
// directory is on the disk of the machine running the agent, and the server could only find out
// by asking the daemon — but the daemon is the side that *asks for* work, never a side that
// answers (FR-053, FR-055). There is no such road, and building one to answer a question that
// can be answered where it is asked would be building it for nothing.
func workdirCommands() []Command {
	return []Command{
		{
			Name:    "workdir changes",
			Group:   GroupAny,
			Summary: "What is in this working directory that you put there.",
			Params: []Param{
				{Name: "limit", Type: TypeInteger, Description: howManyFiles},
			},
			Call: func(_ context.Context, c *Client, args Args) (json.RawMessage, error) {
				return changesHere(c.Env, args)
			},
		},
	}
}

// changesHere answers what the agent has made, and publishes nothing (FR-018, FR-020a).
//
// Information, deliberately: the daemon does not scan for finished work and does not push
// anything on the agent's behalf. A working directory is a desk, not a shelf, and the road out
// of it runs one way and only when the agent takes it.
func changesHere(env Environment, args Args) (json.RawMessage, error) {
	if env.WorkDir == "" {
		return nil, fail(ExitUsage,
			"this run was given no working directory, so there is nothing here to have changed")
	}
	limit := args.Int("limit", defaultChangeLimit)
	if limit < 0 {
		return nil, fail(ExitUsage, "limit cannot be negative")
	}

	list, err := execenv.Changes(env.WorkDir, limit)
	if err != nil {
		return nil, fail(ExitRefused, "%v", err)
	}
	// Never nil, so that the agent reading the answer finds an empty list rather than a null it
	// has to have a second branch for.
	if list.Files == nil {
		list.Files = []execenv.Change{}
	}
	body, err := json.Marshal(list)
	if err != nil {
		return nil, fail(ExitRefused, "%v", err)
	}
	return body, nil
}
