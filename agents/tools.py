#!/usr/bin/env python3
"""
Agnetic OS Tool System — sandboxed execution for agents.

Borrowed patterns:
- Hermes Agent: TOOLSETS compositing, tool call auto-repair, callback-driven streaming
- Flamingo Stack: CommandExecutor interface, typed errors, dry-run + redaction
"""

import os
import json
import asyncio
import logging
import subprocess
import shutil
import signal
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("agnetic-tools")


# ─── Typed Errors (Flamingo pattern) ────────────────────────────────
class ToolError(Exception):
    """Base tool error with code."""
    def __init__(self, message: str, code: str = "TOOL_ERROR", details: dict = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self):
        return {"error": True, "code": self.code, "message": str(self), "details": self.details}


class SandboxError(ToolError):
    def __init__(self, message, command=""):
        super().__init__(message, code="SANDBOX_DENIED", details={"command": command})


class TimeoutError(ToolError):
    def __init__(self, command, timeout):
        super().__init__(f"Command timed out after {timeout}s", code="TIMEOUT", details={"command": command, "timeout": timeout})


class AccessDeniedError(ToolError):
    def __init__(self, path, operation="read"):
        super().__init__(f"Access denied: {path} ({operation})", code="ACCESS_DENIED", details={"path": path, "operation": operation})


# ─── Sandbox Configuration ──────────────────────────────────────────
BLOCKED_COMMANDS = [
    "rm -rf /", "mkfs", "dd if=", "> /dev/", ":(){ :|:&", "shutdown",
    "reboot", "halt", "poweroff", "init 0", "init 6",
]

PRIVILEGED_COMMANDS = ["sudo", "su ", "chmod 777", "chown", "passwd", "useradd", "userdel"]

ALLOWED_READ_PATHS = ["/home", "/tmp", "/opt/agnetic", "/etc/agnetic", "/var/log/agnetic"]
ALLOWED_WRITE_PATHS = ["/tmp", "/opt/agnetic", "/var/log/agnetic"]

MAX_OUTPUT_SIZE = 50000
MAX_FILE_SIZE = 1048576
DEFAULT_TIMEOUT = 30


# ─── Redaction (Flamingo pattern) ───────────────────────────────────
REDACT_PATTERNS = [
    (r'(?i)(password|token|secret|key)\s*[=:]\s*\S+', r'\1=***REDACTED***'),
    (r'ghp_[a-zA-Z0-9]+', 'ghp_***REDACTED***'),
    (r'sk-[a-zA-Z0-9]+', 'sk-***REDACTED***'),
]


def redact(text: str) -> str:
    """Redact secrets from output."""
    import re
    for pattern, replacement in REDACT_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


# ─── CommandExecutor (Flamingo pattern) ─────────────────────────────
@dataclass
class ExecuteResult:
    """Result of a command execution."""
    exit_code: int
    stdout: str
    stderr: str = ""
    timed_out: bool = False
    command: str = ""

    @property
    def success(self):
        return self.exit_code == 0

    def to_dict(self):
        return {
            "output": self.stdout,
            "error_output": self.stderr,
            "exit_code": self.exit_code,
            "error": not self.success,
            "timed_out": self.timed_out,
        }


