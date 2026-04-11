from app.config import settings
from app.agents.state import AgentState
import json
import random
import re
import time
import requests
from cerebras.cloud.sdk import Cerebras
from typing import Any, Callable


_cerebras_client: Cerebras | None = None
ANALYZER_MAX_RETRIES_PER_PROVIDER = 2
ANALYZER_MAX_PARSE_RETRIES = 2
ANALYZER_BACKOFF_BASE_SECONDS = 0.6
ANALYZER_BACKOFF_MAX_SECONDS = 5.0


def _get_cerebras_client() -> Cerebras:
    global _cerebras_client
    if _cerebras_client is None:
        _cerebras_client = Cerebras(api_key=settings.CEREBRAS_API_KEY)
    return _cerebras_client


def _active_llm_label() -> str:
    if settings.CEREBRAS_API_KEY:
        return f"Cerebras ({settings.CEREBRAS_MODEL})"
    if settings.OPENROUTER_API_KEY:
        return f"OpenRouter ({settings.OPENROUTER_MODEL})"
    if settings.GROQ_API_KEY:
        return "Groq (llama-3.3-70b-versatile)"
    return "No LLM configured"


class AnalyzerLLMError(RuntimeError):
    def __init__(self, message: str, *, failure_type: str, providers_used: list[str], llm_failures: list[dict]) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.providers_used = providers_used
        self.llm_failures = llm_failures


def _normalize_llm_content(content: Any) -> str:
    if content is None:
        raise ValueError("LLM returned empty message content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        content = "\n".join(part for part in parts if part)
    content = str(content)
    if not content.strip():
        raise ValueError("LLM returned blank message content")
    return content


def _backoff_seconds(attempt: int) -> float:
    return min(
        ANALYZER_BACKOFF_MAX_SECONDS,
        ANALYZER_BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1)) + random.uniform(0.0, 0.35),
    )


def _classify_llm_exception(exc: Exception) -> tuple[str, bool]:
    message = str(exc).lower()

    if "rate limit" in message or "429" in message or "too many requests" in message:
        return "rate_limit", True
    if isinstance(exc, requests.Timeout) or "timeout" in message:
        return "timeout", True
    if isinstance(exc, requests.ConnectionError):
        return "connection_error", True
    if isinstance(exc, requests.HTTPError):
        if "5" in message:
            return "provider_http_error", True
        return "provider_http_error", False
    if "empty message content" in message or "blank message content" in message:
        return "empty_output", False
    return "provider_error", False


def _call_cerebras(prompt: str, temperature: float, max_tokens: int) -> str:
    response = _get_cerebras_client().chat.completions.create(
        model=settings.CEREBRAS_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_completion_tokens=max_tokens,
    )
    content = response.choices[0].message.content if response.choices else None
    return _normalize_llm_content(content)


def _call_openrouter(prompt: str, temperature: float, max_tokens: int) -> str:
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
        timeout=(15, 60),
    )
    response.raise_for_status()
    body = response.json()
    content = body.get("choices", [{}])[0].get("message", {}).get("content")
    return _normalize_llm_content(content)


def _call_groq(prompt: str, temperature: float, max_tokens: int) -> str:
    from groq import Groq

    groq_client = Groq(api_key=settings.GROQ_API_KEY)
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content if response.choices else None
    return _normalize_llm_content(content)


def _provider_sequence() -> list[tuple[str, Callable[[str, float, int], str]]]:
    providers: list[tuple[str, Callable[[str, float, int], str]]] = []
    if settings.CEREBRAS_API_KEY:
        providers.append(("cerebras", _call_cerebras))
    if settings.OPENROUTER_API_KEY:
        providers.append(("openrouter", _call_openrouter))
    if settings.GROQ_API_KEY:
        providers.append(("groq", _call_groq))
    return providers


