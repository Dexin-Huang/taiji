"""Codex (GPT-5.4) backend for taiji agent turns via codex app-server JSON-RPC."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import re
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

TURN_COMPLETION_TIMEOUT_SEC = 300.0


class CodexAppServer:
    """Minimal JSON-RPC client for the codex app-server binary."""

    def __init__(self, proc: subprocess.Popen[bytes]):
        self._proc = proc
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._notifications: list[dict] = []
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._closed = False
        self._stderr_chunks: list[str] = []

    @classmethod
    async def connect(cls, cwd: str | Path, *, service_name: str = "taiji") -> "CodexAppServer":
        codex_bin = shutil.which("codex")
        if codex_bin is None:
            raise RuntimeError(
                "codex CLI not found. Install with: npm install -g @openai/codex"
            )
        proc = subprocess.Popen(
            [codex_bin, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            env=_codex_process_env(Path(cwd), service_name=service_name),
        )
        client = cls(proc)
        client._reader_task = asyncio.create_task(client._read_loop())
        client._stderr_task = asyncio.create_task(client._stderr_loop())
        try:
            # Handshake
            await client.request("initialize", {
                "clientInfo": CLIENT_INFO,
                "capabilities": CAPABILITIES,
            })
            client.notify("initialized", {})
        except Exception:
            await client.close()
            raise
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
        if self._proc.stdin is None:
            raise RuntimeError("Codex app-server stdin is unavailable")
        self._proc.stdin.write(line.encode())
        self._proc.stdin.flush()

    def _fail_pending(self, message: str) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError(message))
        self._pending.clear()

    async def _read_loop(self) -> None:
        if self._proc.stdout is None:
            self._fail_pending("Codex app-server stdout is unavailable")
            return
        while True:
            raw = await asyncio.to_thread(self._proc.stdout.readline)
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

        if not self._closed:
            self._fail_pending(self._exit_message())

    async def _stderr_loop(self) -> None:
        if self._proc.stderr is None:
            return
        while True:
            raw = await asyncio.to_thread(self._proc.stderr.readline)
            if not raw:
                break
            text = raw.decode(errors="replace")
            if text:
                self._stderr_chunks.append(text)

    def _exit_message(self) -> str:
        returncode = self._proc.poll()
        stderr_text = "".join(self._stderr_chunks).strip()
        if stderr_text:
            return f"Codex app-server exited with code {returncode}: {stderr_text}"
        return f"Codex app-server exited with code {returncode}"

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc.stdin is not None:
            self._proc.stdin.close()
        try:
            self._proc.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.to_thread(self._proc.wait, 5)
        except Exception:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass

    def drain_notifications(self) -> list[dict]:
        out = list(self._notifications)
        self._notifications.clear()
        return out


def _codex_source_home() -> Path:
    raw = os.environ.get("CODEX_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".codex"


def _safe_service_name(service_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(service_name).strip())
    return cleaned or "taiji"


def _prepare_codex_home(cwd: Path, *, service_name: str) -> Path:
    source_home = _codex_source_home()
    cwd_scope = hashlib.sha256(str(cwd.resolve()).encode("utf-8")).hexdigest()[:10]
    target_home = Path(tempfile.gettempdir()) / "taiji-codex-home" / cwd_scope / _safe_service_name(service_name)
    target_home.mkdir(parents=True, exist_ok=True)
    for name in ("auth.json", "config.toml", "version.json"):
        source_path = source_home / name
        target_path = target_home / name
        if source_path.exists():
            target_path.write_bytes(source_path.read_bytes())
    return target_home


def _codex_process_env(cwd: Path, *, service_name: str) -> dict[str, str]:
    env = dict(os.environ)
    env["CODEX_HOME"] = str(_prepare_codex_home(cwd, service_name=service_name))
    return env


def _normalize_path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _resolve_edit_path(raw_path: str, cwd: Path) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.resolve()


def _extract_fenced_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    pattern = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(text):
        lang = match.group(1).strip().lower()
        body = match.group(2).strip()
        blocks.append((lang, body))
    return blocks


def _extract_json_substring(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _load_json_payload(text: str) -> Any | None:
    candidates: list[str] = []
    for lang, body in _extract_fenced_blocks(text):
        if lang in {"json", "application/json", "taiji-json", ""}:
            candidates.append(body)
    candidates.append(text.strip())
    if json_substring := _extract_json_substring(text):
        candidates.append(json_substring)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _coerce_file_edits(raw: Any) -> list[tuple[str, str]]:
    if raw is None:
        return []

    payload: dict[str, Any]
    if isinstance(raw, dict):
        payload = raw
    elif isinstance(raw, list):
        payload = {"files": raw}
    else:
        raise RuntimeError(f"Codex response manifest must be a dict or list, got {type(raw).__name__}")

    entries: list[Any]
    if "files" in payload:
        files_raw = payload["files"]
        if isinstance(files_raw, dict):
            entries = [{"path": key, "content": value} for key, value in files_raw.items()]
        elif isinstance(files_raw, list):
            entries = list(files_raw)
        else:
            raise RuntimeError("Codex response manifest files must be a list or mapping")
    elif "edits" in payload and isinstance(payload["edits"], list):
        entries = list(payload["edits"])
    elif "path" in payload or "content" in payload:
        entries = [payload]
    else:
        raise RuntimeError("Codex response manifest must contain files, edits, or a single path/content pair")

    edits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RuntimeError(f"Codex response manifest entry {index} must be a dict")

        path = entry.get("path") or entry.get("file") or entry.get("name")
        content = entry.get("content")
        if content is None:
            content = entry.get("text") or entry.get("body")
        if not isinstance(path, str) or not path.strip():
            raise RuntimeError(f"Codex response manifest entry {index} must include a non-empty path")
        if not isinstance(content, str):
            raise RuntimeError(f"Codex response manifest entry {index} must include string content")

        normalized = os.path.normcase(path.strip())
        if normalized in seen:
            raise RuntimeError(f"Codex response manifest repeated path {path!r}")
        seen.add(normalized)
        edits.append((path.strip(), content))

    return edits


def _extract_legacy_code_block(text: str) -> str | None:
    pattern = r"```python\s*\n(.*?)```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip() + "\n"
    pattern = r"```\s*\n(.*?)```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        code = match.group(1).strip()
        if "def " in code:
            return code + "\n"
    return None


def _item_text(item: dict[str, Any]) -> str:
    text = item.get("text")
    if isinstance(text, str) and text.strip():
        return text
    content = item.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for entry in content:
            if isinstance(entry, dict) and entry.get("type") == "text":
                value = entry.get("text")
                if isinstance(value, str) and value:
                    parts.append(value)
        return "\n".join(parts).strip()
    return ""


def _apply_codex_file_edits(
    *,
    response_text: str,
    editable_paths: list[Path],
    cwd: Path,
) -> list[Path]:
    allowed = {_normalize_path_key(path) for path in editable_paths}
    if not allowed:
        return []

    payload = _load_json_payload(response_text)
    if payload is not None:
        edits = _coerce_file_edits(payload)
        if not edits:
            return []

        written: list[Path] = []
        for raw_path, content in edits:
            target = _resolve_edit_path(raw_path, cwd)
            if _normalize_path_key(target) not in allowed:
                allowed_list = ", ".join(sorted(str(path) for path in editable_paths))
                raise RuntimeError(
                    f"Codex response attempted to write disallowed file {raw_path!r}; "
                    f"allowed files are: {allowed_list}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append(target)
        return written

    # Backward-compatible fallback: preserve the old single-file behavior when
    # Codex returns a plain python block instead of a structured manifest.
    if len(editable_paths) == 1:
        code = _extract_legacy_code_block(response_text)
        if code is not None:
            editable_paths[0].parent.mkdir(parents=True, exist_ok=True)
            editable_paths[0].write_text(code, encoding="utf-8")
            return [editable_paths[0]]

    return []


def _codex_write_instruction(editable_paths: list[Path], cwd: Path) -> str:
    if not editable_paths:
        return ""

    allowed = []
    for path in editable_paths:
        try:
            allowed.append(path.resolve().relative_to(cwd.resolve()).as_posix())
        except ValueError:
            allowed.append(str(path.resolve()))
    allowed_list = "\n".join(f"- {item}" for item in allowed)
    return (
        "\nIMPORTANT: Return a single JSON object inside one fenced ```json block.\n"
        "Use this exact schema:\n"
        "{\n"
        '  "files": [\n'
        '    {"path": "relative/or/absolute/path", "content": "full file text"},\n'
        "    ...\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        f"{allowed_list}\n"
        "- Only include files from the allowlist above.\n"
        "- Include every file you changed, with its full final content.\n"
        "- If you changed nothing, return {\"files\": []}.\n"
        "- Do not use shell commands to edit files.\n"
        "- Keep any explanatory text outside the JSON block minimal.\n"
    )


async def run_codex_turn(
    *,
    cwd: Path,
    editable_paths: list[Path],
    prompt: str,
    system_prompt: str,
    model: str | None = None,
    effort: str | None = "xhigh",
    sandbox: str = "read-only",
    service_name: str = "taiji_yin",
) -> tuple[str | None, str]:
    """Run a single Codex turn. Returns (thread_id, response_text).

    Codex returns a manifest of file contents for allowlisted paths and the
    host applies those edits mechanically. We prepend the system prompt to the
    user prompt since codex app-server doesn't have a separate system prompt
    field.
    """
    client = await CodexAppServer.connect(cwd, service_name=service_name)
    try:
        # Start thread
        thread_resp = await client.request("thread/start", {
            "cwd": str(cwd),
            "model": model,
            "approvalPolicy": "never",
            "sandbox": sandbox,
            "serviceName": service_name,
            "ephemeral": True,
        })
        thread_id = thread_resp["thread"]["id"]

        # Codex sandbox file writes are unreliable, so we ask it to output a
        # structured manifest of full file contents. The host applies the edits.
        write_instruction = _codex_write_instruction(editable_paths, cwd)
        full_prompt = f"{system_prompt}\n\n{write_instruction}{prompt}" if system_prompt else f"{write_instruction}{prompt}"

        # Start turn and then poll notifications until the turn completes.
        turn_resp = await client.request("turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": full_prompt, "text_elements": []}],
            "model": model,
            "effort": effort,
            "outputSchema": None,
        })
        turn_id = str(turn_resp.get("turn", {}).get("id", "")).strip()

        # Poll notifications until turn/completed
        response_parts = []
        completed = False
        deadline = asyncio.get_running_loop().time() + TURN_COMPLETION_TIMEOUT_SEC
        print("[codex] Waiting for turn completion...")
        while not completed:
            await asyncio.sleep(0.5)
            if client._proc.poll() is not None:
                raise RuntimeError(client._exit_message())
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError(
                    f"Codex turn timed out after {TURN_COMPLETION_TIMEOUT_SEC:.0f}s waiting for turn/completed"
                )
            for notif in client.drain_notifications():
                method = notif.get("method", "")
                params = notif.get("params", {})

                if method == "item/completed":
                    item = params.get("item", {})
                    itype = item.get("type", "")
                    print(f"[codex] item/completed: {itype}")
                    if itype == "agentMessage":
                        text = _item_text(item)
                        if text:
                            response_parts.append(text)
                            print(f"[codex]   text: {text[:200]}")
                    elif itype == "commandExecution":
                        cmd = item.get("command", "")
                        print(f"[codex]   cmd: {cmd[:200]}")

                if method == "turn/completed" and (not turn_id or params.get("turnId") == turn_id):
                    print(f"[codex] Turn completed. Response parts: {len(response_parts)}")
                    completed = True
                    break
                if method == "turn/failed" and (not turn_id or params.get("turnId") == turn_id):
                    raise RuntimeError(f"Codex turn failed: {json.dumps(params)}")
                if method == "error" and not bool(params.get("willRetry")):
                    error = params.get("error", {})
                    raise RuntimeError(f"Codex transport error: {error.get('message', 'unknown error')}")

        response_text = "\n".join(response_parts).strip()

        # Materialize every file Codex explicitly returned in the manifest.
        written_paths = _apply_codex_file_edits(
            response_text=response_text,
            editable_paths=editable_paths,
            cwd=cwd,
        )
        for path in written_paths:
            print(f"[codex] Wrote {path.name}")

        return thread_id, response_text
    finally:
        await client.close()


def codex_available() -> bool:
    """Check if the codex CLI is installed and authenticated."""
    codex_bin = shutil.which("codex")
    if codex_bin is None:
        return False
    try:
        env = _codex_process_env(Path.cwd(), service_name="availability")
        result = subprocess.run(
            [codex_bin, "login", "status"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        return result.returncode == 0
    except Exception:
        return False
