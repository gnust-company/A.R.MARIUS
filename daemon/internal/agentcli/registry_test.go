package agentcli

import (
	"strings"
	"testing"
)

// The name a run arrives under is the key, and there is exactly one row per name. Two rows for
// one kind would be two different accounts of the same CLI, and which one a caller got would
// depend on which line was written first.
func TestEveryKindIsNamedOnceAndSpelledTheServersWay(t *testing.T) {
	seen := map[Kind]bool{}
	for _, row := range All() {
		if row.Kind == "" {
			t.Fatalf("a row with no kind: %+v", row)
		}
		if seen[row.Kind] {
			t.Errorf("%s has two rows", row.Kind)
		}
		seen[row.Kind] = true

		found, known := Lookup(string(row.Kind))
		if !known || found.Kind != row.Kind {
			t.Errorf("%s cannot be looked up by the name a run arrives under", row.Kind)
		}
	}
}

// FR-039: both protocol families are represented from the start, so the boundary between them
// is forced to be right early rather than discovered later around a single family.
func TestBothProtocolFamiliesAreRepresented(t *testing.T) {
	counted := map[Family]int{}
	for _, row := range All() {
		counted[row.Family]++
	}
	for _, family := range []Family{FamilyACP, FamilyOneShot, FamilyAppServer} {
		if counted[family] == 0 {
			t.Errorf("no CLI of the %s family is declared", family)
		}
	}
}

// Every row has a family, and it is one of the three. A row that named a fourth would be a
// workplace registered under a protocol nothing on this machine can speak.
func TestNoRowClaimsAFamilyNobodyCanSpeak(t *testing.T) {
	spoken := map[Family]bool{FamilyACP: true, FamilyOneShot: true, FamilyAppServer: true}
	for _, row := range All() {
		if !spoken[row.Family] {
			t.Errorf("%s is declared as family %q, which is none of the three", row.Kind, row.Family)
		}
	}
}

// A row is all of a CLI or none of it.
//
// The half-filled row is the failure this table exists to make impossible. Before it, the same
// facts sat in six maps in five files, and leaving a CLI out of one of them was not a compile
// error — it was a daemon that registered the workplace, took the work, started the agent and
// handed it a brief written to a file that CLI never opens. Whole or blank; there is no third
// state a reader has to guess about.
func TestARowIsAllOfACLIOrNoneOfIt(t *testing.T) {
	for _, row := range All() {
		missing := row.Undeclared()
		if len(missing) != 0 && len(missing) != 4 {
			t.Errorf("%s declares some of what a run needs and not the rest: missing %v",
				row.Kind, missing)
		}
		if Ready(string(row.Kind)) != (len(missing) == 0) {
			t.Errorf("%s is %v by Ready and %v by what it declares",
				row.Kind, Ready(string(row.Kind)), len(missing) == 0)
		}
	}
}

// Gemini's row is the one written from a measurement rather than from documentation, so what
// was measured is pinned here.
//
// The distinction FR-039a draws is between guessing and knowing, not between waiting and
// writing. Two things were watched happening on `gemini 0.56.0` and they are the two that
// decide whether any of the rest can be true: the flag starts an ACP peer when a program starts
// it with no terminal, and the trust gate exists. The four paths come from the bundle the
// binary ships. If a working account ever contradicts one of them, this test is where the
// correction lands.
func TestGeminisRowSaysWhatWasMeasured(t *testing.T) {
	row, known := Lookup(string(Gemini))
	if !known {
		t.Fatal("Gemini is not in the registry at all, so this machine would not even look for it")
	}
	if !Ready(string(Gemini)) {
		t.Fatalf("Gemini is missing %v", row.Undeclared())
	}
	if row.Family != FamilyACP {
		t.Errorf("Gemini is declared %q, and the handshake that was measured is ACP", row.Family)
	}
	if row.ContextFile != "GEMINI.md" {
		t.Errorf("the brief goes to %q, want GEMINI.md", row.ContextFile)
	}
	// In the home, not the working directory: the personal skills directory is read without a
	// trust decision, and the home is built fresh for each run.
	if row.Skills.Path != ".gemini/skills" || !row.Skills.InHome {
		t.Errorf("skills go to %+v, want .gemini/skills inside the home", row.Skills)
	}
	// Redirecting the home is the only lever: GEMINI_DIR is a constant in the bundle, not a
	// variable it reads.
	if len(row.HomeVars) != 1 || row.HomeVars[0].Variable != "HOME" || row.HomeVars[0].Path != "" {
		t.Errorf("Gemini is pointed at its home by %+v, want HOME alone", row.HomeVars)
	}
}

