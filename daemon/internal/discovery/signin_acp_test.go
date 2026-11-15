package discovery

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"
	"time"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// kimiIntroduction is what `kimi acp` 2.5.3 answered `initialize` with on 2026-11-15, whole,
// with only the two absolute paths it echoes shortened.
const kimiIntroduction = `{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{` +
	`"loadSession":true,"promptCapabilities":{"image":true,"audio":false,"embeddedContext":true},` +
	`"sessionCapabilities":{"list":{},"resume":{},"close":{},"delete":{},"fork":{},"additionalDirectories":{}},` +
	`"mcpCapabilities":{"http":true,"sse":true},"auth":{"logout":{}}},` +
	`"authMethods":[{"id":"login","type":"terminal","name":"Login with Kimi account",` +
	`"description":"Open the device-code login flow in a terminal.","args":["--login"],"env":{},` +
	`"_meta":{"terminal-auth":{"type":"terminal","label":"Login with Kimi account",` +
	`"command":"/home/operator/.kimi-code/bin/kimi","args":["login"],"env":{}}}}],` +
	`"agentInfo":{"name":"Kimi Code CLI","version":"2.5.3"}}}`

// The two answers to `authenticate`, as that binary gave them: in the operator's home, and in a
// home nobody had signed in to.
const (
	kimiSignedIn  = `{"jsonrpc":"2.0","id":2,"result":{}}`
	kimiSignedOut = `{"jsonrpc":"2.0","id":2,"error":{"code":-32000,"message":"Authentication required"}}`
)

var kimi = Found{
	Kind: agentcli.Kimi, Family: agentcli.FamilyACP,
	Path: "/home/operator/.kimi-code/bin/kimi", ProtocolArgs: []string{"acp"},
}

// kimiSaying is a Kimi that answers with these lines, and a record of what it was asked.
func kimiSaying(lines ...string) (Options, *[]map[string]any, *[]string) {
	var asked []map[string]any
	var startedWith []string
	return Options{
		Run: func(context.Context, string, ...string) ([]byte, error) {
			return nil, errors.New("the protocol question must not run the binary any other way")
		},
		Answer: func(context.Context, string, ...string) ([]byte, error) {
			return nil, errors.New("the protocol question must not run the binary any other way")
		},
		Handshake: func(_ context.Context, _ string, args []string, talk func(io.Writer, io.Reader) error) error {
			startedWith = args
			heard := &capturingWriter{}
			err := talk(heard, strings.NewReader(strings.Join(lines, "\n")+"\n"))
			asked = heard.messages
			return err
		},
		Timeout: time.Second,
	}, &asked, &startedWith
}

func methodsAsked(asked []map[string]any) []string {
	var methods []string
	for _, one := range asked {
		method, _ := one["method"].(string)
		methods = append(methods, method)
	}
	return methods
}

// FR-007t: a CLI with no command to ask is asked in its own protocol.
func TestKimiIsAskedAboutItsSignInOverItsOwnProtocol(t *testing.T) {
	opts, asked, startedWith := kimiSaying(kimiIntroduction, kimiSignedIn)

	if got := AskSignIn(context.Background(), kimi, opts); got != SignedIn {
		t.Fatalf("Kimi answered `{}` to authenticate and was read as %v", got)
	}

	if strings.Join(*startedWith, " ") != "acp" {
		t.Errorf("it was started with %v; the question goes to the program a run is given", *startedWith)
	}
	if got := methodsAsked(*asked); strings.Join(got, " ") != "initialize authenticate" {
		t.Fatalf("it was asked %v, want the handshake and then the one question", got)
	}
	params, _ := (*asked)[1]["params"].(map[string]any)
	if params["methodId"] != "login" {
		t.Errorf("authenticate was sent for %v, want the method its row names", params)
	}
}

func TestKimiSayingAuthenticationRequiredIsSignedOut(t *testing.T) {
	opts, _, _ := kimiSaying(kimiIntroduction, kimiSignedOut)

	if got := AskSignIn(context.Background(), kimi, opts); got != SignedOut {
		t.Fatalf("`-32000 Authentication required` was read as %v", got)
	}
}

