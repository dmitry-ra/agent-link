// agent-link extension for Pi: makes this Pi session visible to agent-link and lets it take
// messages. Load it with `pi -e <this file>` or link it into ~/.pi/agent/extensions/
// (install.sh does). Design and formats: docs/adapters/pi.md in the agent-link repository.
//
// - Registry entry <dir>/<pid>.json: who this Pi is, where its session file is, its state.
// - Inbox <dir>/<pid>.sock (unix socket, 0600): one JSON line in, one JSON line back.
// - On every agent_settled a {"event": "settled"} custom entry in the session file, so
//   `agent-link ask` can tell a finished turn from one Pi is about to retry or continue.
// <dir> is $XDG_RUNTIME_DIR/agent-link/pi, else ${XDG_STATE_HOME:-~/.local/state}/agent-link/pi.

import * as fs from "node:fs";
import * as net from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import { VERSION, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";

const PROTOCOL = 1;
const CUSTOM_TYPE = "agent-link";
const MAX_LINE_BYTES = 1024 * 1024;
const CONNECTION_MS = 10_000;
// Shared by every copy of this file in the process: loaded twice (extensions directory and
// -e), only the first copy serves, or both would bind the same socket path.
const OWNER = Symbol.for("agent-link.pi.owner");

type Reply = { ok: true } | { ok: false; reason: string; error: string };

export function registryDir(env: NodeJS.ProcessEnv = process.env): string {
	if (env.XDG_RUNTIME_DIR) return path.join(env.XDG_RUNTIME_DIR, "agent-link", "pi");
	const state = env.XDG_STATE_HOME || path.join(os.homedir(), ".local", "state");
	return path.join(state, "agent-link", "pi");
}

export default function (pi: ExtensionAPI) {
	const me = {};
	const shared = globalThis as unknown as Record<symbol, unknown>;
	let ctx: ExtensionContext | undefined;
	let server: net.Server | undefined;
	let base = "";
	let entry: Record<string, unknown> | undefined;
	let running = false;
	let prompt: string | undefined;

	const mine = () => shared[OWNER] === me;

	function publish(): void {
		if (!entry) return;
		entry.state = prompt !== undefined ? "awaiting-approval" : running ? "busy" : "idle";
		entry.prompt = prompt ?? "";
		entry.name = pi.getSessionName() ?? "";
		// wx after rm: never write through whatever else sits at the temporary name.
		fs.rmSync(`${base}.json.tmp`, { force: true });
		fs.writeFileSync(`${base}.json.tmp`, `${JSON.stringify(entry)}\n`, { mode: 0o600, flag: "wx" });
		fs.renameSync(`${base}.json.tmp`, `${base}.json`);
	}

	function accept(line: string): Reply {
		let msg: { v?: unknown; type?: unknown; text?: unknown } | null;
		try {
			msg = JSON.parse(line);
		} catch {
			return { ok: false, reason: "bad-request", error: "the line is not JSON" };
		}
		if (!msg || msg.v !== PROTOCOL || msg.type !== "message" || typeof msg.text !== "string" || !msg.text.trim()) {
			return { ok: false, reason: "bad-request", error: `expected {"v": ${PROTOCOL}, "type": "message", "text": "..."}` };
		}
		if (!ctx) return { ok: false, reason: "no-session", error: "no Pi session is active" };
		// No run, yet not idle: a manual /compact or a branch summary. Pi refuses typed prompts
		// then, and sendMessage would bypass that check.
		if (!running && !ctx.isIdle()) {
			return { ok: false, reason: "compacting", error: "Pi is compacting its context; try again when it is idle" };
		}
		pi.sendMessage(
			{ customType: CUSTOM_TYPE, content: msg.text, display: true },
			{ triggerTurn: true, deliverAs: "followUp" },
		);
		return { ok: true };
	}

	function serve(conn: net.Socket): void {
		let buf = Buffer.alloc(0);
		let answered = false;
		const reply = (r: Reply) => {
			answered = true;
			conn.end(`${JSON.stringify(r)}\n`);
		};
		conn.setTimeout(CONNECTION_MS, () => conn.destroy());
		conn.on("error", () => {});
		conn.on("data", (chunk: Buffer) => {
			if (answered) return;
			buf = Buffer.concat([buf, chunk]);
			const nl = buf.indexOf(10);
			if (nl > MAX_LINE_BYTES || (nl < 0 && buf.length > MAX_LINE_BYTES)) {
				reply({ ok: false, reason: "too-large", error: `a message line is limited to ${MAX_LINE_BYTES} bytes` });
			} else if (nl >= 0) {
				reply(accept(buf.subarray(0, nl).toString("utf8")));
			}
		});
	}

	function cleanup(): void {
		if (!mine()) return;
		delete shared[OWNER];
		server?.close();
		server = undefined;
		if (base) {
			fs.rmSync(`${base}.json`, { force: true });
			fs.rmSync(`${base}.sock`, { force: true });
		}
		entry = undefined;
		ctx = undefined;
	}

	pi.on("session_start", async (_event, c) => {
		if (shared[OWNER] !== undefined && !mine()) return;
		shared[OWNER] = me;
		ctx = c;
		running = false;
		prompt = undefined;
		const dir = registryDir();
		fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
		const st = fs.lstatSync(dir);
		if (!st.isDirectory() || st.uid !== process.getuid?.() || (st.mode & 0o077) !== 0) {
			delete shared[OWNER];
			throw new Error(`agent-link: ${dir} is not a private directory of this user; this Pi is not registered`);
		}
		base = path.join(dir, String(process.pid));
		let socket = "";
		// A one-shot run (print, json) ends before anyone could answer it: no inbox.
		if (c.mode === "tui" || c.mode === "rpc") {
			socket = `${base}.sock`;
			fs.rmSync(socket, { force: true });
			const s = net.createServer(serve);
			server = s;
			await new Promise<void>((resolve, reject) => {
				s.once("error", reject);
				s.listen(socket, () => resolve());
			});
			s.unref();
			fs.chmodSync(socket, 0o600);
		}
		entry = {
			protocol: PROTOCOL,
			pid: process.pid,
			session_id: c.sessionManager.getSessionId(),
			session_file: c.sessionManager.getSessionFile() ?? "",
			cwd: c.cwd,
			name: "",
			socket,
			state: "idle",
			prompt: "",
			mode: c.mode,
			pi_version: VERSION,
		};
		publish();
	});

	pi.on("session_shutdown", async () => cleanup());

	pi.on("session_info_changed", async () => {
		if (mine()) publish();
	});

	pi.on("agent_start", async () => {
		if (!mine()) return;
		running = true;
		publish();
	});

	pi.on("agent_settled", async () => {
		if (!mine()) return;
		running = false;
		pi.appendEntry(CUSTOM_TYPE, { event: "settled" });
		publish();
	});

	pi.on("ui_prompt_start", async (event) => {
		if (!mine()) return;
		prompt = event.title ?? "";
		publish();
	});

	pi.on("ui_prompt_end", async () => {
		if (!mine()) return;
		prompt = undefined;
		publish();
	});
}
