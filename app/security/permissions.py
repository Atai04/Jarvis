from dataclasses import dataclass
from enum import Enum


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass
class PermissionRequest:
    tool_name: str
    description: str
    risk_level: str


class PermissionEngine:
    def evaluate(
        self,
        tool_name: str,
        permission_level: str,
        description: str,
    ) -> PermissionDecision:

        if permission_level == "safe":
            return PermissionDecision.ALLOW

        if permission_level == "confirm":
            return PermissionDecision.CONFIRM

        if permission_level == "dangerous":
            return PermissionDecision.DENY

        return PermissionDecision.DENY

    def request_confirmation(
        self,
        request: PermissionRequest,
    ) -> bool:

        print()
        print("========================================")
        print("        JARVIS PERMISSION REQUEST")
        print("========================================")
        print()
        print(f"Tool:   {request.tool_name}")
        print(f"Action: {request.description}")
        print(f"Risk:   {request.risk_level}")
        print()

        answer = input("Allow this action? [y/N]: ").strip().lower()

        return answer in {"y", "yes"}