def _chat_completion(prompt: str, temperature: float, max_tokens: int) -> dict:
    providers = _provider_sequence()
    if not providers:
        raise AnalyzerLLMError(
            "No LLM key configured. Set CEREBRAS_API_KEY, OPENROUTER_API_KEY, or GROQ_API_KEY.",
            failure_type="provider_unavailable",
            providers_used=[],
            llm_failures=[],
        )

    providers_used: list[str] = []
    llm_failures: list[dict] = []

    for provider_name, provider_fn in providers:
        if provider_name not in providers_used:
            providers_used.append(provider_name)

        for attempt in range(1, ANALYZER_MAX_RETRIES_PER_PROVIDER + 1):
            try:
                content = provider_fn(prompt, temperature, max_tokens)
                return {
                    "content": content,
                    "provider": provider_name,
                    "providers_used": providers_used,
                    "llm_failures": llm_failures,
                }
            except Exception as exc:
                failure_type, transient = _classify_llm_exception(exc)
                llm_failures.append(
                    {
                        "provider": provider_name,
                        "attempt": attempt,
                        "failure_type": failure_type,
                        "error": str(exc),
                        "transient": transient,
                    }
                )
                if transient and attempt < ANALYZER_MAX_RETRIES_PER_PROVIDER:
                    time.sleep(_backoff_seconds(attempt))
                    continue
                break

    failure_type = llm_failures[-1]["failure_type"] if llm_failures else "llm_generation_failure"
    raise AnalyzerLLMError(
        "All configured analyzer providers failed",
        failure_type=failure_type,
        providers_used=providers_used,
        llm_failures=llm_failures,
    )


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
    raw = ""
    providers_used: list[str] = []
    llm_failures: list[dict] = []

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

    strict_prompt = (
        prompt
        + "\n\nSTRICT OUTPUT RULE: Return exactly one compact JSON object and nothing else."
    )

    try:
        analysis = None
        for parse_attempt in range(1, ANALYZER_MAX_PARSE_RETRIES + 1):
            active_prompt = prompt if parse_attempt == 1 else strict_prompt
            completion = _chat_completion(active_prompt, temperature=0, max_tokens=1800)
            raw = str(completion.get("content") or "")
            providers_used = list(completion.get("providers_used") or [])
            llm_failures = list(completion.get("llm_failures") or [])
            analysis = _parse_analysis_json(raw)
            if isinstance(analysis, dict) and analysis.get("bug_type"):
                break

        if not isinstance(analysis, dict) or not analysis.get("bug_type"):
            raise ValueError("Could not parse valid analyzer JSON payload")

        print(f"[OK] Analysis complete: {analysis['bug_type']} (confidence: {analysis['confidence']})")

        return {
            "bug_type": analysis.get("bug_type", "unknown"),
            "keywords": analysis.get("keywords", []),
            "likely_files": analysis.get("likely_files", []),
            "service": analysis.get("service", "unknown"),
            "confidence": analysis.get("confidence", 0.5),
            "root_cause_hint": analysis.get("root_cause_hint", ""),
            "status": "analyzed",
            "error": None,
            "failure_type": None,
            "providers_used": providers_used,
            "llm_failures": llm_failures,
        }

    except AnalyzerLLMError as e:
        print(f"[ERROR] Analyzer provider orchestration failed: {e}")
        return {
            "error": f"Analyzer provider failure: {e}",
            "status": "failed",
            "failure_type": e.failure_type,
            "providers_used": e.providers_used,
            "llm_failures": e.llm_failures,
        }
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[ERROR] JSON parse failed: {e}\nRaw response: {raw}")
        return {
            "error": f"JSON parse error: {e}",
            "status": "failed",
            "failure_type": "invalid_format",
            "providers_used": providers_used,
            "llm_failures": llm_failures,
        }

    except Exception as e:
        print(f"[ERROR] Analysis failed: {e}")
        return {
            "error": str(e),
            "status": "failed",
            "failure_type": "llm_generation_failure",
            "providers_used": providers_used,
            "llm_failures": llm_failures,
        }


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
