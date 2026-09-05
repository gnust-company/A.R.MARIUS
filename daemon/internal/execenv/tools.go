package execenv

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
)

// CallbackProgram is the name an agent types to call Armarius back (FR-013a).
//
// The skill sheet the agent is given teaches this name and nothing else — no address, no
// credential, no flags carrying either. For the name to be typeable, something has to put a
// program under it on a machine we do not own and on a search path the agent's CLI actually
// consults, which is what this file is for.
const CallbackProgram = "armarius"

// Where the callback program is put, relative to the task's working directory.
//
// Under `.armarius/` with the run homes rather than at the top of the working directory: the
// working directory is the agent's to work in, and a directory of ours appearing in the middle
// of its files is one it may reasonably tidy away. The sweep already reclaims everything under
// here along with the directory itself (FR-021), so nothing new has to learn that it exists.
const toolsSubdir = ".armarius/bin"

// mcpConfigs says where a CLI reads a **per-run** tool declaration from, relative to the working
// directory (FR-013a).
//
// A CLI absent from this table is not being neglected: it gets the command face, which is the
// baseline precisely so that no CLI depends on being in a table like this one.
//
//   - Claude Code takes `--mcp-config <file>`, measured on version 2.1.226 — the same version
//     every other Claude Code fact here was measured on. Deliberately **not** written to
//     `.mcp.json` at the top of the working directory, which is the project-scoped file: that
//     one has to be approved interactively before it loads, and there is nobody at this machine
//     to approve it. A file named on the command line loads without asking, and naming it per
//     run is what FR-013a asks for.
//   - Codex is absent because there is no file for it to read. It keeps MCP servers in the same
//     `config.toml` that this daemon links straight to the operator's own, so declaring anything
//     there would be writing into shared configuration, which FR-013a forbids outright. Its
//     answer is a command-line override instead, rendered where its command line is built
//     (`runtime.toolFlags`) — the same per-run, writes-nothing shape as the file, spelled the way
//     that CLI accepts.
//   - Gemini CLI is absent for the reason it is absent from every table in this package
//     (FR-039a, task T013).
var mcpConfigs = map[string]string{
	"claude_code": ".armarius/mcp.json",
}

// ToolServer is one program a CLI can load tools from, in the only shape both native faces need.
//
// There is one of these per run and it is always the same program — the point of the type is
// that the two faces are rendered from one value rather than described twice.
type ToolServer struct {
	// Name is what the CLI will call this collection of tools.
	Name string `json:"-"`
	// Command is the program to start, at the path the agent reaches it by.
	Command string `json:"command"`
	// Args is how it is asked to speak the tool protocol rather than act as a command.
	Args []string `json:"args,omitempty"`
}

// Tools is what one run was given to call Armarius back with.
type Tools struct {
	// Dir is put at the front of the search path, so the command face answers to its name from
	// anywhere under the working directory.
	Dir string
	// Program is the callback program itself, at the path the agent reaches it by.
	Program string
	// ConfigFile is the native declaration written for this run, and is empty for a CLI that
	// reads none. Empty is not a degraded run: the command face is the same commands.
	ConfigFile string
	// Servers is that same declaration in structured form, for the protocol family that carries
	// it inline in the handshake instead of reading it from a file.
	Servers []ToolServer
}

// ToolsSpec is what placing one run's tools needs to know.
type ToolsSpec struct {
	// CLI is the kind of agent CLI, spelled the way the server spells it.
	CLI string
	// WorkDir is the task's working directory, which is where the agent is started.
	WorkDir string
	// Program is the callback program on this machine — the real one, which this run gets its
	// own reachable path to.
	Program string
}

