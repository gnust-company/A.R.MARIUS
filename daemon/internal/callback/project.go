package callback

import (
	"context"
	"encoding/json"
	"strings"
)

// projectCommands is what a run about a project may do — the Leader's set (FR-013d).
//
// **A task-level run does not get these.** Not because they would be refused if it tried, though
// they would be, but because a run about one task is never handed them in the first place: the
// toolset *is* the scope. That is inherited from Multica, where an agent's tools travel with its
// task like luggage rather than being installed once per machine.
//
// What is deliberately absent is as much a part of this list as what is in it: there is no
// command for approving a plan or moving a phase. The Leader submits and proposes; the patron
// decides (FR-004, FR-014). A command that does not exist cannot be called by mistake.
func projectCommands() []Command {
	return []Command{
		{
			Name:    "project queue",
			Group:   GroupProject,
			Summary: "What to hand out next, in order. Anything waiting on the patron is left out.",
			Call: func(ctx context.Context, c *Client, _ Args) (json.RawMessage, error) {
				path, err := projectPath(c, "/queue")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "GET", path, nil)
			},
		},
		{
			Name:    "project new-task",
			Group:   GroupProject,
			Summary: "Open a task. Attached to an approved plan item it goes live; attached to nothing the patron is asked first.",
			Params: []Param{
				{Name: "title", Type: TypeString, Required: true, Description: "What the task is."},
				{Name: "description", Type: TypeString, Description: "The whole of what is being asked for."},
				{Name: "assignee_marius_id", Type: TypeString, Description: "Who does it."},
				{Name: "plan_item_id", Type: TypeString, Description: "The approved plan item it belongs to."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := projectPath(c, "/tasks")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path,
					body(args, "title", "description", "assignee_marius_id", "plan_item_id"))
			},
		},
		{
			Name:    "project context",
			Group:   GroupProject,
			Summary: "Submit the brief you agreed with the patron. It waits for their approval.",
			Params: []Param{
				{Name: "objective", Type: TypeString, Description: "What this project is for."},
				{Name: "background", Type: TypeString, Description: "What led to it."},
				{Name: "constraints", Type: TypeString, Description: "What it must work within."},
				{Name: "scope", Type: TypeString, Description: "What is in, and what is out."},
				{Name: "principles", Type: TypeString, Description: "How decisions get made when nobody is around to ask."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := projectPath(c, "/context")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path,
					body(args, "objective", "background", "constraints", "scope", "principles"))
			},
		},
		{
			Name:    "project plan",
			Group:   GroupProject,
			Summary: "Submit the plan. It parks in the patron's inbox until they decide.",
			Params: []Param{
				{Name: "summary", Type: TypeString, Description: "The plan in a paragraph."},
				{Name: "risks", Type: TypeString, Description: "What could go wrong."},
				{Name: "milestones", Type: TypeString, Description: "The marks along the way."},
				{Name: "items", Type: TypeString, Description: "The plan items, as a JSON array."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := projectPath(c, "/plan")
				if err != nil {
					return nil, err
				}
				payload := body(args, "summary", "risks", "milestones")
				items, err := decodeItems(args)
				if err != nil {
					return nil, err
				}
				payload["items"] = items
				return c.Call(ctx, "POST", path, payload)
			},
		},
		{
			Name:    "project phase",
			Group:   GroupProject,
			Summary: "Ask the patron to move the project to another phase. Changes nothing on its own.",
			Params: []Param{
				{Name: "target_phase", Type: TypeString, Required: true, Description: "The phase you are proposing."},
				{Name: "reason", Type: TypeString, Description: "Why now."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := projectPath(c, "/phase-proposal")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, body(args, "target_phase", "reason"))
			},
		},
		{
			Name:    "project sprint-summary",
			Group:   GroupProject,
			Summary: "Wrap up a finished batch and hand the patron their three choices.",
			Params: []Param{
				{Name: "summary", Type: TypeString, Required: true, Description: "What the batch delivered."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := projectPath(c, "/sprint-summary")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, body(args, "summary"))
			},
		},
		{
			Name:  "project change-request",
			Group: GroupProject,
			Summary: "Ask the patron before changing what they agreed to. Five areas only: scope, " +
				"objective, cost, deadline, acceptance criteria.",
			Params: []Param{
				{Name: "area", Type: TypeString, Required: true, Description: "Which of the five is changing."},
				{Name: "summary", Type: TypeString, Required: true, Description: "The change, in a line."},
				{Name: "detail", Type: TypeString, Description: "Everything the patron needs to decide."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := projectPath(c, "/change-request")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, body(args, "area", "summary", "detail"))
			},
		},
	}
}

// decodeItems reads the plan items, which are the one input in this program that is a list
// rather than a line.
//
// Both faces reach here. MCP hands over whatever JSON the agent put in the field, already
// decoded; the command line hands over the text it was typed as, which has to be parsed. A
// malformed list is a usage error and says so — sending it on as an empty list would file a plan
// with nothing in it and report success.
func decodeItems(args Args) ([]any, error) {
	switch raw := args["items"].(type) {
	case nil:
		return []any{}, nil
	case []any:
		return raw, nil
	case string:
		if strings.TrimSpace(raw) == "" {
			return []any{}, nil
		}
		var items []any
		if err := json.Unmarshal([]byte(raw), &items); err != nil {
			return nil, fail(ExitUsage, "items must be a JSON array of plan items: %w", err)
		}
		return items, nil
	default:
		return nil, fail(ExitUsage, "items must be a JSON array of plan items")
	}
}
