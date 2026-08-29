// Command armarius is what an agent calls Armarius back with while a run of its own is open.
//
// The daemon puts this binary where the run can reach it and starts the agent with the run's own
// credential in its environment (FR-013a, FR-013c). The agent then simply runs commands:
//
//	armarius task show
//	armarius task comment -body "Started on the parser."
//	armarius task publish -name report.md -content "..."
//
// It never learns a URL, never handles a token, and is never told which task it is on — all
// three come from the environment the daemon built, and an identifier the agent had to go
// looking for is one it could find somebody else's copy of.
//
// The same binary is also an MCP server, for the CLIs that load tools:
//
//	armarius mcp
//
// One binary and one list of commands, two faces (FR-013a). Two installations would be two lists
// of what the agent can do, and they would come apart on the day somebody added a command to one
// of them.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/gnust-company/armarius-daemon/internal/callback"
)

func main() {
	// A signal cancels the context rather than killing the process: a call already on its way to
	// Armarius should be given the chance to be abandoned cleanly, not left half-sent.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	env := callback.FromEnvironment(os.Getenv)
	args := os.Args[1:]

	if len(args) > 0 && args[0] == "mcp" {
		os.Exit(callback.ServeMCP(ctx, env, os.Stdin, os.Stdout, os.Stderr))
	}
	os.Exit(callback.RunCLI(ctx, args, env, os.Stdout, os.Stderr))
}
