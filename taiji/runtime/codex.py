"""Codex (GPT-5.4) backend for taiji agent turns via codex app-server JSON-RPC."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


CLIENT_INFO = {
    "title": "Taiji",
    "name": "taiji-runtime",
    "version": "0.1.0",
}

CAPABILITIES = {
    "experimentalApi": False,
    "optOutNotificationMethods": [
        "item/agentMessage/delta",
        "item/reasoning/summaryTextDelta",
        "item/reasoning/summaryPartAdded",
        "item/reasoning/textDelta",
    ],
}


class CodexAppServer:
    """Minimal JSON-RPC client for the codex app-server binary."""

    def __init__(self, proc: asyncio.subprocess.Process):
        self._proc = proc
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._notifications: list[dict] = []
        self._reader_task: asyncio.Task | None = None
        self._closed = False

    @classmethod
    async def connect(cls, cwd: str | Path) -> "CodexAppServer":
        codex_bin = shutil.which("codex")
        if codex_bin is None:
            raise RuntimeError(
                "codex CLI not found. Install with: npm install -g @openai/codex"
            )
        proc = await asyncio.create_subprocess_exec(
            codex_bin, "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
        )
        client = cls(proc)
        client._reader_task = asyncio.create_task(client._read_loop())
        # Handshake
        await client.request("initialize", {
            "clientInfo": CLIENT_INFO,
            "capabilities": CAPABILITIES,
        })
        client.notify("initialized", {})
        return client

    def notify(self, method: str, params: dict) -> None:
        self._send({"method": method, "params": params})

    async def request(self, method: str, params: dict) -> dict:
        msg_id = self._next_id
        self._next_id += 1
        fut: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        self._send({"id": msg_id, "method": method, "params": params})
        return await fut

    def _send(self, msg: dict) -> None:
        line = json.dumps(msg) + "\n"
        self._proc.stdin.write(line.encode())

    async def _read_loop(self) -> None:
        while True:
            raw = await self._proc.stdout.readline()
            if not raw:
                break
            line = raw.decode().strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Response to a request
            if "id" in msg and "method" not in msg:
                fut = self._pending.pop(msg["id"], None)
                if fut and not fut.done():
                    if "error" in msg:
                        fut.set_exception(RuntimeError(msg["error"].get("message", "codex error")))
                    else:
                        fut.set_result(msg.get("result", {}))
                continue

            # Notification from server
            if "method" in msg and "id" not in msg:
                self._notifications.append(msg)
                continue

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc.stdin:
            self._proc.stdin.close()
        try:
            self._proc.terminate()
        except ProcessLookupError:
            pass
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass

    def drain_notifications(self) -> list[dict]:
        out = list(self._notifications)
        self._notifications.clear()
        return out


async def run_codex_turn(
    *,
    cwd: Path,
    editable_paths: list[Path],
    prompt: str,
    system_prompt: str,
    model: str | None = None,
    effort: str | None = "xhigh",
    sandbox: str = "workspace-write",
) -> tuple[str | None, str]:
    """Run a single Codex turn. Returns (thread_id, response_text).

    The codex agent gets workspace-write access and can edit files directly.
    We prepend the system_prompt to the user prompt since codex app-server
    doesn't have a separate system_prompt field.
    """
    client = await CodexAppServer.connect(cwd)
    try:
        # Start thread
        thread_resp = await client.request("thread/start", {
            "cwd": str(cwd),
            "model": model,
            "approvalPolicy": "never",
            "sandbox": sandbox,
            "serviceName": "taiji_yin",
            "ephemeral": True,
        })
        thread_id = thread_resp["thread"]["id"]

        # System prompt + user prompt combined (codex has no separate system field)
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

        # Start turn and wait for completion
        turn_future = asyncio.ensure_future(
            client.request("turn/start", {
                "threadId": thread_id,
                "input": [{"type": "text", "text": full_prompt, "text_elements": []}],
                "model": model,
                "effort": effort,
                "outputSchema": None,
            })
        )

        # Poll notifications until turn/completed
        response_parts = []
        completed = False
        while not completed:
            await asyncio.sleep(0.5)
            for notif in client.drain_notifications():
                method = notif.get("method", "")
                params = notif.get("params", {})

                if method == "item/completed":
                    item = params.get("item", {})
                    # Agent text responses
                    if item.get("type") == "agentMessage":
                        text = item.get("text", "")
                        if text:
                            response_parts.append(text)

                if method == "turn/completed":
                    completed = True
                    break

            # Check if turn request errored
            if turn_future.done() and not completed:
                exc = turn_future.exception()
                if exc:
                    raise exc
                # Give a final drain chance
                await asyncio.sleep(2)
                for notif in client.drain_notifications():
                    if notif.get("method") == "item/completed":
                        item = notif.get("params", {}).get("item", {})
                        if item.get("type") == "agentMessage":
                            text = item.get("text", "")
                            if text:
                                response_parts.append(text)
                    if notif.get("method") == "turn/completed":
                        completed = True
                break

        return thread_id, "\n".join(response_parts).strip()
    finally:
        await client.close()


def codex_available() -> bool:
    """Check if the codex CLI is installed and authenticated."""
    codex_bin = shutil.which("codex")
    if codex_bin is None:
        return False
    try:
        result = subprocess.run(
            [codex_bin, "login", "status"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False
