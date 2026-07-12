import time
import pytest
from unittest.mock import patch, MagicMock

import watchdog as wd


class TestCheckProcess:
    def test_check_process(self):
        result = wd.check_process("python")
        assert isinstance(result, bool)

    def test_check_process_nonexistent(self):
        result = wd.check_process("zzz_nonexistent_process_xyz_99999")
        assert result is False

    def test_check_port(self):
        result = wd.check_port(1)
        assert isinstance(result, bool)

    def test_check_port_invalid(self):
        result = wd.check_port(99999)
        assert result is False


class TestBackoffEscalation:
    def test_backoff_escalation(self):
        state = wd.ServiceState("test-service")
        assert state.backoff_seconds == 0
        assert state.should_restart_now is False

        state.record_failure()
        assert state.consecutive_failures == 1
        assert state.backoff_seconds == 0
        assert state.should_restart_now is True

        state.record_failure()
        assert state.consecutive_failures == 2
        assert state.backoff_seconds == 10

        state.record_failure()
        assert state.consecutive_failures == 3
        assert state.backoff_seconds == 30

        state.record_failure()
        assert state.consecutive_failures == 4
        assert state.backoff_seconds == 60

    def test_backoff_caps_at_max(self):
        state = wd.ServiceState("test-service")
        for _ in range(10):
            state.record_failure()
        assert state.backoff_seconds == 60


class TestBackoffReset:
    def test_backoff_reset(self):
        state = wd.ServiceState("test-service")
        state.record_failure()
        state.record_failure()
        state.record_failure()
        assert state.consecutive_failures == 3
        state.record_healthy()
        assert state.consecutive_failures == 0
        assert state.backoff_seconds == 0
        assert state.should_restart_now is False

    def test_mark_restarted(self):
        state = wd.ServiceState("test-service")
        state.record_failure()
        assert state.last_restart_ts == 0
        assert state.should_restart_now is True
        state.mark_restarted()
        assert state.last_restart_ts > 0


class TestLoadConfig:
    def test_load_config_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wd, "CONFIG_PATH", tmp_path / "watchdog.yaml")
        config = wd.load_config()
        assert "check_interval" in config
        assert "services" in config
        assert "nats" in config["services"]
        assert "proxy" in config["services"]

    def test_default_services_structure(self):
        for name, svc in wd.DEFAULT_SERVICES.items():
            assert "check" in svc
            assert "command" in svc
            assert isinstance(svc["check"], list)


class TestServiceState:
    def test_service_state_init(self):
        state = wd.ServiceState("my-svc")
        assert state.name == "my-svc"
        assert state.healthy is False
        assert state.consecutive_failures == 0

    def test_healthy_resets_failures(self):
        state = wd.ServiceState("svc")
        state.record_failure()
        state.record_failure()
        state.record_failure()
        state.record_healthy()
        assert state.consecutive_failures == 0
        assert state.healthy is True
