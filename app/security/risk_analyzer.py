import os
import shlex
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar


class CommandRisk(str, Enum):
    SAFE = "safe"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass
class RiskAssessment:
    risk: CommandRisk
    reason: str
    command: str


class CommandRiskAnalyzer:
    DENIED_COMMANDS: ClassVar[set[str]] = {
        "sudo",
        "su",
        "shutdown",
        "reboot",
        "halt",
        "poweroff",
        "mkfs",
        "dd",
    }

    DENIED_PROGRAMS: ClassVar[set[str]] = {
        "diskutil",
    }

    CONFIRM_COMMANDS: ClassVar[set[str]] = {
        "rm",
        "rmdir",
        "mv",
        "cp",
        "chmod",
        "chown",
        "kill",
        "pkill",
        "killall",
        "npm",
        "npx",
        "pip",
        "pip3",
        "uv",
        "brew",
        "curl",
        "wget",
    }

    SAFE_COMMANDS: ClassVar[set[str]] = {
        "ls",
        "pwd",
        "whoami",
        "id",
        "date",
        "uname",
        "sw_vers",
        "which",
        "whereis",
        "cat",
        "head",
        "tail",
        "grep",
        "find",
        "file",
        "stat",
        "du",
        "df",
        "echo",
    }

    SAFE_GIT_SUBCOMMANDS: ClassVar[set[str]] = {
        "status",
        "log",
        "diff",
        "show",
        "branch",
        "tag",
        "remote",
        "rev-parse",
        "ls-files",
    }

    CONFIRM_GIT_SUBCOMMANDS: ClassVar[set[str]] = {
        "add",
        "commit",
        "push",
        "pull",
        "fetch",
        "merge",
        "rebase",
        "checkout",
        "switch",
        "restore",
        "reset",
        "clean",
        "stash",
        "clone",
        "init",
    }

    DENIED_PATHS: ClassVar[set[str]] = {
        "/",
        "/system",
        "/library",
        "/private",
        "/usr",
        "/usr/bin",
        "/usr/sbin",
        "/bin",
        "/sbin",
        "/var",
        "/etc",
        "/dev",
    }

    SHELL_OPERATORS: ClassVar[set[str]] = {
        ";",
        "&&",
        "||",
        "|",
        ">",
        ">>",
        "<",
        "<<",
        "&",
    }

    def _contains_shell_operator(self, command: str) -> bool:
        quote = None
        escaped = False
        index = 0

        while index < len(command):
            char = command[index]

            if escaped:
                escaped = False
                index += 1
                continue

            if char == "\\":
                escaped = True
                index += 1
                continue

            if quote is not None:
                if char == quote:
                    quote = None
                index += 1
                continue

            if char in {"'", '"'}:
                quote = char
                index += 1
                continue

            for operator in sorted(
                self.SHELL_OPERATORS,
                key=len,
                reverse=True,
            ):
                if command.startswith(operator, index):
                    return True

            index += 1

        return False

    def _contains_command_substitution(self, command: str) -> bool:
        quote = None
        escaped = False
        index = 0

        while index < len(command):
            char = command[index]

            if escaped:
                escaped = False
                index += 1
                continue

            if char == "\\":
                escaped = True
                index += 1
                continue

            if quote is not None:
                if char == quote:
                    quote = None
                index += 1
                continue

            if char in {"'", '"'}:
                quote = char
                index += 1
                continue

            if command.startswith("$(", index):
                return True

            if char == "`":
                return True

            index += 1

        return False

    def _is_protected_path(self, argument: str) -> bool:
        expanded = os.path.expanduser(argument)

        if not expanded.startswith("/"):
            return False

        normalized = os.path.normpath(expanded).lower()

        for protected in self.DENIED_PATHS:
            protected_normalized = os.path.normpath(protected).lower()

            if normalized == protected_normalized or normalized.startswith(
                protected_normalized + "/"
            ):
                return True

        return False

    def _has_recursive_protected_delete(
        self,
        executable: str,
        parts: list[str],
    ) -> bool:
        if executable not in {"rm", "rmdir"}:
            return False

        recursive = False

        for argument in parts[1:]:
            if argument.startswith("-"):
                options = argument.lstrip("-")
                if "r" in options:
                    recursive = True

        if not recursive:
            return False

        for argument in parts[1:]:
            if argument.startswith("-"):
                continue

            if self._is_protected_path(argument):
                return True

        return False

    def analyze(self, command: str) -> RiskAssessment:
        command = command.strip()

        if not command:
            return RiskAssessment(
                risk=CommandRisk.DENY,
                reason="Empty command.",
                command=command,
            )

        if self._contains_shell_operator(command):
            return RiskAssessment(
                risk=CommandRisk.DENY,
                reason=("Shell operators and command chaining are not permitted."),
                command=command,
            )

        if self._contains_command_substitution(command):
            return RiskAssessment(
                risk=CommandRisk.DENY,
                reason="Command substitution is not permitted.",
                command=command,
            )

        try:
            parts = shlex.split(command)
        except ValueError as exc:
            return RiskAssessment(
                risk=CommandRisk.DENY,
                reason=f"Invalid command syntax: {exc}",
                command=command,
            )

        if not parts:
            return RiskAssessment(
                risk=CommandRisk.DENY,
                reason="Empty command.",
                command=command,
            )

        executable = os.path.basename(parts[0]).lower()

        if executable in self.DENIED_COMMANDS:
            return RiskAssessment(
                risk=CommandRisk.DENY,
                reason=(f"'{executable}' is blocked by the terminal security policy."),
                command=command,
            )

        if executable in self.DENIED_PROGRAMS:
            return RiskAssessment(
                risk=CommandRisk.DENY,
                reason=(
                    f"'{executable}' can modify disks or system storage and is blocked."
                ),
                command=command,
            )

        if self._has_recursive_protected_delete(
            executable,
            parts,
        ):
            return RiskAssessment(
                risk=CommandRisk.DENY,
                reason=(
                    "Recursive deletion targeting a protected system path is blocked."
                ),
                command=command,
            )

        for argument in parts[1:]:
            if argument.startswith("-"):
                continue

            if self._is_protected_path(argument):
                return RiskAssessment(
                    risk=CommandRisk.DENY,
                    reason=(
                        f"Access to protected system path '{argument}' is blocked."
                    ),
                    command=command,
                )

        if executable == "git":
            if len(parts) < 2:
                return RiskAssessment(
                    risk=CommandRisk.CONFIRM,
                    reason="No git subcommand was specified.",
                    command=command,
                )

            subcommand = parts[1].lower()

            if subcommand in self.SAFE_GIT_SUBCOMMANDS:
                return RiskAssessment(
                    risk=CommandRisk.SAFE,
                    reason=(f"'git {subcommand}' is a read-only git operation."),
                    command=command,
                )

            if subcommand in self.CONFIRM_GIT_SUBCOMMANDS:
                return RiskAssessment(
                    risk=CommandRisk.CONFIRM,
                    reason=(f"'git {subcommand}' can modify repository state."),
                    command=command,
                )

            return RiskAssessment(
                risk=CommandRisk.CONFIRM,
                reason=(
                    f"Unknown git operation '{subcommand}'. "
                    "Explicit confirmation is required."
                ),
                command=command,
            )

        if executable in self.CONFIRM_COMMANDS:
            return RiskAssessment(
                risk=CommandRisk.CONFIRM,
                reason=(f"'{executable}' can modify the system or files."),
                command=command,
            )

        if executable in self.SAFE_COMMANDS:
            if executable == "echo" and len(parts) > 1:
                return RiskAssessment(
                    risk=CommandRisk.CONFIRM,
                    reason="Echo contains user-supplied arguments.",
                    command=command,
                )

            return RiskAssessment(
                risk=CommandRisk.SAFE,
                reason="Read-only or informational command.",
                command=command,
            )

        return RiskAssessment(
            risk=CommandRisk.CONFIRM,
            reason=("Unknown command. Explicit user confirmation is required."),
            command=command,
        )