// `authenticate` is a question on Kimi because Kimi sends people to a terminal to sign in. An
// agent that stops listing the method, or lists it as one this client is meant to carry out,
// is not sent it: on that agent the same call may begin a sign-in.
func TestAnAgentThatDoesNotListTheMethodAsATerminalSignInIsNotAsked(t *testing.T) {
	for name, introduction := range map[string]string{
		"no auth methods at all": `{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{}}}`,
		"a different method":     `{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"authMethods":[{"id":"api-key","type":"terminal"}]}}`,
		"the method, not at a terminal": `{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,` +
			`"authMethods":[{"id":"login","type":"agent"}]}}`,
		"the method, with no type": `{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"authMethods":[{"id":"login"}]}}`,
	} {
		t.Run(name, func(t *testing.T) {
			opts, asked, _ := kimiSaying(introduction, kimiSignedIn)

			if got := AskSignIn(context.Background(), kimi, opts); got != SignInUnknown {
				t.Errorf("an agent that was not asked was reported as %v", got)
			}
			if got := methodsAsked(*asked); strings.Join(got, " ") != "initialize" {
				t.Errorf("it was sent %v", got)
			}
		})
	}
}

// Not hearing *no* is not hearing *yes*, and the other way round (FR-007r).
func TestAnythingElseKimiSaysIsUnknown(t *testing.T) {
	for name, lines := range map[string][]string{
		"some other refusal":         {kimiIntroduction, `{"jsonrpc":"2.0","id":2,"error":{"code":-32603,"message":"Internal error"}}`},
		"method not found":           {kimiIntroduction, `{"jsonrpc":"2.0","id":2,"error":{"code":-32601,"message":"Method not found"}}`},
		"it stopped talking":         {kimiIntroduction},
		"it never introduced itself": {"Loading..."},
		"it refused the handshake":   {`{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid request"}}`},
	} {
		t.Run(name, func(t *testing.T) {
			opts, _, _ := kimiSaying(lines...)
			if got := AskSignIn(context.Background(), kimi, opts); got != SignInUnknown {
				t.Errorf("read as %v", got)
			}
		})
	}
}

func TestAKimiThatCannotBeStartedIsUnknown(t *testing.T) {
	opts, _, _ := kimiSaying()
	opts.Handshake = func(context.Context, string, []string, func(io.Writer, io.Reader) error) error {
		return errors.New("fork/exec: no such file or directory")
	}
	if got := AskSignIn(context.Background(), kimi, opts); got != SignInUnknown {
		t.Errorf("read as %v", got)
	}

	// Found without the flags its row starts it with: there is nothing to start it as.
	bare := kimi
	bare.ProtocolArgs = nil
	opts, asked, _ := kimiSaying(kimiIntroduction, kimiSignedIn)
	if got := AskSignIn(context.Background(), bare, opts); got != SignInUnknown || len(*asked) != 0 {
		t.Errorf("read as %v after asking %v", got, *asked)
	}
}

// Notifications and banners between the two answers do not derail the second question: one
// reader carries the whole conversation.
func TestTheSignInAnswerIsFoundPastWhateverElseTheAgentSays(t *testing.T) {
	opts, _, _ := kimiSaying(
		"kimi-code starting",
		kimiIntroduction,
		`{"jsonrpc":"2.0","method":"session/update","params":{"update":{}}}`,
		`{"jsonrpc":"2.0","id":1,"result":{"late":"duplicate"}}`,
		kimiSignedOut,
	)
	if got := AskSignIn(context.Background(), kimi, opts); got != SignedOut {
		t.Fatalf("read as %v", got)
	}
}

// Kimi declares both ways of carrying a conversation on, and the workplace is resumable by
// either. One that declared only `resume` would be as well.
func TestKimisHandshakeMakesTheWorkplaceResumable(t *testing.T) {
	opts, _, _ := kimiSaying(kimiIntroduction)
	if got := Probe(context.Background(), kimi, opts); !got.Resumable {
		t.Fatalf("capabilities = %+v", got)
	}

	onlyResume := `{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{` +
		`"loadSession":false,"sessionCapabilities":{"resume":{}}}}}`
	opts, _, _ = kimiSaying(onlyResume)
	if got := Probe(context.Background(), kimi, opts); !got.Resumable {
		t.Fatalf("an agent that resumes without loading was registered as not resumable: %+v", got)
	}
}
