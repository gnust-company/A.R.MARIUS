package callback

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"sort"
	"strings"
)

// Writes to stdout and stderr in this file discard their error deliberately, and say so with
// `_, _ =` rather than by leaving it out. There is nothing to do about a failed write to the
// stream you were going to report the failure on, and the exit code — which is what the CLI
// answers with — has already been decided by the time anything is printed.

// RunCLI is the command face: the whole program, with its edges handed in so a test can drive it.
//
// **stdout always carries the answer, and it is always JSON.** On success it is what Armarius
// said, whole and unedited — this program carries an answer to the agent, it does not summarise
// one, and every field it dropped would be a field the agent could not act on. On a refusal it
// is the refusal, with its code and the parameters that fill it, because an agent told only an
// English sentence cannot tell *which rule* said no (FR-084a).
//
// stderr carries one plain line for whoever is reading the log. The exit code says which of the
// five things happened; see the constants in client.go.
func RunCLI(ctx context.Context, args []string, env Environment, stdout, stderr io.Writer) int {
	if err := RefuseCredentialsInArguments(args); err != nil {
		return report(stdout, stderr, &Failure{Code: ExitUsage, Err: err})
	}

	available := Commands(env)
	if len(args) == 0 || isHelp(args[0]) {
		printHelp(stdout, env, available)
		return ExitOK
	}

	name, rest := match(available, args)
	cmd, found := Find(available, name)
	if !found {
		printHelp(stderr, env, available)
		return report(stdout, stderr, &Failure{
			Code: ExitUsage,
			Err:  fmt.Errorf("no such command: %s", strings.Join(args, " ")),
		})
	}

	parsed, err := parseFlags(cmd, rest, stderr)
	if err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return ExitOK
		}
		return report(stdout, stderr, &Failure{Code: ExitUsage, Err: err})
	}
	if missing := cmd.Missing(parsed); len(missing) > 0 {
		return report(stdout, stderr, &Failure{
			Code: ExitUsage,
			Err:  fmt.Errorf("%s needs -%s", cmd.Name, strings.Join(missing, " and -")),
		})
	}

	answer, err := cmd.Call(ctx, NewClient(env), parsed)
	if err != nil {
		return report(stdout, stderr, err)
	}
	writeJSON(stdout, answer)
	return ExitOK
}

// match finds the longest command name that the arguments begin with, so that two-word names
// (`task show`) and one-word names (`whoami`) are dispatched by the same rule.
func match(available []Command, args []string) (string, []string) {
	for words := 2; words >= 1; words-- {
		if len(args) < words {
			continue
		}
		candidate := strings.Join(args[:words], " ")
		if _, ok := Find(available, candidate); ok {
			return candidate, args[words:]
		}
	}
	return args[0], args[1:]
}

// parseFlags turns one command's declared parameters into flags and reads them off the arguments.
//
// Declared once, in the registry, and rendered here — so a parameter added for the MCP face is a
// flag on this one without anybody adding it twice.
func parseFlags(cmd Command, args []string, out io.Writer) (Args, error) {
	fs := flag.NewFlagSet(cmd.Name, flag.ContinueOnError)
	fs.SetOutput(out)
	fs.Usage = func() {
		_, _ = fmt.Fprintf(out, "%s — %s\n\n", cmd.Name, cmd.Summary)
		fs.PrintDefaults()
	}

	strs := map[string]*string{}
	bools := map[string]*bool{}
	for _, p := range cmd.Params {
		switch p.Type {
		case TypeBoolean:
			bools[p.Name] = fs.Bool(p.Name, false, p.Description)
		default:
			strs[p.Name] = fs.String(p.Name, "", p.Description)
		}
	}
	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	if extra := fs.Args(); len(extra) > 0 {
		return nil, fmt.Errorf("%s does not take %q — everything it needs is a flag", cmd.Name, extra[0])
	}

	// Only what was actually given. A flag left alone must stay absent from the request rather
	// than travel as an empty string: the server reads an explicit empty value as *set this to
	// nothing*, which is a different instruction from *leave it alone*.
	given := map[string]bool{}
	fs.Visit(func(f *flag.Flag) { given[f.Name] = true })

	parsed := Args{}
	for name, value := range strs {
		if given[name] {
			parsed[name] = *value
		}
	}
	for name, value := range bools {
		if given[name] {
			parsed[name] = *value
		}
	}
	return parsed, nil
}

func isHelp(arg string) bool {
	switch arg {
	case "help", "-h", "-help", "--help":
		return true
	}
	return false
}

func printHelp(w io.Writer, env Environment, available []Command) {
	_, _ = fmt.Fprint(w, "armarius — talk to Armarius about the work you were given.\n\n")
	switch {
	case env.TaskID != "":
		_, _ = fmt.Fprint(w, "This run is about one task. These are the commands it has:\n\n")
	case env.ProjectID != "":
		_, _ = fmt.Fprint(w, "This run is about a project. These are the commands it has:\n\n")
	default:
		_, _ = fmt.Fprint(w, "This run is about no particular task or project. These are the commands it has:\n\n")
	}

	names := make([]string, 0, len(available))
	width := 0
	for _, cmd := range available {
		names = append(names, cmd.Name)
		if len(cmd.Name) > width {
			width = len(cmd.Name)
		}
	}
	sort.Strings(names)
	for _, name := range names {
		cmd, _ := Find(available, name)
		_, _ = fmt.Fprintf(w, "  %-*s  %s\n", width, cmd.Name, cmd.Summary)
	}
	_, _ = fmt.Fprint(w, "\nRun \"armarius <command> -h\" for what one command takes.\n")
}

// report writes the one line a person reads, puts the machine-readable half where the agent
// looks for it, and hands back the exit code the failure deserves.
//
// The refusal goes to **stdout**, beside where an answer would have been, because that is the
// one place an agent has to look either way. A refusal that only ever reached stderr would leave
// the agent parsing an empty stdout and guessing at what went wrong from an exit code.
func report(stdout, stderr io.Writer, err error) int {
	var failure *Failure
	if !errors.As(err, &failure) {
		failure = &Failure{Code: ExitRefused, Err: err}
	}
	if len(failure.Body) > 0 {
		writeJSON(stdout, failure.Body)
	}
	_, _ = fmt.Fprintf(stderr, "armarius: %v\n", failure.Err)
	return failure.Code
}

// writeJSON puts the answer on stdout, always as JSON and always ending in a newline, so a
// caller reading line by line is not left waiting for one.
func writeJSON(w io.Writer, answer json.RawMessage) {
	if len(answer) == 0 {
		_, _ = fmt.Fprintln(w, "{}")
		return
	}
	_, _ = fmt.Fprintln(w, strings.TrimRight(string(answer), "\n"))
}
