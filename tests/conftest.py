import sys
import os
import yaml
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(PROJECT_ROOT / "agents"))
sys.path.insert(0, str(PROJECT_ROOT / "services"))
sys.path.insert(0, str(PROJECT_ROOT / "dashboard"))


@pytest.fixture
def tmp_agents_dir(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    config = {
        "name": "proxy",
        "role": "tech_agent",
        "model": "qwen2.5:7b",
        "provider": "ollama",
        "capabilities": ["system_diagnostics", "log_analysis"],
        "skills": ["proxy-diagnostics"],
        "toolsets": ["terminal", "file_operations"],
        "nats": {
            "subjects": {
                "command": "agnetic.agent.proxy.command.>",
                "event": "agnetic.agent.proxy.event.>",
                "status": "agnetic.agent.proxy.status",
            }
        },
    }

    with open(agents_dir / "proxy.yaml", "w") as f:
        yaml.dump(config, f)

    return agents_dir


@pytest.fixture
def mock_nats():
    nc = AsyncMock()
    nc.is_connected = True
    nc.publish = AsyncMock()
    nc.subscribe = AsyncMock()
    nc.jetstream = MagicMock()
    nc.close = AsyncMock()
    return nc


@pytest.fixture
def sample_agent_yaml():
    return {
        "name": "proxy",
        "role": "tech_agent",
        "model": "qwen2.5:7b",
        "provider": "ollama",
        "capabilities": ["system_diagnostics", "troubleshooting"],
        "skills": ["system-health", "proxy-diagnostics"],
        "toolsets": ["terminal", "file_operations", "web_search", "nats"],
        "nats": {
            "subjects": {
                "command": "agnetic.agent.proxy.command.>",
                "event": "agnetic.agent.proxy.event.>",
                "status": "agnetic.agent.proxy.status",
            }
        },
    }
