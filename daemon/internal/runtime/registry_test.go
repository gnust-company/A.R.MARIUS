package runtime

import (
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/agentcli"
)

// FR-035, FR-037: two protocol families, one contract, and nothing above this package learns
// that either exists. Both are the same interface or the promise is not kept.
func TestBothFamiliesAreDrivenThroughTheOneContract(t *testing.T) {
	var engines = map[agentcli.Family]Runtime{
		agentcli.FamilyOneShot: OneShot{},
		agentcli.FamilyACP:     ACP{},
	}
	for _, row := range agentcli.All() {
		if _, driven := engines[row.Family]; !driven {
			t.Errorf("%s belongs to family %q and nothing here can run one", row.Kind, row.Family)
		}
	}
}

// The two halves of *this daemon can run that CLI* must agree.
//
// They are deliberately in different places: what a CLI **is** — where its brief goes, where it
// looks for skills, what its home holds — is a row in the registry, and how you **start** one is
// code here, because starting takes closures over a request and a reader for its output. That is
// the right seam, and it is exactly the seam that drifts. A row filled in for a CLI nothing here
// can start makes the machine ask for work it will fail to begin; an invocation for a kind whose
// row is blank makes it start a CLI and hand it a brief written where that CLI never looks.
//
// So the two are held against each other rather than trusted to stay in step, and the test names
// what to do in either direction: fill the row in, or delete the invocation.
func TestWhatCanBeStartedAndWhatIsDeclaredAreTheSameSet(t *testing.T) {
	for _, row := range agentcli.All() {
		kind := string(row.Kind)
		declared, canStart := agentcli.Ready(kind), startable(kind)
		switch {
		case declared && !canStart:
			t.Errorf("%s has a full row and nothing here starts it: a machine would ask for work "+
				"it cannot begin", kind)
		case !declared && canStart:
			t.Errorf("%s can be started and its row is missing %v: the agent would be handed a "+
				"brief written where it never looks", kind, agentcli.Undeclared(kind))
		}
		if Supported(kind) != (declared && canStart) {
			t.Errorf("%s: Supported says %v while the two halves say %v and %v",
				kind, Supported(kind), declared, canStart)
		}
	}
}

// Nothing here knows how to start a CLI the registry has never heard of. An invocation under a
// name no row carries is one nothing will ever reach — the name a run arrives under comes from
// the server, out of a workplace this machine registered off the same table.
func TestNothingIsStartableUnderANameTheRegistryDoesNotCarry(t *testing.T) {
	known := map[string]bool{}
	for _, row := range agentcli.All() {
		known[string(row.Kind)] = true
	}
	for kind := range oneShots {
		if !known[kind] {
			t.Errorf("a one-shot invocation is written for %q, which is in no row", kind)
		}
	}
	for kind := range acpFlags {
		if !known[kind] {
			t.Errorf("an ACP invocation is written for %q, which is in no row", kind)
		}
	}
}

// Gemini is the case the two halves exist to handle, so it is checked as itself: known of,
// registered as a workplace, and not asked for work (FR-039a, task T013).
func TestGeminiIsNotAskedForWorkWhileItsAnswersAreUnmeasured(t *testing.T) {
	if Supported(string(agentcli.Gemini)) {
		t.Fatal("this build claims it can drive Gemini CLI — a run there would fail during setup, " +
			"go back on the shelf, and be offered to this same machine again")
	}
}

// A kind nobody has heard of is not supported, and asking is not an error.
func TestAKindThisMachineHasNeverHeardOfIsSimplyNotSupported(t *testing.T) {
	if Supported("a-cli-that-does-not-exist") {
		t.Error("an unknown kind was reported as one this daemon can drive")
	}
}
