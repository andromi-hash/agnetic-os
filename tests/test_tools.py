import pytest
import json
from unittest.mock import patch, MagicMock
from pathlib import Path

import tools


class TestSandbox:
    def test_sandbox_blocks_dangerous_commands(self):
        executor = tools.CommandExecutor(sandbox=True)
        with pytest.raises(tools.SandboxError, match="Blocked"):
            executor._validate("rm -rf /")

    def test_sandbox_blocks_path_traversal(self):
        executor = tools.CommandExecutor(sandbox=True)
        with pytest.raises(tools.SandboxError, match="privileged"):
            executor._validate("chmod 777 /etc/passwd")

    def test_sandbox_allows_safe_commands(self):
        executor = tools.CommandExecutor(sandbox=True)
        executor._validate("ls -la /tmp")
        executor._validate("cat /home/user/file.txt")
        executor._validate("python3 script.py")

    def test_sandbox_disabled(self):
        executor = tools.CommandExecutor(sandbox=False)
        executor._validate("sudo rm -rf /")
        executor._validate("rm -rf /")


class TestReadFile:
    def test_read_file_sandboxed(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        result = tools._tool_read_file({"path": str(test_file)})
        assert result["error"] is False
        assert result["content"] == "hello world"

    def test_read_file_not_found(self, tmp_path):
        result = tools._tool_read_file({"path": str(tmp_path / "nonexistent.txt")})
        assert result["error"] is True
        assert "not found" in result["content"].lower()

    def test_read_file_lines_limit(self, tmp_path):
        test_file = tmp_path / "lines.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5")
        result = tools._tool_read_file({"path": str(test_file), "lines": 3})
        assert result["error"] is False
        assert len(result["content"].splitlines()) == 3


class TestWriteFile:
    def test_write_file_sandboxed(self, tmp_path):
        test_file = tmp_path / "output.txt"
        result = tools._tool_write_file({"path": str(test_file), "content": "test data"})
        assert result["error"] is False
        assert test_file.read_text() == "test data"

    def test_write_file_creates_parents(self, tmp_path):
        test_file = tmp_path / "a" / "b" / "c.txt"
        result = tools._tool_write_file({"path": str(test_file), "content": "nested"})
        assert result["error"] is False
        assert test_file.read_text() == "nested"


class TestListDir:
    def test_list_dir_sandboxed(self, tmp_path):
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.txt").write_text("b")
        (tmp_path / "subdir").mkdir()
        result = tools._tool_list_dir({"path": str(tmp_path)})
        assert result["error"] is False
        names = [e["name"] for e in result["entries"]]
        assert "file1.txt" in names
        assert "file2.txt" in names
        assert "subdir" in names

    def test_list_dir_not_found(self, tmp_path):
        result = tools._tool_list_dir({"path": str(tmp_path / "nonexistent")})
        assert result["error"] is True


class TestToolCallRepair:
    def test_tool_call_repair_json(self):
        result = tools.repair_tool_arguments('{"command": "ls"}', "shell")
        assert result == {"command": "ls"}

    def test_tool_call_repair_dict_passthrough(self):
        result = tools.repair_tool_arguments({"command": "ls"}, "shell")
        assert result == {"command": "ls"}

    def test_tool_call_repair_wraps_shell_string(self):
        result = tools.repair_tool_arguments("echo hello", "shell")
        assert result == {"command": "echo hello"}

    def test_tool_call_repair_wraps_path_string(self):
        result = tools.repair_tool_arguments("/tmp/file.txt", "read_file")
        assert result == {"path": "/tmp/file.txt"}

    def test_tool_call_repair_braces(self):
        result = tools.repair_tool_arguments('"command": "ls"', "shell")
        assert result == {"command": "ls"}


class TestToolsets:
    def test_toolsets_core_has_tools(self):
        core = tools.resolve_toolset("core")
        assert "shell" in core
        assert "read_file" in core
        assert "write_file" in core
        assert "list_dir" in core
        assert "search_files" in core

    def test_toolsets_full_has_all(self):
        full = tools.resolve_toolset("full")
        assert "shell" in full
        assert "read_file" in full
        assert "http_get" in full
        assert "http_post" in full
        assert "delegate_to_agent" in full

    def test_toolsets_readonly(self):
        readonly = tools.resolve_toolset("readonly")
        assert "shell" not in readonly
        assert "write_file" not in readonly
        assert "read_file" in readonly
        assert "list_dir" in readonly

    def test_toolsets_invalid(self):
        assert tools.resolve_toolset("nonexistent") == []

    def test_get_tool_definitions(self):
        defs = tools.get_tool_definitions("core")
        names = {d["function"]["name"] for d in defs}
        assert "shell" in names
        assert "read_file" in names
        assert "delegate_to_agent" not in names
