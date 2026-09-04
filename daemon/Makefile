# How this repository checks the daemon.
#
# There is no CI here yet — no .github/workflows, and no requirement in the spec that there be
# one (see specs/002-daemon-acp-runtime/plan.md). So `make check` IS the gate. Run it before
# every commit that touches daemon/.

GO             ?= go
GOBIN          := $(shell $(GO) env GOPATH)/bin
GOLANGCI_LINT  ?= $(shell command -v golangci-lint 2>/dev/null || printf '%s/golangci-lint' '$(GOBIN)')
BIN_DIR        := bin
BINARY         := $(BIN_DIR)/armarius-daemon
# The callback program, and it is not optional: the daemon refuses to start unless it is
# beside it, because an agent cannot call Armarius back without it. Measured while running
# the quickstart end to end (T129) — building only the daemon produced one that exited on
# the first `start` with "the armarius program is not installed beside this daemon".
CALLBACK       := $(BIN_DIR)/armarius

.DEFAULT_GOAL := check
.PHONY: check vet lint test build fmt tidy clean help

## check: vet, lint and test — the whole gate, in the order that fails cheapest first
check: vet lint test

## vet: the compiler's own suspicions
vet:
	$(GO) vet ./...

## lint: the rules in .golangci.yml
lint: | $(GOLANGCI_LINT)
	$(GOLANGCI_LINT) run ./...

## test: every test in the module
test:
	$(GO) test ./...

## build: both binaries for this machine, in ./bin — they ship together
build:
	$(GO) build -o $(BINARY) ./cmd/armarius-daemon
	$(GO) build -o $(CALLBACK) ./cmd/armarius

## fmt: rewrite the source into canonical form
fmt:
	$(GO) fmt ./...

## tidy: bring go.mod and go.sum back in line with the imports
tidy:
	$(GO) mod tidy

## clean: remove build output
clean:
	rm -rf $(BIN_DIR)

# Reached only when the binary is absent: `make` skips this rule once the file exists.
$(GOLANGCI_LINT):
	@echo 'golangci-lint not found at $@' >&2
	@echo 'install it with:' >&2
	@echo '  go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@latest' >&2
	@exit 1

## help: list what can be run here
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed -e 's/^## /  /'
