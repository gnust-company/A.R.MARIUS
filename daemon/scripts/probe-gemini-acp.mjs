#!/usr/bin/env node
/**
 * probe-gemini-acp.mjs — find out what Gemini CLI actually does over ACP.
 *
 * Task T013 of specs/002-daemon-acp-runtime asks four questions, and forbids writing any Gemini
 * code before they are answered by running the thing rather than by reading about it. This script
 * is how they get answered on a machine that has `gemini` installed, by somebody who is not the
 * person who wrote the daemon.
 *
 *   1. Which context file does it read, and does what we put there reach the model?
 *   2. Which directory does it discover skills from, and does it see one we planted?
 *   3. Does it advertise session loading, and does loading one actually work?
 *   4. Does a tool call carry the parameters and the result over ACP, or only a title?
 *
 * A fifth question the daemon cannot avoid, added because a known issue says the answer may be
 * unpleasant: does it demand an interactive login when it is started by a program rather than
 * from a terminal? The daemon will always start it that way.
 *
 * Requirements: node 18 or newer, and `gemini` on PATH. Nothing to install.
 *
 *   node probe-gemini-acp.mjs
 *   node probe-gemini-acp.mjs --command /path/to/gemini --timeout 180
 *
 * It writes two files next to itself and prints a summary:
 *   gemini-acp-probe.log   every byte in both directions, which is the real evidence
 *   gemini-acp-probe.json  the answers, machine-readable
 *
 * Send both back. Nothing secret is written to them beyond what Gemini itself prints, but read
 * the log before sending if the machine has anything sensitive in the working directory.
 */

import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import process from 'node:process';

// ---------------------------------------------------------------------------- arguments

const args = process.argv.slice(2);
function flag(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
}

const COMMAND = flag('command', 'gemini');
const TIMEOUT_MS = Number(flag('timeout', '180')) * 1000;
const PROTOCOL_VERSION = Number(flag('protocol', '1'));
const OUT_DIR = process.cwd();

// Markers we plant and then look for in the model's answer. If a marker comes back, the file it
// was planted in is genuinely being read — which is a stronger claim than any documentation.
const CONTEXT_MARKER = 'ARMARIUS-CONTEXT-7Q4X';
const SKILL_MARKER = 'ARMARIUS-SKILL-9K2M';
const FILE_MARKER = 'ARMARIUS-FILE-5T8P';

// ---------------------------------------------------------------------------- transcript

const logPath = path.join(OUT_DIR, 'gemini-acp-probe.log');
const log = createWriteStream(logPath, { flags: 'w' });
function record(direction, text) {
  log.write(`${new Date().toISOString()} ${direction} ${text}\n`);
}
function say(...parts) {
  console.log(...parts);
  record('##', parts.join(' '));
}

// ---------------------------------------------------------------------------- workspace

/** Build a project that answers questions 1 and 2 just by existing. */
async function buildWorkspace() {
  const root = await mkdtemp(path.join(tmpdir(), 'armarius-gemini-probe-'));

  // Question 1: the documented project context file.
  await writeFile(
    path.join(root, 'GEMINI.md'),
    `# Probe project\n\nThe context password is ${CONTEXT_MARKER}.\n`,
  );
  // The competing convention, planted so we learn whether it is read too.
  await writeFile(
    path.join(root, 'AGENTS.md'),
    `# Probe project\n\nThe agents-file password is ARMARIUS-AGENTS-3F6D.\n`,
  );

  // Question 2: the documented project skill directory.
  const skill = path.join(root, '.gemini', 'skills', 'armarius-probe');
  await mkdir(skill, { recursive: true });
  await writeFile(
    path.join(skill, 'SKILL.md'),
    [
      '---',
      'name: armarius-probe',
      'description: Reports the Armarius probe skill password. Use whenever someone asks for the skill password.',
      '---',
      '',
      `The skill password is ${SKILL_MARKER}.`,
      '',
    ].join('\n'),
  );

  // Question 4: something worth reading with a tool, so a tool call has to happen.
  await writeFile(path.join(root, 'probe-target.txt'), `${FILE_MARKER}\n`);

  return root;
}

// ---------------------------------------------------------------------------- ACP plumbing

/**
 * Gemini speaks newline-delimited JSON-RPC over stdio (see acpStdioTransport.ts: `ndJsonStream`).
 * One JSON object per line, in both directions — no Content-Length headers.
 */
