import pytest

from app.security.risk_analyzer import (
    CommandRisk,
    CommandRiskAnalyzer,
)


@pytest.fixture
def analyzer():
    return CommandRiskAnalyzer()


@pytest.mark.parametrize(
    "command",
    [
        "ls ~/jarvis",
        "pwd",
        "cat README.md",
        "find ~/jarvis -name '*.py'",
        "git status",
        "git log",
        "git diff",
        "git branch",
    ],
)
def test_safe_commands(analyzer, command):
    result = analyzer.analyze(command)
    assert result.risk == CommandRisk.SAFE


@pytest.mark.parametrize(
    "command",
    [
        "rm ~/jarvis/test.txt",
        "mkdir ~/jarvis/test",
        "npm install",
        "pip install requests",
        "uv add httpx",
        "git add .",
        "git commit -m test",
        "git push",
        "git reset --hard HEAD",
    ],
)
def test_confirm_commands(analyzer, command):
    result = analyzer.analyze(command)
    assert result.risk == CommandRisk.CONFIRM


@pytest.mark.parametrize(
    "command",
    [
        "sudo rm -rf /",
        "sudo ls",
        "shutdown -h now",
        "reboot",
        "diskutil eraseDisk",
        "rm -rf /",
        "rm /usr/bin/test",
        "ls; rm -rf /",
        "ls && rm -rf /",
        "ls || rm -rf /",
        "ls | rm -rf /",
        "echo test > file",
        "echo test >> file",
        "sleep 10 &",
        "echo $(whoami)",
        "echo `whoami`",
    ],
)
def test_denied_commands(analyzer, command):
    result = analyzer.analyze(command)
    assert result.risk == CommandRisk.DENY


def test_unknown_command_requires_confirmation(analyzer):
    result = analyzer.analyze("some_unknown_command")

    assert result.risk == CommandRisk.CONFIRM


def test_quoted_shell_characters_are_not_shell_operators(analyzer):
    result = analyzer.analyze("echo ';'")

    assert result.risk == CommandRisk.CONFIRM