// The gate that would have made the whole row a silent no-op.
//
// Gemini will not read project-level configuration out of a folder nobody has trusted, and the
// daemon makes a fresh folder for every task, which nobody ever has. Untrusted, it writes a line
// to its error stream and carries on with the brief unread — which on every screen looks like an
// agent that was told everything and did nothing.
func TestGeminiIsToldTheRunsOwnFolderMayBeRead(t *testing.T) {
	row, _ := Lookup(string(Gemini))
	for _, v := range row.Env {
		if v.Name == "GEMINI_CLI_TRUST_WORKSPACE" {
			if v.Value != "true" {
				t.Fatalf("the trust variable is set to %q, and only \"true\" opens the gate", v.Value)
			}
			return
		}
	}
	t.Fatal("Gemini is not told the run's own folder may be read, so its brief goes unopened")
}

// Nothing here may carry a secret. These land in the environment of a program this daemon does
// not own, and the one rule about that environment is that a run sees what a rule put there
// (FR-014c) — a credential in a table read by every machine is not that.
func TestNoRowSmugglesACredentialIntoTheEnvironment(t *testing.T) {
	for _, row := range All() {
		for _, v := range row.Env {
			if v.Name == "" || v.Value == "" {
				t.Errorf("%s declares an unusable variable %+v", row.Kind, v)
			}
			for _, smell := range []string{"TOKEN", "SECRET", "PASSWORD", "KEY", "CREDENTIAL"} {
				if strings.Contains(v.Name, smell) {
					t.Errorf("%s declares %s, which reads like a credential — those are minted "+
						"per run, never carried in a table", row.Kind, v.Name)
				}
			}
		}
	}
}

// A kind nobody has heard of and a row with nothing in it answer the same, because they mean
// the same thing to whoever asked: there is nothing here to set a run up from.
func TestAKindNobodyHasHeardOfIsMissingEverything(t *testing.T) {
	missing := Undeclared("a-cli-that-does-not-exist")
	if len(missing) != 4 {
		t.Errorf("an unknown kind is missing %v, want all four facts", missing)
	}
	if Ready("a-cli-that-does-not-exist") {
		t.Error("an unknown kind was reported ready to run work")
	}
}

// The table is handed out as a copy. A caller that sorted or trimmed what it got back would
// otherwise be editing what every other caller reads.
func TestTheTableCannotBeEditedByWhoeverReadsIt(t *testing.T) {
	got := All()
	if len(got) == 0 {
		t.Fatal("the registry is empty")
	}
	got[0].ContextFile = "SOMETHING_ELSE.md"

	again := All()
	if again[0].ContextFile == "SOMETHING_ELSE.md" {
		t.Error("editing what All returned changed the registry itself")
	}
}

// Silences reports what a row actually declares and nothing else. A zero is not a threshold of
// zero — it is a CLI that has no threshold of its own, and reporting it as one would hand the
// watchdog a number that cuts every run instantly.
func TestOnlyARealThresholdIsReportedAsOne(t *testing.T) {
	declared := Silences()
	for _, row := range All() {
		got, reported := declared[string(row.Kind)]
		switch {
		case row.Silence > 0 && got != row.Silence:
			t.Errorf("%s declares %s and Silences says %s", row.Kind, row.Silence, got)
		case row.Silence <= 0 && reported:
			t.Errorf("%s declares no threshold of its own and Silences reported %s", row.Kind, got)
		}
	}
	for cli, threshold := range declared {
		if threshold <= 0 {
			t.Errorf("%s was reported with a threshold of %s", cli, threshold)
		}
	}
}

// Every lifetime a row uses can say what it is. A store path and every error about one are
// built out of these words, and an unnamed lifetime turns both into a number.
func TestEveryLifetimeARowUsesHasAName(t *testing.T) {
	for _, row := range All() {
		for _, entry := range row.Home {
			name := entry.Lifetime.String()
			if name == "" || strings.HasPrefix(name, "lifetime(") {
				t.Errorf("%s declares a home entry at %s whose lifetime renders as %q",
					row.Kind, entry.Path, name)
			}
		}
	}
	// The fallback still names itself, so a lifetime added without a word for it shows up in an
	// error message as the number it is rather than as an empty string.
	if unknown := Lifetime(99).String(); unknown != "lifetime(99)" {
		t.Errorf("an unknown lifetime renders as %q, want it to name itself", unknown)
	}
}

// A threshold declared here is a claim about how long a tool goes quiet while still working.
// Nobody has measured that for any of these, and a number invented would end runs that were
// fine — so the honest content today is none, and this says so out loud rather than leaving it
// to be noticed.
func TestNoThresholdIsDeclaredOnAGuess(t *testing.T) {
	if declared := Silences(); len(declared) != 0 {
		t.Errorf("thresholds are declared for %v — if they were measured, say where, and delete this test",
			declared)
	}
}
