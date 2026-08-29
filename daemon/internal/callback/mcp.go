package callback

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
)

// protocolVersion is the MCP revision this server speaks.
//
// A client asking for a revision we know is answered in its own revision; anything else is
// answered in ours and left to decide. Declaring whatever the client asked for would be the
// worse failure of the two — the client would go on to use a feature we do not have, and find
// out one call later.
const protocolVersion = "2024-11-05"

var understoodVersions = map[string]bool{
	"2024-11-05": true,
	"2025-03-26": true,
	"2025-06-18": true,
}

// ServeMCP is the native-tool face: the same commands, spoken as MCP over stdio (FR-013a).
//
// This is the face a CLI with a tool loader is given, and it is deliberately the *same program*
// as the command face rather than a second installation. Both enumerate `Commands(env)` and
// nothing else, so a command added to the registry appears on both faces at once and cannot be
// added to one and forgotten on the other — which is the failure two installations make
// inevitable rather than merely possible.
//
// Over stdio, and never over a port: the run's credential is in this process's environment, and
// a port is something anything else on the machine can also reach.
func ServeMCP(ctx context.Context, env Environment, stdin io.Reader, stdout, stderr io.Writer) int {
	available := Commands(env)
	reader := bufio.NewScanner(stdin)
	// One JSON-RPC message per line, and a tool result can carry a whole task thread. The
	// default scanner buffer is 64 KiB, which is smaller than a message this server will
	// legitimately need to read back.
	reader.Buffer(make([]byte, 0, 64*1024), maxAnswer)

	encoder := json.NewEncoder(stdout)
	for reader.Scan() {
		line := strings.TrimSpace(reader.Text())
		if line == "" {
			continue
		}
		var request rpcRequest
		if err := json.Unmarshal([]byte(line), &request); err != nil {
			fmt.Fprintf(stderr, "armarius mcp: could not read a message: %v\n", err)
			continue
		}
		response, answer := dispatchMCP(ctx, env, available, request)
		if !answer {
			// A notification. JSON-RPC forbids answering one, and a client that gets an answer
			// it did not ask for is a client that stops trusting the stream.
			continue
		}
		if err := encoder.Encode(response); err != nil {
			fmt.Fprintf(stderr, "armarius mcp: could not answer: %v\n", err)
			return ExitUnreached
		}
	}
	if err := reader.Err(); err != nil {
		fmt.Fprintf(stderr, "armarius mcp: the connection ended badly: %v\n", err)
		return ExitUnreached
	}
	return ExitOK
}

type rpcRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type rpcResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Result  any             `json:"result,omitempty"`
	Error   *rpcError       `json:"error,omitempty"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

func dispatchMCP(
	ctx context.Context, env Environment, available []Command, request rpcRequest,
) (rpcResponse, bool) {
	answer := rpcResponse{JSONRPC: "2.0", ID: request.ID}
	// No id means a notification: acted on, never answered.
	wants := len(request.ID) > 0

	switch request.Method {
	case "initialize":
		answer.Result = initializeResult(request.Params)
	case "tools/list":
		answer.Result = map[string]any{"tools": toolsOf(available)}
	case "tools/call":
		answer.Result = callTool(ctx, env, available, request.Params)
	case "ping":
		answer.Result = map[string]any{}
	case "notifications/initialized", "notifications/cancelled":
		return answer, false
	default:
		answer.Error = &rpcError{Code: -32601, Message: "no such method: " + request.Method}
	}
	return answer, wants
}

func initializeResult(params json.RawMessage) map[string]any {
	asked := struct {
		ProtocolVersion string `json:"protocolVersion"`
	}{}
	_ = json.Unmarshal(params, &asked)
	speaking := protocolVersion
	if understoodVersions[asked.ProtocolVersion] {
		speaking = asked.ProtocolVersion
	}
	return map[string]any{
		"protocolVersion": speaking,
		"capabilities":    map[string]any{"tools": map[string]any{}},
		"serverInfo":      map[string]any{"name": "armarius", "version": "1"},
	}
}

// toolsOf renders the run's commands as MCP tools.
//
// Rendered from `Commands(env)` and from nothing else. There is no second list here to keep in
// step with the first, which is the whole of what "one thing, two faces" buys.
func toolsOf(available []Command) []map[string]any {
	tools := make([]map[string]any, 0, len(available))
	for _, cmd := range available {
		properties := map[string]any{}
		required := []string{}
		for _, p := range cmd.Params {
			properties[p.Name] = map[string]any{
				"type":        string(p.Type),
				"description": p.Description,
			}
			if p.Required {
				required = append(required, p.Name)
			}
		}
		schema := map[string]any{"type": "object", "properties": properties}
		if len(required) > 0 {
			schema["required"] = required
		}
		tools = append(tools, map[string]any{
			"name":        cmd.ToolName(),
			"description": cmd.Summary,
			"inputSchema": schema,
		})
	}
	return tools
}

// callTool runs one command and answers in MCP's shape.
//
// A refusal comes back as a **result with `isError` set**, not as a JSON-RPC error. The
// distinction is the protocol's and it matters: a JSON-RPC error says the call could not be
// made, while this says the call was made and Armarius said no — and only the second is
// something the agent can read and act on.
func callTool(
	ctx context.Context, env Environment, available []Command, params json.RawMessage,
) map[string]any {
	asked := struct {
		Name      string         `json:"name"`
		Arguments map[string]any `json:"arguments"`
	}{}
	if err := json.Unmarshal(params, &asked); err != nil {
		return toolError("could not read the arguments: " + err.Error())
	}
	cmd, found := Find(available, asked.Name)
	if !found {
		// Named rather than merely refused: an agent whose tool list has gone stale should be
		// told *this run does not have that*, which is a different thing from a typo.
		return toolError("this run has no tool called " + asked.Name)
	}
	args := Args(asked.Arguments)
	if args == nil {
		args = Args{}
	}
	if missing := cmd.Missing(args); len(missing) > 0 {
		return toolError(cmd.Name + " needs " + strings.Join(missing, " and "))
	}

	answer, err := cmd.Call(ctx, NewClient(env), args)
	if err != nil {
		var failure *Failure
		if errors.As(err, &failure) && len(failure.Body) > 0 {
			// The refusal itself, with its code and parameters — the same thing the command
			// face puts on stdout, for the same reason.
			return toolError(string(failure.Body))
		}
		return toolError(err.Error())
	}
	return toolResult(string(answer), false)
}

func toolError(text string) map[string]any { return toolResult(text, true) }

func toolResult(text string, isError bool) map[string]any {
	if text == "" {
		text = "{}"
	}
	return map[string]any{
		"content": []map[string]any{{"type": "text", "text": text}},
		"isError": isError,
	}
}
