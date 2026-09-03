package callback

import (
	"context"
	"encoding/json"
	"strings"
)

// onboardingCommands are what a run about no task and no project may do (FR-040c).
//
// One shape of run reaches here, and only one: the team-building interview, where the patron is
// setting a project up with the workspace's own agent and there is no project yet to be about.
// Every other run names a task or a project, and is handed a different set.
//
// **They take the chat's id rather than reading it out of the environment**, unlike the task and
// project commands. The environment carries what the *claim door* said this run is about, and
// that door knows nothing of interviews — a chat is a thing above it, in the layer that owns
// what the patron is doing. The id travels the only way it honestly can: in the message this run
// was queued with, which names the chat this turn belongs to. What stops the id being pointed
// somewhere else is not this side at all — the server admits only chats in the caller's own
// workspace, hosted by the caller itself.
func onboardingCommands() []Command {
	return []Command{
		{
			Name:    "onboarding ask",
			Group:   GroupWorkspace,
			Summary: "Ask the patron your next question, then stop and wait for the answer.",
			Params: []Param{
				{Name: "session_id", Type: TypeString, Required: true, Description: "The chat this question belongs to, named in your instructions."},
				{Name: "question", Type: TypeString, Required: true, Description: "The single question you are asking now."},
				{Name: "options", Type: TypeString, Required: true, Description: `The answers to offer — at least one, as a JSON array: [{"id":"1","label":"…"}]. Add one whose label invites a typed answer when the patron should write their own.`},
				{Name: "multi", Type: TypeBoolean, Description: "Whether several options may be picked at once."},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := onboardingPath(args, "/question")
				if err != nil {
					return nil, err
				}
				options, err := decodeJSONArray(args, "options")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, map[string]any{
					"question": args.String("question"),
					"options":  options,
					"multi":    args.Bool("multi"),
				})
			},
		},
		{
			Name:    "onboarding propose",
			Group:   GroupWorkspace,
			Summary: "Post the project and roster you agreed, for the patron to confirm.",
			Params: []Param{
				{Name: "session_id", Type: TypeString, Required: true, Description: "The chat this draft belongs to, named in your instructions."},
				{Name: "project", Type: TypeString, Required: true, Description: `The project, as a JSON object: {"name":"…","objective":"…"}.`},
				{Name: "roster", Type: TypeString, Required: true, Description: `The worker roles, as a JSON array. The Project Leader is added for you.`},
			},
			Call: func(ctx context.Context, c *Client, args Args) (json.RawMessage, error) {
				path, err := onboardingPath(args, "/complete")
				if err != nil {
					return nil, err
				}
				project, err := decodeJSONObject(args, "project")
				if err != nil {
					return nil, err
				}
				roster, err := decodeJSONArray(args, "roster")
				if err != nil {
					return nil, err
				}
				return c.Call(ctx, "POST", path, map[string]any{
					"project": project,
					"roster":  roster,
				})
			},
		},
	}
}

// onboardingPath builds a path under the chat named in the call, refusing when none was.
//
// Refused here rather than sent on: a path with an empty id in the middle of it is a different
// path, and the answer it comes back with would be about something else.
func onboardingPath(args Args, suffix string) (string, error) {
	id := strings.TrimSpace(args.String("session_id"))
	if id == "" {
		return "", fail(ExitUsage, "say which chat this is for: session_id is named in your instructions")
	}
	return "/agent/onboarding/" + id + suffix, nil
}

// decodeJSONArray reads a list parameter, whichever face it arrived through.
//
// MCP hands over decoded JSON; the command line hands over the text it was typed as. Malformed
// is a usage error rather than an empty list: an empty list would be sent on, and a question
// with nothing to pick is refused at the far end — so the agent would be told its options are
// wrong in a message about a field it thought it had filled in.
func decodeJSONArray(args Args, name string) ([]any, error) {
	switch raw := args[name].(type) {
	case nil:
		return []any{}, nil
	case []any:
		return raw, nil
	case string:
		if strings.TrimSpace(raw) == "" {
			return []any{}, nil
		}
		var out []any
		if err := json.Unmarshal([]byte(raw), &out); err != nil {
			return nil, fail(ExitUsage, "%s must be a JSON array: %w", name, err)
		}
		return out, nil
	default:
		return nil, fail(ExitUsage, "%s must be a JSON array", name)
	}
}

// decodeJSONObject is the same for a single object, and absent is *not* a real answer here: the
// two places it is used are both required, and an empty object would file a nameless project.
func decodeJSONObject(args Args, name string) (map[string]any, error) {
	switch raw := args[name].(type) {
	case map[string]any:
		return raw, nil
	case string:
		var out map[string]any
		if err := json.Unmarshal([]byte(raw), &out); err != nil {
			return nil, fail(ExitUsage, "%s must be a JSON object: %w", name, err)
		}
		return out, nil
	default:
		return nil, fail(ExitUsage, "%s must be a JSON object", name)
	}
}
