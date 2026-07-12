# Changelog

All notable changes to Agnetic Starship OS.

## [0.2.0] — 2026-07-11

### Added
- **Tool System** — 8 sandboxed tools: shell, read_file, write_file, list_dir, http_get, http_post, search_files, delegate_to_agent
- **Tool Compositing** — TOOLSETS pattern (core, network, delegation, full, readonly, webhook_safe)
- **CommandExecutor** — Sandboxed execution with dry-run, timeout, and redaction
- **Typed Errors** — ToolError, SandboxError, TimeoutError, AccessDeniedError
- **Tool Call Auto-Repair** — Fixes malformed JSON arguments from models
- **SSE Streaming** — `/api/chat/stream` endpoint for real-time token-by-token chat
- **Multi-Agent Delegation** — `delegate_to_agent` tool for Ergo→Proxy/Romi coordination
- **NATS Authentication** — Per-agent tokens with subject-level permissions
- **Encrypted Config** — AES-256-GCM with PBKDF2 key derivation
- **Secrets Manager** — Encrypted API key/token storage
- **AppArmor Profiles** — agnetic-agent, ollama, nats (deny-by-default)
- **Secret Redaction** — Auto-redacts tokens/keys from tool output
- **README.md** — Comprehensive project documentation
- **AGENT_GUIDE.md** — Developer guide for creating new agents
- **SECURITY.md** — Security architecture documentation

### Changed
- Agent daemon now uses chat API with tool calling loop (max 10 rounds)
- Dashboard server.py enhanced with streaming endpoint
- Tool arguments auto-repaired before execution

## [0.1.0] — 2026-07-11

### Added
- **Restructured** as Agnetic Starship OS monorepo
- **GPU Detection** — `scripts/detect-gpu.sh` (NVIDIA/AMD/Intel, WSL2 support)
- **Systemd Daemon Mode** — 7 service units with security hardening
- **Debian Packaging** — `.deb` package with postinst/prerm/postrm scripts
- **ISO Building** — live-build configuration for Ubuntu 24.04
- **Dynamic Dashboard** — Reads agent YAML configs, GPU info, Ollama models
- **Ollama Model Manager** — List, pull, delete models from web UI
- **Agent Auto-Pull** — Agents pull their model on first start
- **CLI** — `agneticctl` (Go/Cobra) with ping, agent, version commands
- **StarAgent** — Rust telemetry collector → NATS
- **3 Agent Daemons** — proxy, romi, ergo with YAML configs
- **NATS + JetStream** — Agent-to-agent message bus
- **Makefile** — build, dev, status, stop, install, deb, iso targets

### Infrastructure
- Go 1.24.4, Rust 1.97.0, NATS 2.14.3
- Python venv with nats-py, aiohttp, httpx, PyYAML
- GitHub: https://github.com/andromi-hash/agnetic-os
