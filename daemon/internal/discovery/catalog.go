package discovery

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
)

// Asking a tool for its model catalog rather than reading examples off its help (FR-007k,
// revised 2026-10-26).
//
// Claude Code has no flag that lists models, which is why the first version of this read the
// three aliases `--help` quotes and offered them as examples. It does answer the question, just
// not on the command line: its stream-json control protocol replies to a `list_models` control
// request with the same rows its own `/model` picker shows, computed by the installed binary for
// the signed-in account. Multica asks exactly this, and so does this file.
//
// No user message is ever written, so no model runs and nothing is billed: the CLI answers the
// control request, sees its input end, and exits. Measured on claude 2.1.301 on 2026-10-26:
// thirteen rows, about two seconds.
//
// Anything short of a usable answer — a CLI too old to know the request, a timeout, a reply that
// does not parse, a list with nothing selectable — is a failure, and the caller keeps what
// `--help` said. A partial answer is never offered as the catalog.

// catalogQuestion is how one tool is asked for its catalog, and which choices the answer feeds.
type catalogQuestion struct {
	// key is the choice the catalog replaces — the examples read off `--help` for it.
	key string
	// narrows is the choice each catalog row may narrow: the levels that model takes.
	narrows string
	// args start the tool in the mode that speaks the control protocol.
	args []string
}

// claudeCatalog is Claude Code's question.
//
// `--strict-mcp-config` with no `--mcp-config` means no MCP servers at all. Asking for a list of
// models has no use for the person's servers, and one that starts a container would make the
// question arbitrarily slow and arbitrarily side-effecting.
var claudeCatalog = catalogQuestion{
	key:     ChoiceModel,
	narrows: ChoiceThinkingLevel,
	args: []string{
		"--print",
		"--verbose",
		"--input-format", "stream-json",
		"--output-format", "stream-json",
		"--strict-mcp-config",
	},
}

// catalogRequestID labels the request so its reply can be picked out of the stream.
const catalogRequestID = "armarius-list-models"

// defaultModelValue is the picker row meaning *whatever this CLI resolves to*. Blank already
// means that here (FR-007k), so it is not offered as a pick of its own.
const defaultModelValue = "default"

// errCatalogUnsupported marks a CLI that answered and said it does not know the request.
var errCatalogUnsupported = errors.New("the CLI does not know the list_models request")

// catalogModel is one row of Claude Code's catalog.
type catalogModel struct {
	Value                 string   `json:"value"`
	ResolvedModel         string   `json:"resolvedModel"`
	DisplayName           string   `json:"displayName"`
	SupportsEffort        bool     `json:"supportsEffort"`
	SupportedEffortLevels []string `json:"supportedEffortLevels"`
	Disabled              bool     `json:"disabled"`
}

// catalogReply is the control-protocol envelope. The doubled `response` is Claude Code's shape:
// the outer one is the envelope, the inner one the payload.
type catalogReply struct {
	Type     string `json:"type"`
	Response struct {
		Subtype   string `json:"subtype"`
		RequestID string `json:"request_id"`
		Error     string `json:"error"`
		Response  struct {
			Models []catalogModel `json:"models"`
		} `json:"response"`
	} `json:"response"`
}

// askCatalog starts the tool, asks for its catalog, and turns the answer into the choice it
// replaces. False means there is no catalog to offer, and the caller keeps what it had.
func askCatalog(ctx context.Context, found Found, opts Options, question catalogQuestion) (Choice, bool) {
	ctx, cancel := context.WithTimeout(ctx, opts.Timeout)
	defer cancel()

	var rows []catalogModel
	err := opts.Handshake(ctx, found.Path, question.args, func(to io.Writer, from io.Reader) error {
		var asked error
		rows, asked = requestCatalog(to, from)
		return asked
	})
	if err != nil {
		return Choice{}, false
	}
	return choiceFromCatalog(rows, question)
}