class CommandExecutor:
    """Sandboxed command executor with timeout and dry-run support.

    Borrowed from Flamingo Stack's CommandExecutor pattern.
    """

    def __init__(self, dry_run=False, sandbox=True, timeout=DEFAULT_TIMEOUT):
        self.dry_run = dry_run
        self.sandbox = sandbox
        self.default_timeout = timeout

    def _validate(self, command: str):
        """Validate command against sandbox rules."""
        if not self.sandbox:
            return

        cmd_lower = command.lower().strip()
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                raise SandboxError(f"Blocked: '{blocked}'", command)

        for priv in PRIVILEGED_COMMANDS:
            if priv in cmd_lower:
                raise SandboxError(f"Blocked: privileged command '{priv}'", command)

    async def execute(self, command: str, timeout: int = None, env: dict = None) -> ExecuteResult:
        """Execute a shell command with sandboxing."""
        timeout = timeout or self.default_timeout
        self._validate(command)

        if self.dry_run:
            log.info("[DRY RUN] Would execute: %s", redact(command))
            return ExecuteResult(exit_code=0, stdout=f"[DRY RUN] {command}", command=command)

        try:
            merged_env = {**os.environ, "TERM": "dumb"}
            if env:
                merged_env.update(env)

            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecuteResult(
                exit_code=proc.returncode,
                stdout=stdout.decode(errors="replace")[:MAX_OUTPUT_SIZE],
                stderr=stderr.decode(errors="replace")[:MAX_OUTPUT_SIZE],
                command=command,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return ExecuteResult(exit_code=-1, stdout="", stderr=f"Timeout after {timeout}s", timed_out=True, command=command)
        except Exception as e:
            return ExecuteResult(exit_code=-1, stdout="", stderr=str(e), command=command)


# ─── Tool Compositing (Hermes pattern) ──────────────────────────────
TOOLSETS = {
    "core": {
        "description": "Basic filesystem and shell operations",
        "tools": ["shell", "read_file", "write_file", "list_dir", "search_files"],
    },
    "network": {
        "description": "HTTP requests and API calls",
        "tools": ["http_get", "http_post"],
    },
    "delegation": {
        "description": "Multi-agent task delegation",
        "tools": ["delegate_to_agent"],
    },
    "full": {
        "description": "All available tools",
        "includes": ["core", "network", "delegation"],
    },
    "readonly": {
        "description": "Read-only operations (no writes, no shell)",
        "tools": ["read_file", "list_dir", "search_files", "http_get"],
    },
    "webhook_safe": {
        "description": "Safe tools for untrusted input (no shell, no writes)",
        "tools": ["read_file", "list_dir", "search_files", "http_get"],
    },
}


def resolve_toolset(name: str) -> list:
    """Resolve a toolset name to a flat list of tool names."""
    if name not in TOOLSETS:
        return []

    ts = TOOLSETS[name]
    tools = list(ts.get("tools", []))

    for include in ts.get("includes", []):
        tools.extend(resolve_toolset(include))

    return list(set(tools))


def get_tool_definitions(toolset: str = "full") -> list:
    """Get Ollama-compatible tool definitions for a toolset."""
    allowed = set(resolve_toolset(toolset))
    return [t for t in TOOL_DEFINITIONS if t["function"]["name"] in allowed]


# ─── Tool Call Auto-Repair (Hermes pattern) ─────────────────────────
def repair_tool_arguments(args: Any, tool_name: str) -> dict:
    """Attempt to repair malformed tool call arguments.

    Borrowed from Hermes Agent's _repair_tool_call_arguments().
    Models sometimes return corrupted JSON for tool arguments.
    """
    if isinstance(args, dict):
        return args

    if isinstance(args, str):
        # Try parsing as JSON
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Try fixing common issues
        fixed = args.strip()
        if fixed.startswith("'") and fixed.endswith("'"):
            fixed = fixed[1:-1]
        if not fixed.startswith("{"):
            fixed = "{" + fixed
        if not fixed.endswith("}"):
            fixed = fixed + "}"

        try:
            parsed = json.loads(fixed)
            if isinstance(parsed, dict):
                log.warning("Repaired malformed arguments for %s", tool_name)
                return parsed
        except json.JSONDecodeError:
            pass

        # Last resort: wrap as {"command": args} for shell-like tools
        if tool_name == "shell":
            return {"command": args}
        if tool_name in ("read_file", "list_dir"):
            return {"path": args}

    log.warning("Could not repair arguments for %s: %s", tool_name, str(args)[:100])
    return {}


# ─── Tool Definitions (Ollama function calling format) ──────────────
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Execute a shell command and return its output. Use for running programs, checking system status, installing packages, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read"},
                    "lines": {"type": "integer", "description": "Max lines to read (optional)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates the file if it doesn't exist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List contents of a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the directory"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_get",
            "description": "Make an HTTP GET request and return the response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "headers": {"type": "object", "description": "Optional headers"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_post",
            "description": "Make an HTTP POST request with JSON body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to post to"},
                    "body": {"type": "object", "description": "JSON body"},
                    "headers": {"type": "object", "description": "Optional headers"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for files by name pattern or grep content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern or grep regex"},
                    "path": {"type": "string", "description": "Directory to search in"},
                    "content": {"type": "string", "description": "If set, grep for this in file contents"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_agent",
            "description": "Delegate a task to another agent. Use for multi-agent coordination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "Agent name (proxy, romi, ergo)"},
                    "command": {"type": "string", "description": "Command to send"},
                    "args": {"type": "object", "description": "Optional arguments"},
                },
                "required": ["agent", "command"],
            },
        },
    },
]