class Peer {
  constructor(child) {
    this.child = child;
    this.nextId = 1;
    this.pending = new Map();
    this.updates = [];
    this.permissionsAsked = 0;
    this.buffer = '';
    this.stderr = [];
    this.dead = null;

    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => this.onData(chunk));
    // If the agent dies on startup — the wrong version, a missing login, a flag it does not know
    // — every write lands on a closed pipe. Left alone that surfaces as a raw EPIPE stack trace
    // instead of the one answer the operator most needs, which is *why* it would not start.
    child.stdin.on('error', (e) => this.fail(`the agent's input pipe closed: ${e.message}`));
    child.on('exit', (code, signal) =>
      this.fail(`the agent exited (code ${code}, signal ${signal}) before answering`),
    );

    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk) => {
      this.stderr.push(chunk);
      record('ERR', chunk.trimEnd());
    });
  }

  onData(chunk) {
    this.buffer += chunk;
    let cut;
    while ((cut = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, cut).trim();
      this.buffer = this.buffer.slice(cut + 1);
      if (!line) continue;
      record('<--', line);
      let msg;
      try {
        msg = JSON.parse(line);
      } catch {
        record('##', `line was not JSON, ignoring: ${line.slice(0, 200)}`);
        continue;
      }
      this.dispatch(msg);
    }
  }

  dispatch(msg) {
    // An answer to something we asked.
    if (msg.id !== undefined && msg.method === undefined) {
      const waiter = this.pending.get(msg.id);
      if (waiter) {
        this.pending.delete(msg.id);
        msg.error ? waiter.reject(new Error(JSON.stringify(msg.error))) : waiter.resolve(msg.result);
      }
      return;
    }

    // Something the agent is telling or asking us.
    if (msg.method === 'session/update') {
      this.updates.push(msg.params?.update ?? msg.params);
      return;
    }
    if (msg.id === undefined) return; // any other notification

    if (msg.method === 'session/request_permission') {
      // Say yes to everything. We are here to see what a tool call looks like, and a probe that
      // stops to ask its operator is a probe that answers nothing.
      this.permissionsAsked += 1;
      const options = msg.params?.options ?? [];
      const chosen =
        options.find((o) => /always/i.test(o.optionId ?? '') || /always/i.test(o.name ?? '')) ??
        options[0];
      this.reply(msg.id, {
        outcome: { outcome: 'selected', optionId: chosen?.optionId ?? 'proceed_once' },
      });
      return;
    }

    // Anything else: answer honestly that we do not implement it, rather than hanging.
    this.replyError(msg.id, -32601, `probe does not implement ${msg.method}`);
  }

  /** Give up on everything still outstanding, with a reason worth reading. */
  fail(reason) {
    this.dead = reason;
    for (const [id, waiter] of this.pending) {
      this.pending.delete(id);
      waiter.reject(new Error(reason));
    }
  }

  send(obj) {
    const line = JSON.stringify(obj);
    record('-->', line);
    if (this.dead || this.child.stdin.destroyed || this.child.stdin.writableEnded) {
      record('##', `not sent — ${this.dead ?? 'the input pipe is already closed'}`);
      return;
    }
    try {
      this.child.stdin.write(line + '\n');
    } catch (e) {
      this.fail(`writing to the agent failed: ${e.message}`);
    }
  }

  reply(id, result) {
    this.send({ jsonrpc: '2.0', id, result });
  }

  replyError(id, code, message) {
    this.send({ jsonrpc: '2.0', id, error: { code, message } });
  }

  request(method, params) {
    if (this.dead) return Promise.reject(new Error(this.dead));
    const id = this.nextId++;
    const promise = new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
    this.send({ jsonrpc: '2.0', id, method, params });
    return promise;
  }
}

function withTimeout(promise, ms, what) {
  let timer;
  return Promise.race([
    promise.finally(() => clearTimeout(timer)),
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`timed out after ${ms / 1000}s waiting for ${what}`)), ms);
    }),
  ]);
}

function startGemini(cwd) {
  // stdio is a pipe, not a terminal — exactly how the daemon will start it, and exactly the
  // condition under which gemini-cli issue #12042 reports an unexpected login prompt.
  const child = spawn(COMMAND, ['--experimental-acp'], {
    cwd,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env },
  });
  return child;
}

