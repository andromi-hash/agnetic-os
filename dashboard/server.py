#!/usr/bin/env python3
"""Agnetic OS Web Dashboard — dynamic config, real-time status, Ollama management."""

import sys
import os
import json
import asyncio
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("agnetic-dash")

NATS_URL = os.getenv("NATS_URL", "nats://127.0.0.1:4222")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
PORT = int(os.getenv("DASHBOARD_PORT", "8899"))
STATUS_FILE = Path("/tmp/agnetic-status.json")
GPU_STATE = Path("/tmp/agnetic-gpu-state.json")
HISTORY_DIR = Path("/tmp/agnetic-history")
PROJECT_DIR = Path(os.getenv("AGNETIC_ROOT", os.path.dirname(os.path.abspath(__file__)).replace("/dashboard", "")))

nc = None


def load_agent_configs():
    """Load agent configs from YAML files."""
    configs = {}
    agents_dir = PROJECT_DIR / "agents"
    for yaml_file in agents_dir.glob("*.yaml"):
        if yaml_file.name == "config.yaml":
            continue
        try:
            import yaml
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            if data and "agent" in data:
                name = data["agent"].get("name", yaml_file.stem)
                configs[name] = {
                    "name": name,
                    "model": data["agent"].get("model", "unknown"),
                    "description": data["agent"].get("description", ""),
                    "skills": data["agent"].get("skills", []),
                    "nats_subjects": data["agent"].get("nats", {}).get("subjects", {}),
                    "file": yaml_file.name,
                }
        except Exception as e:
            log.warning(f"Failed to load {yaml_file}: {e}")

    # Fallback: read main config.yaml
    if not configs:
        config_file = agents_dir / "config.yaml"
        if config_file.exists():
            try:
                import yaml
                with open(config_file) as f:
                    data = yaml.safe_load(f)
                for name, agent_data in data.get("agents", {}).items():
                    configs[name] = {
                        "name": name,
                        "model": agent_data.get("model", "unknown"),
                        "description": f"{name} agent",
                        "skills": agent_data.get("skills", []),
                        "file": "config.yaml",
                    }
            except Exception as e:
                log.warning(f"Failed to load config.yaml: {e}")

    return configs


def get_gpu_info():
    """Read GPU state from detect-gpu output."""
    try:
        if GPU_STATE.exists():
            return json.loads(GPU_STATE.read_text())
    except (json.JSONDecodeError, IOError):
        pass
    return {"vendor": "none"}


def get_system_telemetry():
    """Read system telemetry from status file."""
    try:
        if STATUS_FILE.exists():
            return json.loads(STATUS_FILE.read_text())
    except (json.JSONDecodeError, IOError):
        pass
    return {"agents": {}, "telemetry": {}, "messages": []}


async def get_nats():
    global nc
    if nc is None or not nc.is_connected:
        from nats import connect as nats_connect
        nc = await nats_connect(NATS_URL)
    return nc