// requestCatalog writes the one request and reads until its reply.
func requestCatalog(to io.Writer, from io.Reader) ([]catalogModel, error) {
	request, err := json.Marshal(map[string]any{
		"type":       "control_request",
		"request_id": catalogRequestID,
		"request":    map[string]any{"subtype": "list_models"},
	})
	if err != nil {
		return nil, err
	}
	if _, err := to.Write(append(request, '\n')); err != nil {
		return nil, fmt.Errorf("asking for the model catalog: %w", err)
	}
	// Ending the input is what makes this one question rather than a session: the CLI answers,
	// sees the end, and exits by itself.
	if closer, ok := to.(io.Closer); ok {
		_ = closer.Close()
	}

	lines := bufio.NewScanner(from)
	// A catalog line carries every model with its levels; the default 64 KiB is closer to a
	// limit than it looks.
	lines.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for lines.Scan() {
		var reply catalogReply
		if json.Unmarshal(lines.Bytes(), &reply) != nil {
			// The stream is shared with whatever else the session prints; a line that is not
			// ours is skipped, not taken for corruption.
			continue
		}
		if reply.Type != "control_response" || reply.Response.RequestID != catalogRequestID {
			continue
		}
		if reply.Response.Subtype != "success" {
			said := strings.TrimSpace(reply.Response.Error)
			if strings.Contains(strings.ToLower(said), "unsupported control request subtype") {
				return nil, fmt.Errorf("%w: %s", errCatalogUnsupported, said)
			}
			return nil, fmt.Errorf("the model catalog was refused: %s", said)
		}
		return reply.Response.Response.Models, nil
	}
	if err := lines.Err(); err != nil {
		return nil, err
	}
	return nil, errors.New("the CLI ended without answering the model catalog request")
}

// choiceFromCatalog projects the catalog rows onto the one choice they replace.
//
// Keyed by the model a row **resolves to**, which is what is stored on the agent and handed to
// `--model`, as Multica stores it: two tokens often name one model (`default` and `opus` both run
// Opus 5.5 today), and the resolved name is the one that does not move under the person. Rows the
// CLI greys out are left out — they cannot be run from here. Each row's levels become a narrowing
// of the other choice: an empty list says this model takes no level at all.
func choiceFromCatalog(rows []catalogModel, question catalogQuestion) (Choice, bool) {
	choice := Choice{
		Key:     question.key,
		Source:  SourceToolListed,
		Labels:  map[string]string{},
		Narrows: map[string]map[string][]string{},
	}
	seen := map[string]bool{}
	add := func(row catalogModel, id string) {
		seen[id] = true
		choice.Values = append(choice.Values, id)
		if label := strings.TrimSpace(row.DisplayName); label != "" && label != id {
			choice.Labels[id] = label
		}
		if levels, narrowed := levelsOf(row); narrowed {
			choice.Narrows[id] = map[string][]string{question.narrows: levels}
		}
	}

	var fallback *catalogModel
	for i := range rows {
		row := rows[i]
		id := modelID(row)
		if id == "" || row.Disabled {
			continue
		}
		if strings.TrimSpace(row.Value) == defaultModelValue {
			fallback = &rows[i]
			continue
		}
		if !seen[id] {
			add(row, id)
		}
	}
	// The default row usually names a model another row names too, and then it adds nothing.
	// When it does not — an install restricted to one model can look like this — it is the
	// only way to that model, so it is kept.
	if fallback != nil {
		if id := modelID(*fallback); !seen[id] {
			add(*fallback, id)
		}
	}
	if len(choice.Values) == 0 {
		return Choice{}, false
	}
	return choice, true
}

func modelID(row catalogModel) string {
	if id := strings.TrimSpace(row.ResolvedModel); id != "" {
		return id
	}
	return strings.TrimSpace(row.Value)
}

// levelsOf says which levels a model takes, and whether the row said anything at all. A model
// that does not take a level narrows the other choice to nothing; one that takes levels without
// naming them narrows nothing.
func levelsOf(row catalogModel) ([]string, bool) {
	if !row.SupportsEffort {
		return []string{}, true
	}
	levels := []string{}
	for _, level := range row.SupportedEffortLevels {
		if level = strings.TrimSpace(level); level != "" {
			levels = append(levels, level)
		}
	}
	if len(levels) == 0 {
		return nil, false
	}
	return levels, true
}

// withCatalog puts the catalog in place of the choice it replaces, or adds it when `--help` gave
// nothing for that choice.
func withCatalog(choices []Choice, catalog Choice) []Choice {
	for i := range choices {
		if choices[i].Key == catalog.Key {
			choices[i] = catalog
			return choices
		}
	}
	return append(choices, catalog)
}