// ---------------------------------------------------------------------------- the run

const findings = {
  probedAt: new Date().toISOString(),
  command: COMMAND,
  geminiVersion: null,
  initialize: null,
  newSession: null,
  loadSession: { advertised: null, attempted: false, worked: null, detail: null },
  toolCalls: [],
  answerText: '',
  sawContextMarker: false,
  sawSkillMarker: false,
  sawFileMarker: false,
  permissionsAsked: 0,
  askedToLogIn: null,
  stderrExcerpt: '',
  errors: [],
};

async function main() {
  const workspace = await buildWorkspace();
  say(`workspace: ${workspace}`);
  say(`command:   ${COMMAND} --experimental-acp`);
  say('');

  const child = startGemini(workspace);
  child.on('error', (e) => {
    console.error(`could not start ${COMMAND}: ${e.message}`);
    console.error('Pass the right path with --command /path/to/gemini');
    process.exit(2);
  });

  const peer = new Peer(child);
  const exited = new Promise((resolve) => child.on('exit', (code, signal) => resolve({ code, signal })));

  try {
    // --- 3a. what does it say it can do -------------------------------------------------
    findings.initialize = await withTimeout(
      peer.request('initialize', {
        protocolVersion: PROTOCOL_VERSION,
        clientCapabilities: {
          // Say we cannot serve files, so it uses its own tools — which is what we want to watch.
          fs: { readTextFile: false, writeTextFile: false },
        },
      }),
      30_000,
      'initialize',
    );
    findings.geminiVersion = findings.initialize?.agentInfo?.version ?? null;
    findings.loadSession.advertised = findings.initialize?.agentCapabilities?.loadSession ?? null;
    say(`initialize ok — agent ${JSON.stringify(findings.initialize?.agentInfo ?? {})}`);
    say(`agentCapabilities: ${JSON.stringify(findings.initialize?.agentCapabilities ?? {})}`);

    // --- open a session ------------------------------------------------------------------
    findings.newSession = await withTimeout(
      peer.request('session/new', { cwd: workspace, mcpServers: [] }),
      60_000,
      'session/new',
    );
    const sessionId = findings.newSession?.sessionId;
    say(`session/new ok — sessionId ${sessionId}`);

    // --- 1, 2, 4. make it prove what it can see -------------------------------------------
    const prompt = [
      'Answer with plain text. Do exactly these three things, in order:',
      '1. If your instructions contain a line with a context password, print it verbatim.',
      '2. If you have a skill about an Armarius probe, use it and print the skill password verbatim.',
      '3. Read the file probe-target.txt in the current directory with your file-reading tool and print its contents verbatim.',
      'Then stop. Do not modify any file.',
    ].join('\n');

    const promptResult = await withTimeout(
      peer.request('session/prompt', {
        sessionId,
        prompt: [{ type: 'text', text: prompt }],
      }),
      TIMEOUT_MS,
      'session/prompt',
    );
    say(`session/prompt finished — ${JSON.stringify(promptResult)}`);

    // --- read what came back --------------------------------------------------------------
    for (const u of peer.updates) {
      if (u?.sessionUpdate === 'agent_message_chunk') {
        findings.answerText += u.content?.text ?? '';
      }
      if (u?.sessionUpdate === 'tool_call' || u?.sessionUpdate === 'tool_call_update') {
        findings.toolCalls.push({
          sessionUpdate: u.sessionUpdate,
          fieldsPresent: Object.keys(u).sort(),
          title: u.title ?? null,
          kind: u.kind ?? null,
          status: u.status ?? null,
          // The two fields the whole of question 4 turns on.
          hasRawInput: Object.prototype.hasOwnProperty.call(u, 'rawInput'),
          hasRawOutput: Object.prototype.hasOwnProperty.call(u, 'rawOutput'),
          rawInput: u.rawInput ?? null,
          rawOutput: u.rawOutput ?? null,
          content: u.content ?? null,
          locations: u.locations ?? null,
        });
      }
    }
    findings.permissionsAsked = peer.permissionsAsked;
    findings.sawContextMarker = findings.answerText.includes(CONTEXT_MARKER);
    findings.sawSkillMarker = findings.answerText.includes(SKILL_MARKER);
    findings.sawFileMarker =
      findings.answerText.includes(FILE_MARKER) ||
      JSON.stringify(findings.toolCalls).includes(FILE_MARKER);

    // --- 3b. does loading a session actually work -------------------------------------------
    if (findings.loadSession.advertised) {
      findings.loadSession.attempted = true;
      try {
        const loaded = await withTimeout(
          peer.request('session/load', { sessionId, cwd: workspace, mcpServers: [] }),
          60_000,
          'session/load',
        );
        findings.loadSession.worked = true;
        findings.loadSession.detail =
          loaded && Object.keys(loaded).length ? JSON.stringify(loaded) : 'returned without error';
        say('session/load ok');
      } catch (e) {
        findings.loadSession.worked = false;
        findings.loadSession.detail = e.message;
        say(`session/load failed: ${e.message}`);
      }
    }
  } catch (e) {
    findings.errors.push(e.message);
    say(`FAILED: ${e.message}`);
  } finally {
    try {
      child.stdin.end();
    } catch {
      /* already gone */
    }
    const done = await Promise.race([
      exited,
      new Promise((r) => setTimeout(() => r({ code: null, signal: 'probe-gave-up' }), 10_000)),
    ]);
    if (done.signal === 'probe-gave-up') child.kill('SIGTERM');
    record('##', `child exited: ${JSON.stringify(done)}`);
  }

  // The login trap. Only what gemini itself said on stderr counts: the list of auth methods it
  // returns from initialize mentions logging in no matter what, and so do our own error strings,
  // so searching the whole transcript answers a different question than the one being asked.
  const complaints = peer.stderr.join('');
  findings.stderrExcerpt = complaints.slice(0, 4000);
  const soundsLikeLogin = /log ?in|sign ?in|authenticat|oauth|api[ _-]?key|credential|not logged/i;
  if (soundsLikeLogin.test(complaints)) {
    findings.askedToLogIn = 'YES — it complained on stderr; the excerpt is in the JSON file';
  } else if (findings.newSession?.sessionId) {
    findings.askedToLogIn = 'no — a session opened with no login step';
  } else {
    findings.askedToLogIn = 'unknown — no session opened, and nothing was said about login';
  }

  await writeFile(path.join(OUT_DIR, 'gemini-acp-probe.json'), JSON.stringify(findings, null, 2));
  report();
}