# ─── Tool Execution ─────────────────────────────────────────────────
_executor = CommandExecutor(sandbox=True)


async def execute_tool(name: str, arguments: dict, nats=None, callbacks: dict = None) -> dict:
    """Execute a tool by name with given arguments.

    Args:
        name: Tool name
        arguments: Tool arguments dict
        nats: NATS connection for delegation
        callbacks: Optional dict of callbacks for streaming progress
    """
    callbacks = callbacks or {}

    # Auto-repair arguments (Hermes pattern)
    arguments = repair_tool_arguments(arguments, name)

    # Emit tool start (Hermes callback pattern)
    if "tool_start" in callbacks:
        callbacks["tool_start"](name, arguments)

    try:
        if name == "shell":
            result = await _tool_shell(arguments)
        elif name == "read_file":
            result = _tool_read_file(arguments)
        elif name == "write_file":
            result = _tool_write_file(arguments)
        elif name == "list_dir":
            result = _tool_list_dir(arguments)
        elif name == "http_get":
            result = await _tool_http_get(arguments)
        elif name == "http_post":
            result = await _tool_http_post(arguments)
        elif name == "search_files":
            result = _tool_search_files(arguments)
        elif name == "delegate_to_agent":
            result = await _tool_delegate(nats, arguments)
        else:
            result = {"error": True, "message": f"Unknown tool: {name}"}
    except ToolError as e:
        result = e.to_dict()
    except Exception as e:
        log.error("Tool execution error (%s): %s", name, e)
        result = {"error": True, "message": str(e)}

    # Redact secrets from output (Flamingo pattern)
    if "output" in result:
        result["output"] = redact(result["output"])

    # Emit tool complete (Hermes callback pattern)
    if "tool_complete" in callbacks:
        callbacks["tool_complete"](name, result)

    return result


async def _tool_shell(args: dict) -> dict:
    cmd = args.get("command", "")
    timeout = args.get("timeout", DEFAULT_TIMEOUT)
    result = await _executor.execute(cmd, timeout=timeout)
    return result.to_dict()


def _tool_read_file(args: dict) -> dict:
    path = args.get("path", "")
    lines = args.get("lines", 0)

    if not _check_path(path, "read"):
        raise AccessDeniedError(path, "read")

    try:
        p = Path(path)
        if not p.exists():
            return {"content": f"File not found: {path}", "error": True}
        if p.stat().st_size > MAX_FILE_SIZE:
            return {"content": f"File too large ({p.stat().st_size} bytes)", "error": True}

        content = p.read_text(errors="replace")
        if lines > 0:
            content = "\n".join(content.splitlines()[:lines])
        return {"content": content, "error": False}
    except ToolError:
        raise
    except Exception as e:
        return {"content": str(e), "error": True}


def _tool_write_file(args: dict) -> dict:
    path = args.get("path", "")
    content = args.get("content", "")

    if not _check_path(path, "write"):
        raise AccessDeniedError(path, "write")

    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return {"output": f"Written {len(content)} bytes to {path}", "error": False}
    except Exception as e:
        return {"output": str(e), "error": True}


