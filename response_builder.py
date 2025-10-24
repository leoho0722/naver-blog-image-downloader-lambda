from typing import Any, Dict


def build_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status_code": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": body,
    }