function yes(v) {
  return v === true ? 'YES' : v === false ? 'NO' : String(v);
}

function report() {
  const withRawInput = findings.toolCalls.filter((t) => t.hasRawInput).length;
  const withRawOutput = findings.toolCalls.filter((t) => t.hasRawOutput).length;
  const withContent = findings.toolCalls.filter((t) => (t.content ?? []).length > 0).length;

  const lines = [
    '',
    '=========================== ANSWERS ===========================',
    `gemini version                : ${findings.geminiVersion ?? 'unknown'}`,
    '',
    `1. GEMINI.md reached the model : ${yes(findings.sawContextMarker)}`,
    `2. .gemini/skills was found    : ${yes(findings.sawSkillMarker)}`,
    `3. loadSession advertised      : ${yes(findings.loadSession.advertised)}`,
    `   session/load actually works : ${yes(findings.loadSession.worked)}${
      findings.loadSession.detail ? ` (${String(findings.loadSession.detail).slice(0, 120)})` : ''
    }`,
    `4. tool calls seen             : ${findings.toolCalls.length}`,
    `   carrying rawInput (params)  : ${withRawInput}`,
    `   carrying rawOutput          : ${withRawOutput}`,
    `   carrying content            : ${withContent}`,
    `   tool read the file          : ${yes(findings.sawFileMarker)}`,
    '',
    `5. asked for an interactive login when started from a program: ${findings.askedToLogIn}`,
    `   permission requests received: ${findings.permissionsAsked}`,
    findings.errors.length ? `\nerrors: ${findings.errors.join(' | ')}` : '',
    '',
    'Written:',
    `  ${path.join(OUT_DIR, 'gemini-acp-probe.log')}`,
    `  ${path.join(OUT_DIR, 'gemini-acp-probe.json')}`,
    'Send both back — the log is the evidence, the summary above is only a reading of it.',
    '===============================================================',
  ];
  console.log(lines.join('\n'));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
