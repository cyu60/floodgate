"""Synchronous, persistent GBrain MCP stdio client (no Python dependencies).

Implements the MCP 2025-03-26 stdio framing, initialization and tools/call
contracts: https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
and /basic/lifecycle. This deliberately supports only local tool calls, not
HTTP, sampling, or filesystem access. Initialize the brain separately with
``GBRAIN_HOME=<root> gbrain init --pglite --no-embedding`` before use.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import select
import shutil
import subprocess
import threading
import time
from typing import Any


class GBrainError(RuntimeError):
    """Transport or tool failure; payload retains a structured server error."""

    def __init__(self, message: str, *, payload: Any = None):
        super().__init__(message)
        self.payload = payload
        error = payload.get("error", payload) if isinstance(payload, dict) else None
        self.code = error.get("code") if isinstance(error, dict) else error


class _TransportError(GBrainError):
    pass


class GBrainClient:
    """Own one stdio process for one pre-initialized brain.

    Calls are serialized, including startup and shutdown. A failed transport is
    closed and may be started again by a later call; mutations are never retried
    automatically because a timeout does not establish whether they committed.
    Use the same request_id to reconcile/replay a timed-out GBrain page write.
    """

    _PROTOCOL = "2025-03-26"
    _MAX_MESSAGE = 8 * 1024 * 1024
    _OS_ENV = {
        "PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "TMP", "TEMP",
        "LANG", "LANGUAGE", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
    }

    def __init__(self, home: Path | str, command: str = "gbrain", timeout: float = 8.0):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        self.home = Path(home).expanduser().resolve()
        self.command = command
        self.timeout = timeout
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._inbox: queue.Queue = queue.Queue()
        self._next_id = 0
        self.last_notices: tuple[str, ...] = ()

    def _acquire(self):
        if not self._lock.acquire(timeout=self.timeout):
            raise GBrainError("Timed out waiting for another GBrain call")

    def start(self) -> GBrainClient:
        """Start and initialize MCP; does not create or initialize a database."""
        self._acquire()
        try:
            if self._process is not None:
                if self._process.poll() is None:
                    return self
                self._close_locked()
            if not self.home.is_dir():
                raise GBrainError(f"GBrain home does not exist: {self.home}")
            executable = shutil.which(self.command)
            if executable is None:
                raise GBrainError(f"GBrain executable not found: {self.command}")
            executable = str(Path(executable).resolve())
            # An allowlist also removes future provider/DB override variables.
            # Keep provider configuration in this brain's private config/.env.
            env = {key: value for key, value in os.environ.items()
                   if key in self._OS_ENV or key.startswith("LC_")}
            env["GBRAIN_HOME"] = str(self.home)
            self._inbox = queue.Queue()
            try:
                self._process = subprocess.Popen(
                    [executable, "serve", "--surface", "full"],
                    cwd=self.home, env=env, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                )
                os.set_blocking(self._process.stdin.fileno(), False)
                self._reader = threading.Thread(
                    target=self._read_messages,
                    args=(self._process.stdout, self._inbox), daemon=True,
                    name="floodgate-gbrain-stdio",
                )
                self._reader.start()
                result = self._request("initialize", {
                    "protocolVersion": self._PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "floodgate", "version": "0.1.0"},
                })
                if (not isinstance(result, dict)
                        or result.get("protocolVersion") != self._PROTOCOL
                        or not isinstance(result.get("capabilities"), dict)
                        or "tools" not in result["capabilities"]):
                    raise _TransportError("GBrain did not negotiate the supported MCP tools protocol")
                self._send({"jsonrpc": "2.0", "method": "notifications/initialized"},
                           time.monotonic() + self.timeout)
            except (OSError, GBrainError) as exc:
                self._close_locked()
                if isinstance(exc, GBrainError):
                    raise
                raise GBrainError(f"Could not start GBrain: {exc}") from exc
            return self
        finally:
            self._lock.release()

    @classmethod
    def _read_messages(cls, stream, inbox):
        try:
            while line := stream.readline(cls._MAX_MESSAGE + 1):
                if len(line) > cls._MAX_MESSAGE or not line.endswith(b"\n"):
                    raise _TransportError("Invalid or oversized GBrain MCP message")
                try:
                    value = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    raise _TransportError("GBrain emitted invalid MCP JSON") from exc
                for message in value if isinstance(value, list) else [value]:
                    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                        raise _TransportError("GBrain emitted an invalid MCP envelope")
                    inbox.put(message)
        except (OSError, ValueError, GBrainError) as exc:
            inbox.put(exc if isinstance(exc, GBrainError)
                      else _TransportError("GBrain output stream failed"))
        finally:
            inbox.put(_TransportError("GBrain closed its MCP connection"))

    def _send(self, message: dict, deadline: float):
        data = (json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        if len(data) > self._MAX_MESSAGE:
            raise GBrainError("GBrain MCP request exceeds 8 MiB")
        fd = self._process.stdin.fileno()
        offset = 0
        try:
            while offset < len(data):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
                    raise _TransportError("GBrain request timed out; mutation outcome may be unknown")
                try:
                    written = os.write(fd, data[offset:])
                except BlockingIOError:
                    continue
                if written == 0:
                    raise _TransportError("GBrain input stream closed")
                offset += written
        except OSError as exc:
            raise _TransportError("Could not write to GBrain MCP connection") from exc

    def _request(self, method: str, params: dict) -> Any:
        self._next_id += 1
        request_id = self._next_id
        deadline = time.monotonic() + self.timeout
        self._send({"jsonrpc": "2.0", "id": request_id,
                    "method": method, "params": params}, deadline)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _TransportError("GBrain request timed out; mutation outcome may be unknown")
            try:
                message = self._inbox.get(timeout=remaining)
            except queue.Empty as exc:
                raise _TransportError("GBrain request timed out; mutation outcome may be unknown") from exc
            if isinstance(message, Exception):
                raise message
            if "method" in message:
                if "id" in message:
                    # No optional client capabilities were advertised. Ping is
                    # the only server request this client can fulfill.
                    response = {"jsonrpc": "2.0", "id": message["id"]}
                    if message["method"] == "ping":
                        response["result"] = {}
                    else:
                        response["error"] = {"code": -32601, "message": "Method not supported"}
                    self._send(response, deadline)
                continue  # Notifications are independent of our response.
            if message.get("id") != request_id:
                raise _TransportError("GBrain replied with an unexpected request ID")
            if "error" in message:
                error = message["error"]
                detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                raise GBrainError(f"GBrain protocol error: {detail}", payload=error)
            if "result" not in message:
                raise _TransportError("GBrain response has no result")
            return message["result"]

    def call(self, name: str, arguments: dict) -> Any:
        """Return the JSON payload; ancillary text is retained in last_notices.

        GBrain dispatch emits one JSON content block and may append plain-text
        backup/retrieval notices. Those notices must not change a page into a
        list. Multiple JSON blocks are ambiguous and are rejected.
        """
        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
            raise ValueError("A tool name and argument dictionary are required")
        # Reject unserializable inputs before touching the child process.
        json.dumps(arguments, allow_nan=False)
        self._acquire()
        try:
            self.last_notices = ()
            self.start()
            try:
                result = self._request("tools/call", {"name": name, "arguments": arguments})
            except _TransportError:
                self._close_locked()
                raise
            if not isinstance(result, dict):
                raise GBrainError("GBrain returned an invalid tool result", payload=result)
            payload = result.get("structuredContent")
            if payload is None:
                values = []
                json_values, notices, other_content = [], [], False
                content = result.get("content", [])
                if not isinstance(content, list) or any(not isinstance(item, dict) for item in content):
                    raise GBrainError("GBrain returned invalid tool content", payload=result)
                for item in content:
                    if item.get("type") == "text":
                        value = item.get("text", "")
                        try:
                            value = json.loads(value)
                            json_values.append(value)
                        except (TypeError, ValueError):
                            notices.append(value)
                        values.append(value)
                    else:
                        other_content = True
                        values.append(item)
                if len(json_values) > 1 or (json_values and other_content):
                    raise GBrainError("GBrain returned ambiguous tool data blocks", payload=result)
                if json_values:
                    payload = json_values[0]
                    self.last_notices = tuple(notices)
                else:
                    payload = values[0] if len(values) == 1 else values
            if result.get("isError"):
                raise GBrainError(f"GBrain tool {name} failed: {payload}", payload=payload)
            return payload
        finally:
            self._lock.release()

    def _close_locked(self):
        process, self._process = self._process, None
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        grace = min(self.timeout, 1.0)
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=grace)
        if self._reader:
            self._reader.join(timeout=grace)
            self._reader = None
        if process.stdout:
            process.stdout.close()

    def close(self):
        """Close stdin, then terminate/kill only if the server fails to exit."""
        self._acquire()
        try:
            self._close_locked()
        finally:
            self._lock.release()

    def __enter__(self) -> GBrainClient:
        return self.start()

    def __exit__(self, *exc):
        self.close()
