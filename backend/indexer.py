import json
import sys

from app.agents.github_clone_agent import clone_repository_agent


def process_payload(payload: dict) -> dict:
    return clone_repository_agent(payload)


if __name__ == "__main__":
    input_data = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()

    try:
        payload = json.loads(input_data)
        result = process_payload(payload)
        print(json.dumps(result, indent=2))
        if result.get("status") == "error":
            sys.exit(1)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": f"Invalid input or fatal error: {str(exc)}",
                }
            )
        )
        sys.exit(1)