def _tool_list_dir(args: dict) -> dict:
    path = args.get("path", ".")

    if not _check_path(path, "read"):
        raise AccessDeniedError(path, "list")

    try:
        p = Path(path)
        if not p.exists():
            return {"entries": [], "error": True, "message": f"Not found: {path}"}
        entries = []
        for item in sorted(p.iterdir()):
            entry = {"name": item.name, "type": "dir" if item.is_dir() else "file"}
            try:
                entry["size"] = item.stat().st_size
            except Exception:
                entry["size"] = 0
            entries.append(entry)
        return {"entries": entries, "error": False}
    except Exception as e:
        return {"entries": [], "error": True, "message": str(e)}


async def _tool_http_get(args: dict) -> dict:
    import httpx
    url = args.get("url", "")
    headers = args.get("headers", {})

    if not url.startswith(("http://", "https://")):
        return {"status_code": 0, "body": "Invalid URL", "error": True}

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            body = resp.text[:MAX_OUTPUT_SIZE]
            return {"status_code": resp.status_code, "body": redact(body), "error": resp.status_code >= 400}
    except Exception as e:
        return {"status_code": 0, "body": str(e), "error": True}


async def _tool_http_post(args: dict) -> dict:
    import httpx
    url = args.get("url", "")
    body = args.get("body", {})
    headers = args.get("headers", {})
    headers.setdefault("Content-Type", "application/json")

    if not url.startswith(("http://", "https://")):
        return {"status_code": 0, "body": "Invalid URL", "error": True}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp_body = redact(resp.text[:MAX_OUTPUT_SIZE])
            return {"status_code": resp.status_code, "body": resp_body, "error": resp.status_code >= 400}
    except Exception as e:
        return {"status_code": 0, "body": str(e), "error": True}


def _tool_search_files(args: dict) -> dict:
    pattern = args.get("pattern", "*")
    path = args.get("path", ".")
    content = args.get("content", "")

    if not _check_path(path, "read"):
        raise AccessDeniedError(path, "search")

    try:
        p = Path(path)
        if content:
            results = []
            for f in p.rglob("*"):
                if f.is_file() and f.stat().st_size < MAX_FILE_SIZE:
                    try:
                        text = f.read_text(errors="replace")
                        for i, line in enumerate(text.splitlines(), 1):
                            if content.lower() in line.lower():
                                results.append({"file": str(f), "line": i, "match": line.strip()[:200]})
                                if len(results) >= 50:
                                    break
                    except Exception:
                        continue
                if len(results) >= 50:
                    break
            return {"results": results, "error": False}
        else:
            results = []
            for f in p.glob(pattern):
                results.append({"path": str(f), "type": "dir" if f.is_dir() else "file"})
                if len(results) >= 100:
                    break
            return {"results": results, "error": False}
    except Exception as e:
        return {"results": [], "error": True, "message": str(e)}


async def _tool_delegate(nats, args: dict) -> dict:
    agent = args.get("agent", "")
    command = args.get("command", "")
    extra_args = args.get("args", {})

    if not nats:
        return {"error": "NATS not connected — cannot delegate"}

    subject = f"agnetic.agent.{agent}.command.{command.replace(' ', '.')}"
    reply = f"agnetic.delegate.{datetime.now().timestamp()}"

    try:
        sub = await nats.subscribe(reply, max_msgs=1)
        await nats.publish(subject, json.dumps({
            "command": command,
            "args": extra_args,
            "reply_to": reply,
        }).encode())

        msg = await sub.next_msg(timeout=60)
        result = json.loads(msg.data.decode())
        return result
    except asyncio.TimeoutError:
        return {"error": f"Agent '{agent}' did not respond in 60s"}
    except Exception as e:
        return {"error": str(e)}


def _check_path(path: str, operation: str = "read") -> bool:
    """Validate path against allowed directories."""
    try:
        resolved = Path(path).resolve()
        paths = ALLOWED_READ_PATHS if operation == "read" else ALLOWED_WRITE_PATHS
        return any(str(resolved).startswith(allowed) for allowed in paths)
    except Exception:
        return False
