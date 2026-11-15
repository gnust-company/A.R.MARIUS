package discovery

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"strings"
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// liveKimi names the switch that lets these tests start the Kimi Code installed on this machine.
//
// Off unless somebody sets it, because what it does is not a unit test's business: it starts
// the operator's own login shell and their own CLI. Nothing here runs a turn or spends anything
// on anybody's account — see cmd/armarius-daemon for the test that does.
const liveKimi = "ARMARIUS_LIVE_KIMI"

// The whole of what discovery says about a real Kimi Code, start to finish (FR-002a, FR-039g,
// FR-007t): found through the login shell from a search path that does not have it, asked its
// version, asked what it can do, and asked whether anybody is signed in.
//
// Only Kimi is looked for. The other rows are answered *not installed* without looking, so this
// never starts any other CLI that happens to be on the machine.
func TestLiveKimiIsFoundAskedAndSignedIn(t *testing.T) {
	if os.Getenv(liveKimi) == "" {
		t.Skipf("set %s=1 to run this against the Kimi Code installed here", liveKimi)
	}
	// The search path a daemon gets when nothing has read the operator's startup files.
	t.Setenv("PATH", "/usr/local/bin:/usr/bin:/bin")
	if _, err := exec.LookPath("kimi"); err == nil {
		t.Skip("kimi is on the bare system path here, so there is nothing for the shell to add")
	}

	ctx := context.Background()
	swept := Discover(ctx, Options{
		LookPath: func(string) (string, error) { return "", errors.New("not on the daemon's path") },
		Elsewhere: func(ctx context.Context, _ []string) map[string]string {
			return askLoginShell(ctx, []string{"kimi"})
		},
	})
	if len(swept.Found) != 1 || swept.Found[0].Kind != agentcli.Kimi {
		t.Fatalf("found %+v, skipped %+v; want Kimi and nothing else", swept.Found, swept.Skipped)
	}
	kimi := swept.Found[0]
	t.Logf("found at %s, version %q, started with %v", kimi.Path, kimi.Version, kimi.ProtocolArgs)
	if !strings.HasSuffix(kimi.Path, "/kimi") || kimi.Version == "" {
		t.Errorf("found = %+v", kimi)
	}

	answered := Probe(ctx, kimi, Options{})
	t.Logf("capabilities: %+v", answered)
	if !answered.Resumable {
		t.Errorf("a Kimi that declares session/resume was registered as not resumable: %+v", answered)
	}

	said := AskSignIn(ctx, kimi, Options{})
	t.Logf("sign-in: %s", said)
	if said == SignInUnknown {
		t.Errorf("the installed Kimi could not be asked about its sign-in")
	}
}
