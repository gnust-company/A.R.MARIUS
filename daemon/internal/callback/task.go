package callback

import (
	"context"
	"encoding/json"
)

// taskCommands is everything a run about one task may do (FR-013d).
//
// The task is never named in an argument. It is the task this run is about, and it comes from
// the environment the daemon built — so there is no identifier for an agent to get wrong, and
// none for it to go looking for. Looking is how it would find somebody else's.
func taskCommands() []Command {
	return []Command{
		{
			Name:    "task show",
			Group:   GroupTask,
			Summary: "Read your task: the brief, the thread, what has been published, and who else is here.",
			Call: func(ctx context.Context, c *Client, _ Args) (json.RawMessage, error) {
				path, err := taskPath(c, "")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "GET", path, nil)
			},
		},
		{
			Name:    "task comment",
			Group:   GroupTask,
			Summary: "Leave a comment on the task. Mention someone with @their-name to reach them.",
			Params: []Param{
				{Name: "body", Type: TypeString, Required: true, Description: "What to say."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := taskPath(c, "/comment")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, body(args, "body"))
			},
		},
		{
			Name:    "task status",
			Group:   GroupTask,
			Summary: "Move the task to another status.",
			Params: []Param{
				{Name: "status", Type: TypeString, Required: true, Description: "The status to move to."},
				{Name: "reason", Type: TypeString, Description: "Why. Required for some moves."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := taskPath(c, "/status")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, body(args, "status", "reason"))
			},
		},
		{
			Name:    "task next-action",
			Group:   GroupTask,
			Summary: "Record the single next thing to be done, so a later run picks up where this one stopped.",
			Params: []Param{
				{Name: "next_action", Type: TypeString, Description: "The next step. Send it empty to clear it."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := taskPath(c, "/next-action")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, body(args, "next_action"))
			},
		},
		{
			Name:  "task publish",
			Group: GroupTask,
			Summary: "Publish an artifact of this task. Safe to repeat: the same name with the same " +
				"bytes is recorded once, however many times it is sent.",
			Params: []Param{
				{Name: "name", Type: TypeString, Required: true, Description: "What to call it."},
				{Name: "kind", Type: TypeString, Description: "file, note or link. Defaults to file."},
				{Name: "content", Type: TypeString, Description: "The text of it, for a note or a text file."},
				{Name: "content_b64", Type: TypeString, Description: "The bytes of it, base64, for anything not text."},
				{Name: "content_sha256", Type: TypeString, Description: "Checksum of the bytes, if you have one."},
				{Name: "uri", Type: TypeString, Description: "Where it lives, for a link."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := taskPath(c, "/artifact")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path,
					body(args, "name", "kind", "content", "content_b64", "content_sha256", "uri"))
			},
		},
		{
			Name:    "task criteria",
			Group:   GroupTask,
			Summary: "The acceptance criteria this task is judged against, and how each one stands.",
			Call: func(ctx context.Context, c *Client, _ Args) (json.RawMessage, error) {
				path, err := taskPath(c, "/criteria")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "GET", path, nil)
			},
		},
		{
			Name:    "task rate",
			Group:   GroupTask,
			Summary: "Score one acceptance criterion. The Leader's call.",
			Params: []Param{
				{Name: "criterion_id", Type: TypeString, Required: true, Description: "Which criterion, from `task criteria`."},
				{Name: "result", Type: TypeString, Required: true, Description: "passed or failed."},
				{Name: "evidence_artifact_id", Type: TypeString, Description: "The published artifact that proves a pass."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := taskPath(c, "/criteria/"+args.String("criterion_id"))
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, body(args, "result", "evidence_artifact_id"))
			},
		},
		{
			Name:    "task sign",
			Group:   GroupTask,
			Summary: "Sign the work off, or send it back with what to fix. The Leader's call.",
			Params: []Param{
				{Name: "approve", Type: TypeBoolean, Required: true, Description: "true to sign, false to send it back."},
				{Name: "reason", Type: TypeString, Description: "Required when sending it back."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := taskPath(c, "/approval")
				if err != nil {
					return nil, err
				}
				payload := body(args, "reason")
				payload["approve"] = args.Bool("approve")
				return c.Call(ctx, "POST", path, payload)
			},
		},
		{
			Name:    "task handback",
			Group:   GroupTask,
			Summary: "Hand the work back, or ask a question you cannot answer alone. Healthy: the task stays live.",
			Params: []Param{
				{Name: "reason", Type: TypeString, Required: true, Description: "What you need, or why you are handing it back."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := taskPath(c, "/handback")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, body(args, "reason"))
			},
		},
		{
			Name:    "task request",
			Group:   GroupTask,
			Summary: "Ask to be put on this task. It is a request to the Leader — nothing is assigned here.",
			Params: []Param{
				{Name: "note", Type: TypeString, Description: "Why you are asking."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := taskPath(c, "/request")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, body(args, "note"))
			},
		},
		{
			Name:    "task recovery",
			Group:   GroupTask,
			Summary: "Record the recovery action you decided for a stuck task. The Leader's call.",
			Params: []Param{
				{Name: "action", Type: TypeString, Required: true, Description: "What you decided to do about it."},
				{Name: "next_action", Type: TypeString, Description: "The next step to write onto the task."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := taskPath(c, "/recovery")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, body(args, "action", "next_action"))
			},
		},
		{
			Name:    "task escalate",
			Group:   GroupTask,
			Summary: "Hand a stuck task to the patron because it is beyond you. The Leader's call.",
			Params: []Param{
				{Name: "reason", Type: TypeString, Required: true, Description: "Why you could not get it unstuck."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := taskPath(c, "/escalate")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, body(args, "reason"))
			},
		},
	}
}
