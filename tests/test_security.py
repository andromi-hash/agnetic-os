import os
import json
import secrets
import pytest
from pathlib import Path
from unittest.mock import patch

import security


class TestGenerateTokens:
    def test_generate_tokens(self, tmp_path, monkeypatch):
        monkeypatch.setattr(security, "SECRETS_DIR", tmp_path / "secrets")
        tokens = security.generate_agent_tokens()
        assert isinstance(tokens, dict)
        assert "proxy" in tokens
        assert "romi" in tokens
        assert "ergo" in tokens
        assert "staragent" in tokens
        assert "dashboard" in tokens
        assert "operator" in tokens
        for agent, token in tokens.items():
            assert len(token) == 64

    def test_token_files_created(self, tmp_path, monkeypatch):
        secrets_dir = tmp_path / "secrets"
        monkeypatch.setattr(security, "SECRETS_DIR", secrets_dir)
        security.generate_agent_tokens()
        for agent in ["proxy", "romi", "ergo", "staragent", "dashboard", "operator"]:
            token_file = secrets_dir / f"{agent}.token"
            assert token_file.exists()
            content = token_file.read_text()
            assert len(content) == 64

    def test_load_agent_token(self, tmp_path, monkeypatch):
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "proxy.token").write_text("testtoken1234567890")
        monkeypatch.setattr(security, "SECRETS_DIR", secrets_dir)
        token = security.load_agent_token("proxy")
        assert token == "testtoken1234567890"

    def test_load_agent_token_fallback_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr(security, "SECRETS_DIR", tmp_path / "empty")
        monkeypatch.setenv("AGENTIC_TEST_TOKEN", "envtoken12345")
        token = security.load_agent_token("test")
        assert token == "envtoken12345"


class TestNatsAuthConfig:
    def test_nats_auth_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(security, "SECRETS_DIR", tmp_path / "secrets")
        tokens = security.generate_agent_tokens()
        config = security.generate_nats_config(tokens)
        assert "port: 4222" in config
        assert "jetstream" in config
        assert "accounts:" in config
        assert "proxy" in config
        assert "romi" in config
        assert "ergo" in config

    def test_nats_config_has_permissions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(security, "SECRETS_DIR", tmp_path / "secrets")
        tokens = security.generate_agent_tokens()
        config = security.generate_nats_config(tokens)
        assert "publish" in config
        assert "subscribe" in config
        assert "agnetic.agent.proxy" in config

    def test_nats_config_generates_tokens_if_none(self, monkeypatch):
        monkeypatch.setattr(security, "SECRETS_DIR", Path("/tmp/test-empty-secrets"))
        config = security.generate_nats_config()
        assert isinstance(config, str)
        assert "port: 4222" in config


class TestPermissionScopes:
    def test_permission_scopes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(security, "SECRETS_DIR", tmp_path / "secrets")
        tokens = security.generate_agent_tokens()
        config = security.generate_nats_config(tokens)
        assert "allow" in config
        for scope in ["agnetic.agent.proxy.>", "agnetic.agent.romi.>", "agnetic.agent.ergo.>",
                       "agnetic.telemetry.>"]:
            assert scope in config


class TestApparmorProfileExists:
    def test_apparmor_profile_exists(self):
        profile_path = Path(__file__).resolve().parent.parent / "security" / "apparmor" / "agnetic-agent"
        assert profile_path.exists()
        content = profile_path.read_text()
        assert "agnetic-agent" in content
        assert "deny capability" in content
        assert "network inet stream" in content
