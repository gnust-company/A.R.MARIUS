package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

// maxAnswer is how much of a server answer is read before giving up on it. Every answer this
// program expects is a short JSON object; a body past this size means something other than
// the Armarius API is at the other end, and reading it all would be the only way this daemon
// could be made to exhaust its own machine's memory.
const maxAnswer = 1 << 20

// sendJSON makes one JSON request and decodes the JSON answer, returning the status alongside
// it so a caller can treat a particular status as a real answer rather than as a failure.
//
// `token` is the machine's own credential and is left empty by the two link routes, which are
// the only ones called before this machine has one.
func sendJSON(
	ctx context.Context,
	httpClient *http.Client,
	method, url, token string,
	body, into any,
) (int, error) {
	payload, err := json.Marshal(body)
	if err != nil {
		return 0, fmt.Errorf("encoding the request to %s: %w", url, err)
	}
	req, err := http.NewRequestWithContext(ctx, method, url, bytes.NewReader(payload))
	if err != nil {
		return 0, fmt.Errorf("building the request to %s: %w", url, err)
	}
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}

	resp, err := httpClient.Do(req)
	if err != nil {
		return 0, fmt.Errorf("calling %s: %w", url, err)
	}
	defer func() { _ = resp.Body.Close() }()

	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxAnswer))
	if err != nil {
		return resp.StatusCode, fmt.Errorf("reading the answer from %s: %w", url, err)
	}
	if len(raw) > 0 && into != nil {
		// A body that will not decode is worth reporting only when the status was otherwise
		// fine; on an error status the status itself is the news.
		if decodeErr := json.Unmarshal(raw, into); decodeErr != nil && resp.StatusCode < 400 {
			return resp.StatusCode, fmt.Errorf("the answer from %s was not JSON: %w", url, decodeErr)
		}
	}
	if resp.StatusCode >= 400 {
		return resp.StatusCode, fmt.Errorf("%s answered %s", url, resp.Status)
	}
	return resp.StatusCode, nil
}

// endpoint joins a server base URL, however the operator typed it, to one API path.
func endpoint(server, path string) string {
	return strings.TrimRight(server, "/") + path
}