// PlaceTools puts the callback program where this run's agent can reach it, and declares it to
// the CLIs that load tools (FR-013, FR-013a).
//
// **It refuses rather than continues.** A run set up without the callback program is a run whose
// agent is holding a sheet of instructions naming a command that does not exist: every call it
// makes fails with *command not found*, which no code here would see and no event would report.
// Refusing puts the run back on the shelf with a reason written down, which is the failure this
// machine can actually be fixed from.
//
// A link, not a copy. The program is the same one for every run on this machine, and a copy per
// task would age past the daemon that placed it — a machine upgraded mid-life would then hand
// half its runs an old callback and never say so. Machines that cannot make links do not host
// workplaces at all (see ProbeLinks), so there is no case here where a link is unavailable and a
// copy would have been.
func PlaceTools(spec ToolsSpec) (Tools, error) {
	if spec.WorkDir == "" {
		return Tools{}, fmt.Errorf("placing the callback program needs the task's working directory")
	}
	if spec.Program == "" {
		return Tools{}, fmt.Errorf(
			"refusing to set up a run with no %s program to hand it: the agent is told to call it by name",
			CallbackProgram,
		)
	}
	if _, err := os.Stat(spec.Program); err != nil {
		return Tools{}, fmt.Errorf("the %s program is not at %s: %w", CallbackProgram, spec.Program, err)
	}

	dir := filepath.Join(spec.WorkDir, filepath.FromSlash(toolsSubdir))
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return Tools{}, fmt.Errorf("making room for the %s program: %w", CallbackProgram, err)
	}

	program := filepath.Join(dir, CallbackProgram+exeSuffix())
	// Removed and remade rather than left alone, for the same reason the brief is: what is
	// already there was put there by an earlier run of this task, possibly by an earlier build
	// of this daemon, and possibly by the agent itself.
	if err := os.RemoveAll(program); err != nil {
		return Tools{}, fmt.Errorf("clearing the previous %s program: %w", CallbackProgram, err)
	}
	if err := os.Symlink(spec.Program, program); err != nil {
		return Tools{}, fmt.Errorf("putting the %s program where the agent can reach it: %w", CallbackProgram, err)
	}

	tools := Tools{
		Dir:     dir,
		Program: program,
		Servers: []ToolServer{{Name: CallbackProgram, Command: program, Args: []string{"mcp"}}},
	}

	rel, declares := mcpConfigs[spec.CLI]
	if !declares {
		return tools, nil
	}
	path := filepath.Join(spec.WorkDir, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return Tools{}, fmt.Errorf("making room for the tool declaration of %s: %w", spec.CLI, err)
	}
	declaration, err := json.MarshalIndent(mcpDeclaration(tools.Servers), "", "  ")
	if err != nil {
		return Tools{}, fmt.Errorf("writing the tool declaration of %s: %w", spec.CLI, err)
	}
	if err := os.WriteFile(path, append(declaration, '\n'), 0o600); err != nil {
		return Tools{}, fmt.Errorf("writing the tool declaration of %s: %w", spec.CLI, err)
	}
	tools.ConfigFile = path
	return tools, nil
}

// mcpDeclaration is the file shape the tool protocol's own configuration uses: servers by name.
func mcpDeclaration(servers []ToolServer) map[string]any {
	byName := make(map[string]ToolServer, len(servers))
	for _, s := range servers {
		byName[s.Name] = s
	}
	return map[string]any{"mcpServers": byName}
}

// CallbackBeside is where the callback program is expected to be found: next to the daemon.
//
// The two are one release and travel in one archive, so the daemon's own location is the only
// answer that stays true after the operator moves the installation, renames the directory, or
// keeps two versions side by side. Looking it up on the search path instead would find whichever
// one happened to be there — including, on a developer's machine, a build from last week.
func CallbackBeside(daemon string) string {
	if daemon == "" {
		return ""
	}
	return filepath.Join(filepath.Dir(daemon), CallbackProgram+exeSuffix())
}

// exeSuffix is what an executable is called on this operating system. Windows resolves a bare
// name on the search path by appending this, so the placed program has to carry it or the agent
// types a name nothing answers to.
func exeSuffix() string {
	if runtime.GOOS == "windows" {
		return ".exe"
	}
	return ""
}
