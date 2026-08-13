from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class PermissionLevel(str, Enum):
    SAFE = "safe"
    CONFIRM = "confirm"
    DANGEROUS = "dangerous"


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None


class Tool(ABC):
    name: str
    description: str
    permission: PermissionLevel

    def get_permission(
        self,
        arguments: dict[str, Any],
    ) -> PermissionLevel:
        """
        Return the permission level required for this tool invocation.

        Most tools use their static permission level.
        Tools with dynamic risk, such as terminal execution,
        can override this method.
        """
        return self.permission

    @abstractmethod
    def schema(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        raise NotImplementedError
