package discovery

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// helpWithAuth is the part of Claude Code 2.1.322's own `--help` that matters here, as printed
// on 2026-11-13 — including two of the option descriptions that mention the word without
// being the command.
const helpWithAuth = `Options:
  --bare                                Minimal mode: skip hooks, LSP, ... Anthropic auth is
                                        strictly ANTHROPIC_API_KEY or
                                        apiKeyHelper via --settings (OAuth and
Commands:
  agents [options]                      List configured agents
  auth                                  Manage authentication
  gateway [options]                     Run the enterprise auth/telemetry
  setup-token                           Set up a long-lived authentication token
`

func asking(said string, err error, asked *[]string) Options {
	return Options{
		Run: func(context.Context, string, ...string) ([]byte, error) {
			return []byte(helpWithAuth), nil
		},
		Answer: func(_ context.Context, _ string, args ...string) ([]byte, error) {
			if asked != nil {
				*asked = args
			}
			return []byte(said), err
		},
		Timeout: time.Second,
	}
}

var claude = Found{Kind: agentcli.ClaudeCode, Path: "/usr/bin/claude"}

// The two answers below are the ones Claude Code 2.1.322 printed on 2026-11-13, the first in
// the operator's home and the second in a home nobody had signed in to (where it also exited 1).
const (
	signedInAnswer = `{
  "loggedIn": true,
  "authMethod": "claude.ai",
  "apiProvider": "firstParty",
  "loginExpiresAt": "2026-12-09T21:32:16.742Z",
  "subscriptionType": "pro"
}`
	signedOutAnswer = `{
  "loggedIn": false,
  "authMethod": "none",
  "apiProvider": "firstParty",
  "loginExpiresAt": null
}`
)

func TestClaudeCodeIsAskedWithItsOwnStatusCommand(t *testing.T) {
	var asked []string
	got := AskSignIn(context.Background(), claude, asking(signedInAnswer, nil, &asked))

	if got != SignedIn {
		t.Errorf("answer = %v, want signed in", got)
	}
	if want := []string{"auth", "status", "--json"}; !reflect.DeepEqual(asked, want) {
		t.Errorf("asked with %v, want %v", asked, want)
	}
}

func TestSignedOutIsWhatTheCLISaidNotAFailureToAsk(t *testing.T) {
	got := AskSignIn(context.Background(), claude, asking(signedOutAnswer, nil, nil))

	if got != SignedOut {
		t.Errorf("answer = %v, want signed out", got)
	}
	if said := got.Reported(); said == nil || *said {
		t.Errorf("reported %v, want an explicit false", said)
	}
}

// Every one of these is *nothing was learned*. None may come out as signed out: that would
// close a working workplace on a guess.
func TestAnAnswerThatCannotBeReadClaimsNothing(t *testing.T) {
	cases := map[string]Options{
		"the command would not start":   asking("", errors.New("exec: not found"), nil),
		"not JSON at all":               asking("Unknown command: auth\n", nil, nil),
		"JSON without the field":        asking(`{"authMethod": "claude.ai"}`, nil, nil),
		"the field is not a yes or no":  asking(`{"loggedIn": "yes"}`, nil, nil),
		"an empty answer":               asking("", nil, nil),
		"null where the answer belongs": asking(`{"loggedIn": null}`, nil, nil),
	}
	for name, opts := range cases {
		t.Run(name, func(t *testing.T) {
			got := AskSignIn(context.Background(), claude, opts)
			if got != SignInUnknown {
				t.Errorf("answer = %v, want unknown", got)
			}
			if got.Reported() != nil {
				t.Errorf("an unknown answer was reported as %v", *got.Reported())
			}
		})
	}
}

// Gemini and Codex have no measured way of being asked, so they are not asked — and a CLI
// that is not asked is never reported signed out.
func TestACLIWithNoSuchQuestionIsNotAsked(t *testing.T) {
	for _, kind := range []agentcli.Kind{agentcli.Gemini, agentcli.Codex} {
		called := false
		opts := Options{
			Answer: func(context.Context, string, ...string) ([]byte, error) {
				called = true
				return []byte(signedOutAnswer), nil
			},
			Timeout: time.Second,
		}

		got := AskSignIn(context.Background(), Found{Kind: kind, Path: "/usr/bin/x"}, opts)

		if called {
			t.Errorf("%s was asked a question it has no command for", kind)
		}
		if got != SignInUnknown {
			t.Errorf("%s: answer = %v, want unknown", kind, got)
		}
	}
}

// A CLI too old to have the command would take the words as a prompt. It is not asked.
func TestACLIWhoseHelpDoesNotListTheCommandIsNeverAskedIt(t *testing.T) {
	olderHelps := map[string]string{
		"no such command":                   "Commands:\n  mcp        Configure MCP servers\n",
		"the word only inside a sentence":   "  --bare    Anthropic auth is strictly ANTHROPIC_API_KEY\n",
		"a different command with the word": "  gateway [options]   Run the enterprise auth/telemetry\n",
		"help that would not print":         "",
	}
	for name, help := range olderHelps {
		t.Run(name, func(t *testing.T) {
			asked := false
			opts := Options{
				Run: func(context.Context, string, ...string) ([]byte, error) {
					if help == "" {
						return nil, errors.New("exit status 1")
					}
					return []byte(help), nil
				},
				Answer: func(context.Context, string, ...string) ([]byte, error) {
					asked = true
					return []byte(signedOutAnswer), nil
				},
				Timeout: time.Second,
			}

			got := AskSignIn(context.Background(), claude, opts)

			if asked {
				t.Error("the CLI was handed words its own help does not list as a command")
			}
			if got != SignInUnknown {
				t.Errorf("answer = %v, want unknown", got)
			}
		})
	}
}
