// Runs integrations/pi/agent-link.ts against a fake Pi extension API, driven by JSON lines on
// stdin; every command gets one JSON line on stdout. Used by tests/test_pi.py.
//
//   {"load": N}                          call the extension factory N times (a double load)
//   {"set": {"idle": false, "name": "x"}} change what the fake session reports
//   {"emit": "session_start", "event": {...}}   run every copy's handlers for an event
//   {"log": true}                        sendMessage and appendEntry calls since the last log

import { pathToFileURL } from "node:url";
import * as readline from "node:readline";

const ext = (await import(pathToFileURL(process.argv[2]).href)).default;
const state = { idle: true, name: undefined, mode: "tui", sessionId: "s-1", sessionFile: "/w/s-1.jsonl" };
const copies = [];
let log = [];

function fakePi(copy) {
	const handlers = {};
	copies.push(handlers);
	return {
		on: (name, h) => (handlers[name] ??= []).push(h),
		sendMessage: (message, options) => log.push({ copy, sent: message, options }),
		appendEntry: (customType, data) => log.push({ copy, entry: { customType, data } }),
		getSessionName: () => state.name,
	};
}

const ctx = {
	get mode() { return state.mode; },
	cwd: "/w",
	isIdle: () => state.idle,
	sessionManager: { getSessionId: () => state.sessionId, getSessionFile: () => state.sessionFile },
};

for await (const line of readline.createInterface({ input: process.stdin })) {
	const cmd = JSON.parse(line);
	let out = { ok: true };
	try {
		if (cmd.load) for (let i = 0; i < cmd.load; i++) ext(fakePi(copies.length));
		if (cmd.set) Object.assign(state, cmd.set);
		if (cmd.emit) for (const h of copies) for (const f of h[cmd.emit] ?? []) await f({ type: cmd.emit, ...cmd.event }, ctx);
		if (cmd.log) [out, log] = [{ ok: true, log }, []];
	} catch (e) {
		out = { ok: false, error: String(e && e.message) };
	}
	process.stdout.write(`${JSON.stringify(out)}\n`);
}