async def get_ollama_models():
    """Fetch Ollama model list."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{OLLAMA_URL}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("models", [])
    except Exception:
        pass
    return []


async def get_agent_process_status():
    """Check which agent daemons are running."""
    agents = {}
    for name in ["proxy", "romi", "ergo"]:
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"agent_daemon.py {name}"],
                capture_output=True, timeout=2
            )
            agents[name] = result.returncode == 0
        except Exception:
            agents[name] = False
    return agents


async def handle_index(request):
    index_html = PROJECT_DIR / "dashboard" / "index.html"
    if index_html.exists():
        return web.Response(text=index_html.read_text(), content_type="text/html")
    return web.Response(text="<h1>Dashboard loading...</h1>", content_type="text/html")


async def handle_api_dashboard(request):
    """Main dashboard API — returns all data needed by the UI."""
    agent_configs = load_agent_configs()
    agent_status = await get_agent_process_status()
    gpu_info = get_gpu_info()
    telemetry = get_system_telemetry()
    ollama_models = await get_ollama_models()

    # Merge agent configs with runtime status
    agents = {}
    for name, config in agent_configs.items():
        agents[name] = {
            **config,
            "running": agent_status.get(name, False),
            "status": "online" if agent_status.get(name, False) else "offline",
        }

    # Add any agents from runtime status not in configs
    for name, running in agent_status.items():
        if name not in agents:
            agents[name] = {
                "name": name,
                "model": "unknown",
                "description": "",
                "skills": [],
                "running": running,
                "status": "online" if running else "offline",
            }

    return web.json_response({
        "agents": agents,
        "telemetry": telemetry.get("telemetry", {}),
        "messages": telemetry.get("messages", []),
        "gpu": gpu_info,
        "ollama": {
            "url": OLLAMA_URL,
            "models": [{"name": m.get("name", ""), "size": m.get("size", 0)} for m in ollama_models],
        },
        "nats": {"url": NATS_URL, "connected": nc.is_connected if nc else False},
        "timestamp": datetime.now().isoformat(),
    })


async def handle_api_agents(request):
    """Return agent configs and status."""
    agent_configs = load_agent_configs()
    agent_status = await get_agent_process_status()
    agents = {}
    for name, config in agent_configs.items():
        agents[name] = {
            **config,
            "running": agent_status.get(name, False),
        }
    return web.json_response({"agents": agents})


async def handle_api_gpu(request):
    return web.json_response(get_gpu_info())


async def handle_api_ollama_models(request):
    """List Ollama models."""
    models = await get_ollama_models()
    return web.json_response({"models": models})


async def handle_api_ollama_pull(request):
    """Pull an Ollama model."""
    try:
        body = await request.json()
        model = body.get("model", "")
        if not model:
            return web.json_response({"error": "model name required"}, status=400)

        # Pull in background
        async def pull_model():
            proc = await asyncio.create_subprocess_exec(
                "ollama", "pull", model,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await proc.communicate()

        asyncio.create_task(pull_model())
        return web.json_response({"status": "pulling", "model": model})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_api_ollama_delete(request):
    """Delete an Ollama model."""
    try:
        body = await request.json()
        model = body.get("model", "")
        if not model:
            return web.json_response({"error": "model name required"}, status=400)
        proc = await asyncio.create_subprocess_exec(
            "ollama", "rm", model,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return web.json_response({"status": "deleted", "model": model, "output": stdout.decode()})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_send(request):
    try:
        body = await request.json()
        agent = body.get("agent", "proxy")
        command = body.get("command", "ping")
        args = body.get("args", {})

        nats = await get_nats()
        safe_command = command.replace(" ", ".")
        if not safe_command:
            safe_command = "ping"
        subject = f"agnetic.agent.{agent}.command.{safe_command}"
        reply = f"agnetic.reply.{datetime.now().timestamp()}"
        sub = await nats.subscribe(reply, max_msgs=1)

        await nats.publish(subject, json.dumps({
            "command": command,
            "args": args,
            "reply_to": reply,
        }).encode())

        try:
            msg = await sub.next_msg(timeout=120)
            result = json.loads(msg.data.decode())
            return web.json_response(result)
        except asyncio.TimeoutError:
            return web.json_response({"error": "timeout", "response": "Agent did not respond in 120s"})
    except Exception as e:
        return web.json_response({"error": str(e)})


async def handle_logs(request):
    agent = request.query.get("agent", "proxy")
    log_file = PROJECT_DIR / "logs" / f"agents-{agent}.log"
    if not log_file.exists():
        log_file = PROJECT_DIR / "logs" / f"{agent}.log"
    try:
        lines = log_file.read_text().splitlines()[-100:]
        return web.json_response({"agent": agent, "lines": lines})
    except (FileNotFoundError, IOError):
        return web.json_response({"agent": agent, "lines": ["No log file found"]})


async def handle_history(request):
    agent = request.query.get("agent", "")
    limit = int(request.query.get("limit", "50"))
    results = []
    for f in sorted(HISTORY_DIR.glob("*.jsonl"), reverse=True)[:3]:
        if not f.exists():
            continue
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if agent and agent not in entry.get("subject", ""):
                        continue
                    results.append(entry)
                    if len(results) >= limit:
                        break
                except json.JSONDecodeError:
                    continue
            if len(results) >= limit:
                break
    return web.json_response({"messages": results, "total": len(results)})


async def handle_health(request):
    agent_status = await get_agent_process_status()
    nats_ok = False
    try:
        nats = await get_nats()
        nats_ok = nats.is_connected
    except Exception:
        pass

    return web.json_response({
        "status": "ok",
        "nats_connected": nats_ok,
        "agents_running": agent_status,
        "staragent_running": os.system("pgrep -x staragent > /dev/null 2>&1") == 0,
        "timestamp": datetime.now().isoformat(),
    })


app = web.Application()
app.router.add_get("/", handle_index)
app.router.add_get("/api/dashboard", handle_api_dashboard)
app.router.add_get("/api/agents", handle_api_agents)
app.router.add_get("/api/gpu", handle_api_gpu)
app.router.add_get("/api/ollama/models", handle_api_ollama_models)
app.router.add_post("/api/ollama/pull", handle_api_ollama_pull)
app.router.add_post("/api/ollama/delete", handle_api_ollama_delete)
app.router.add_get("/api/logs", handle_logs)
app.router.add_get("/api/history", handle_history)
app.router.add_post("/api/send", handle_send)
app.router.add_get("/api/health", handle_health)


async def cleanup(app):
    global nc
    if nc:
        await nc.close()

app.on_shutdown.append(cleanup)

if __name__ == "__main__":
    log.info("Agnetic Dashboard starting on http://0.0.0.0:%d", PORT)
    web.run_app(app, host="0.0.0.0", port=PORT)
