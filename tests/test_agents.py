import sys
import os
import json
import yaml
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

import agent_daemon


class TestLoadAgentConfig:
    def test_load_agent_config(self, tmp_agents_dir, monkeypatch):
        monkeypatch.setattr(agent_daemon, "AGENTS_DIR", tmp_agents_dir)
        config = agent_daemon.load_agent_config("proxy")
        assert config["name"] == "proxy"
        assert config["model"] == "qwen2.5:7b"
        assert config["role"] == "tech_agent"

    def test_load_agent_config_missing(self, tmp_agents_dir, monkeypatch):
        monkeypatch.setattr(agent_daemon, "AGENTS_DIR", tmp_agents_dir)
        with pytest.raises(SystemExit):
            agent_daemon.load_agent_config("nonexistent")


class TestLoadSoul:
    def test_load_soul(self, tmp_path, monkeypatch):
        souls_dir = tmp_path / "souls" / "proxy"
        souls_dir.mkdir(parents=True)
        soul_file = souls_dir / "SOUL.md"
        soul_file.write_text("# Proxy Soul\nYou are Proxy.")

        monkeypatch.setattr(agent_daemon, "SOULS_DIR", tmp_path / "souls")
        content = agent_daemon.load_soul("proxy")
        assert content is not None
        assert "Proxy Soul" in content

    def test_load_soul_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_daemon, "SOULS_DIR", tmp_path / "souls")
        content = agent_daemon.load_soul("nonexistent")
        assert content is None


class TestSystemPrompt:
    def test_system_prompt_includes_soul(self, tmp_path, monkeypatch):
        souls_dir = tmp_path / "souls" / "proxy"
        souls_dir.mkdir(parents=True)
        (souls_dir / "SOUL.md").write_text("You are Proxy the security engineer.")

        monkeypatch.setattr(agent_daemon, "SOULS_DIR", tmp_path / "souls")
        monkeypatch.setattr(agent_daemon, "SKILLS_DIR", tmp_path / "skills")
        (tmp_path / "skills").mkdir()

        soul = agent_daemon.load_soul("proxy")
        assert soul is not None
        assert "security engineer" in soul


class TestToolSchemas:
    def test_tool_definitions_format(self):
        from tools import TOOL_DEFINITIONS
        assert len(TOOL_DEFINITIONS) > 0
        for td in TOOL_DEFINITIONS:
            assert td["type"] == "function"
            assert "function" in td
            assert "name" in td["function"]
            assert "description" in td["function"]
            assert "parameters" in td["function"]

    def test_shell_tool_has_command_param(self):
        from tools import TOOL_DEFINITIONS
        shell = next(d for d in TOOL_DEFINITIONS if d["function"]["name"] == "shell")
        params = shell["function"]["parameters"]
        assert "command" in params["properties"]
        assert "command" in params["required"]


class TestNatsSubjects:
    def test_nats_subjects_from_config(self, sample_agent_yaml):
        nats_config = sample_agent_yaml.get("nats", {})
        subjects = nats_config.get("subjects", {})
        assert "command" in subjects
        assert "event" in subjects
        assert "status" in subjects
        assert "proxy" in subjects["command"]

    def test_nats_subject_pattern(self, sample_agent_yaml):
        name = sample_agent_yaml["name"]
        subjects = sample_agent_yaml["nats"]["subjects"]
        assert subjects["command"] == f"agnetic.agent.{name}.command.>"
        assert subjects["status"] == f"agnetic.agent.{name}.status"
