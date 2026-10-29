import json
import sys
from typing import Optional

from app.core.memory import PolicyMemoryManager
from app.core.quote import quote_policy

_memory: Optional[PolicyMemoryManager] = None


def get_memory() -> PolicyMemoryManager:
    global _memory
    if _memory is None:
        _memory = PolicyMemoryManager()
    return _memory


def _tool_schema() -> dict:
    return {
        "tools": [
            {
                "name": "reprice_policy_micro_underwrite",
                "description": "Calculates behavioral dynamic risk premium for policy telemetry.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "policy_id": {"type": "string"},
                        "hard_brakes_per_100mi": {"type": "number"},
                        "night_miles_pct": {"type": "number"},
                        "speed_violations": {"type": "number"},
                        "total_miles": {"type": "number"},
                        "previous_premium": {"type": "number"},
                        "iot_moisture": {"type": "number"},
                        "weather_precip_mm": {"type": "number"},
                        "weather_wind_mph": {"type": "number"},
                        "bbox": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 4,
                            "maxItems": 4,
                        },
                    },
                    "required": ["policy_id", "previous_premium"],
                },
            },
            {
                "name": "get_policy_context",
                "description": "Recalls stored underwriting history for one policy.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "policy_id": {"type": "string"},
                        "limit": {"type": "number"},
                    },
                    "required": ["policy_id"],
                },
            },
        ]
    }


def _ok(request_id, result: dict) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    )


def handle_mcp_request(request_str: str) -> str:
    try:
        req = json.loads(request_str)
    except json.JSONDecodeError as exc:
        return _error(None, -32700, str(exc))

    request_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    try:
        if method == "tools/list":
            return _ok(request_id, _tool_schema())

        if method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                return _error(request_id, -32602, "arguments must be an object")

            if tool_name == "reprice_policy_micro_underwrite":
                quoted = quote_policy(args, get_memory())
                body = dict(quoted)
                body["calculated_risk_score"] = quoted["risk_score"]
                body["raw_calculated_premium"] = quoted["raw_premium"]
                body["regulatory_notes"] = quoted["regulatory_status"]
                body["primary_risk_drivers"] = quoted["attribution_reasons"]
                return _ok(
                    request_id,
                    {"content": [{"type": "text", "text": json.dumps(body)}]},
                )

            if tool_name == "get_policy_context":
                policy_id = args.get("policy_id")
                if not policy_id:
                    return _error(request_id, -32602, "policy_id is required")
                context = get_memory().get_policy_context(
                    str(policy_id), limit=int(args.get("limit", 3))
                )
                return _ok(
                    request_id,
                    {"content": [{"type": "text", "text": json.dumps(context)}]},
                )

            return _error(request_id, -32602, f"Unknown tool: {tool_name}")

        return _error(request_id, -32601, "Method not found")
    except ValueError as exc:
        return _error(request_id, -32602, str(exc))
    except Exception as exc:
        return _error(request_id, -32603, str(exc))


if __name__ == "__main__":
    for line in sys.stdin:
        if line.strip():
            response = handle_mcp_request(line)
            sys.stdout.write(response + "\n")
            sys.stdout.flush()
