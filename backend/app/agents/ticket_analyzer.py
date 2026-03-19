from app.config import settings
from app.agents.state import AgentState
import json
import re
import requests


def _active_llm_label() -> str:
    if settings.OPENROUTER_API_KEY:
        return f"OpenRouter ({settings.OPENROUTER_MODEL})"
    if settings.GROQ_API_KEY:
        return "Groq (llama-3.3-70b-versatile)"
    return "No LLM configured"


def _chat_completion(prompt: str, temperature: float, max_tokens: int) -> str:
    if settings.OPENROUTER_API_KEY:
        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": settings.OPENROUTER_APP_NAME,
        }
        if settings.OPENROUTER_HTTP_REFERER:
            headers["HTTP-Referer"] = settings.OPENROUTER_HTTP_REFERER

        payload = {
            "model": settings.OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = requests.post(
            f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        body = response.json()
        return body["choices"][0]["message"]["content"]

    if settings.GROQ_API_KEY:
        from groq import Groq

        groq_client = Groq(api_key=settings.GROQ_API_KEY)
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    raise RuntimeError("No LLM key configured. Set OPENROUTER_API_KEY or GROQ_API_KEY.")


def _parse_analysis_json(raw: str) -> dict:
    value = (raw or "").strip()
    if not value:
        raise ValueError("Empty LLM response")

    value = re.sub(r"```json|```", "", value).strip()

    try:
        return json.loads(value)
    except Exception:
        pass

    start = value.find("{")
    if start != -1:
        depth = 0
        for idx in range(start, len(value)):
            ch = value[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = value[start : idx + 1]
                    return json.loads(candidate)

    raise ValueError("Could not parse valid JSON object from analyzer output")

def ticket_analyzer_node(state: AgentState) -> AgentState:
    ticket = state["ticket"]

    print(f"\n[ANALYZE] Ticket: {ticket['jira_key']} - {ticket['summary']}")
    print(f"[LLM] Provider: {_active_llm_label()}")

    prompt = f"""You are an expert software engineer analyzing a bug ticket.

Ticket Key: {ticket['jira_key']}
Summary: {ticket['summary']}
Description: {ticket.get('description', 'No description provided')}
Priority: {ticket.get('priority', 'Medium')}

Analyze this ticket and return ONLY a JSON object with these fields:
- "bug_type": one of ["missing_dependency", "runtime_error", "logic_error", "security_vulnerability", "config_error", "null_pointer", "type_error", "syntax_error"]
- "keywords": list of 3-6 specific technical keywords
- "likely_files": list of files that likely contain the bug
- "service": one of ["python-service", "node-service", "unknown"]
- "confidence": float between 0.0 and 1.0
- "root_cause_hint": one-sentence hint about the root cause

Respond with ONLY valid JSON. No markdown, no explanation."""

    try:
        raw = _chat_completion(prompt, temperature=0, max_tokens=1800)
        analysis = _parse_analysis_json(raw)

        if not isinstance(analysis, dict) or not analysis.get("bug_type"):
            strict_prompt = (
                prompt
                + "\n\nSTRICT OUTPUT RULE: Return exactly one compact JSON object and nothing else."
            )
            raw_retry = _chat_completion(strict_prompt, temperature=0, max_tokens=1800)
            analysis = _parse_analysis_json(raw_retry)

        print(f"[OK] Analysis complete: {analysis['bug_type']} (confidence: {analysis['confidence']})")

        return {
            "bug_type": analysis.get("bug_type", "unknown"),
            "keywords": analysis.get("keywords", []),
            "likely_files": analysis.get("likely_files", []),
            "service": analysis.get("service", "unknown"),
            "confidence": analysis.get("confidence", 0.5),
            "root_cause_hint": analysis.get("root_cause_hint", ""),
            "status": "analyzed",
            "error": None
        }

    except (json.JSONDecodeError, ValueError) as e:
        print(f"[ERROR] JSON parse failed: {e}\nRaw response: {raw}")
        return {"error": f"JSON parse error: {e}", "status": "failed"}

    except Exception as e:
        print(f"[ERROR] Analysis failed: {e}")
        return {"error": str(e), "status": "failed"}


if __name__ == "__main__":
    sample_ticket = {
        "jira_key": "ST-1",
        "summary": "Python service crashes - missing flask_cors",
        "description": "The python-service fails to start. Error: ImportError: No module named 'flask_cors'. File: python-service/app/__init__.py",
        "priority": "High",
        "status": "Open"
    }

    result = ticket_analyzer_node({"ticket": sample_ticket})
    print("\nResult:")
    print(json.dumps(result, indent=2))
