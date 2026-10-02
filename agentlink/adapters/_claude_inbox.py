"""Deliver one message into a Claude Code session's inbox socket.

The receiving session starts a turn with the message (or reads it between tool calls when
busy). The inbox answers only on failure, and only to a reply socket named in the message:
a held message and a dropped one get a receipt, a delivered one gets nothing. So "delivered"
here means "no refusal arrived within the wait". A dropped message in a burst is reported
about 5 s late.

Measured on Claude Code 2.1.284-2.1.285; see docs/adapters/claude-code.md.
"""

import errno
import json
import os
import secrets
import select
import socket
import stat
import time
import uuid

# Measured on 2.1.284: a 1048486-byte line is held, a 1048586-byte one is
# silently discarded. Stay well below: a small overshoot still "sends" fine.
MAX_LINE_BYTES = 1_000_000

REFUSED = {"refused", "denied", "expired"}


def envelope(text, name, mode):
    if name is None and mode is None:
        return text
    attrs = ""
    # The receiver parses attributes in a fixed order: from-name before from-mode.
    if name is not None:
        attrs += f' from-name="{name}"'
    if mode is not None:
        attrs += f' from-mode="{mode}"'
    return f"<cross-session-message{attrs}>\n{text}\n</cross-session-message>"


def reply_socket():
    """Listening socket in the per-user directory the inbox accepts as a reply address."""
    d = f"/tmp/cc-socks-{os.getuid()}"
    try:
        os.mkdir(d, 0o700)
    except FileExistsError:
        pass
    st = os.lstat(d)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise OSError(f"{d} is not a private directory of this user")
    path = os.path.join(d, secrets.token_hex(8) + ".sock")
    s = socket.socket(socket.AF_UNIX)
    s.bind(path)
    os.chmod(path, 0o600)
    s.listen(4)
    return s, path


def await_receipt(listener, seconds):
    conns, bufs = [], {}
    deadline = time.monotonic() + seconds
    try:
        while (left := deadline - time.monotonic()) > 0:
            ready, _, _ = select.select([listener] + conns, [], [], left)
            for r in ready:
                if r is listener:
                    c, _ = listener.accept()
                    conns.append(c)
                    bufs[c] = b""
                    continue
                data = r.recv(65536)
                if not data:
                    conns.remove(r)
                    r.close()
                    continue
                bufs[r] += data
                while b"\n" in bufs[r]:
                    line, bufs[r] = bufs[r].split(b"\n", 1)
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("type") == "control" and msg.get("action") == "peer_message_status":
                        return msg
        return None
    finally:
        for c in conns:
            c.close()


def deliver(socket_path, text, name=None, wait=2.0):
    """Return (status, detail): delivered | no-inbox | too-large | dropped | held | refused | io-error."""
    for label, value in (("name", name),):
        if value is not None and any(ch in value for ch in '"<>\r\n'):
            return "io-error", f"{label} must not contain quotes, angle brackets or newlines"
    listener = path = None
    try:
        listener, path = reply_socket()
        msg = {"type": "user", "msg_id": str(uuid.uuid4()),
               "message": {"role": "user", "content": envelope(text, name, None)}}
        msg["from"] = "uds:" + path
        wire = json.dumps(msg).encode() + b"\n"
        if len(wire) > MAX_LINE_BYTES:
            return "too-large", f"message is {len(wire)} bytes on the wire, cap is {MAX_LINE_BYTES}"
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(10)
        try:
            s.connect(socket_path)
        except (FileNotFoundError, ConnectionRefusedError, socket.timeout) as e:
            return "no-inbox", f"no live inbox at {socket_path}: {e}"
        try:
            s.sendall(wire)
            s.shutdown(socket.SHUT_WR)
        except OSError as e:
            if e.errno == errno.EPIPE:
                return "too-large", "inbox closed the connection mid-send (message too large?)"
            return "io-error", f"send failed: {e}"
        finally:
            s.close()
        receipt = await_receipt(listener, wait)
        if receipt is None:
            return "delivered", ""
        status = receipt.get("status")
        if status == "delivered":
            return "delivered", ""
        if status == "held":
            return "held", "held for approval at the receiver"
        if status == "dropped":
            return "dropped", f"dropped: {receipt.get('drop_reason')}"
        if status in REFUSED:
            return "refused", f"{status}: {receipt.get('reason', '')}"
        return "io-error", f"unexpected receipt status {status!r}"
    except OSError as e:
        return "io-error", str(e)
    finally:
        if listener is not None:
            listener.close()
        if path:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
