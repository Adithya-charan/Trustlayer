"""Command router: turns a user message into at most one approved tool call.

Flow: message -> Groq picks a tool by name -> we validate name, arguments and the caller's permission ->
read-only tools run; consequential tools return a signed, single-use confirmation instead of running.
Results shown to the user come only from the backend handlers, never from model text."""
import datetime as dt
import json
import logging
import uuid

import jwt
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.assistant.tools import TOOLS, Ctx, Tool, permitted, tools_for
from app.audit import logger as audit
from app.core.config import get_settings
from app.core.security import Actor, limiter

log = logging.getLogger("trustlayer.assistant")
CONFIRM_TTL = dt.timedelta(minutes=5)
_used_confirmations: dict[str, float] = {}  # jti -> expiry; single-process prototype, like the rate limiter

SYSTEM_PROMPT = (
    "You are the TrustLayer operator assistant inside a data-privacy dashboard. You can only help by calling one of the provided tools; "
    "you cannot run SQL, shell commands or workflows, and you never reveal or guess data values. Pick the single best tool for the request, "
    "or reply briefly in plain text if no tool fits. For any question about the uploaded dataset or its PII findings (counts, categories, columns, risk, why something is sensitive, a summary) always call ask_about_dataset, never explain_page. For questions about policy changes, access history, denied attempts, a user's activity, or why something was allowed, masked or denied, call recent_policy_changes or access_history; for a follow-up about the previous answer call followup_on_last_answer. Set limit to the number the user asked for. Keep replies under 40 words. The user's role is '{role}' and they are on the '{page}' page."
)


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def get_llm_client():
    """The single place the Groq key is read. Tests replace this function; the key is never logged or returned."""
    key = get_settings().groq_api_key
    if not key:
        raise _error(503, "assistant_not_configured", "The AI assistant is not configured yet. Ask an administrator to set GROQ_API_KEY on the server.")
    from groq import Groq  # imported lazily so the app starts even if the optional SDK is absent

    return Groq(api_key=key, timeout=get_settings().groq_timeout_seconds)


def is_configured() -> bool:
    return bool(get_settings().groq_api_key)


def _clean_history(history: list[dict]) -> list[dict]:
    out = []
    for h in history[-6:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            out.append({"role": h["role"], "content": h["content"][:500]})
    return out


def _llm_choose(actor: Actor, message: str, page: str, history: list[dict]):
    client = get_llm_client()
    visible = tools_for(actor)
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(role=actor.role, page=page)}, *_clean_history(history), {"role": "user", "content": message}]
    try:
        resp = client.chat.completions.create(
            model=get_settings().groq_model, messages=messages, tools=[t.schema() for t in visible], tool_choice="auto",
            temperature=0, max_tokens=300,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - map provider failures without echoing provider text (it could carry request details)
        status = getattr(exc, "status_code", None)
        log.warning("llm call failed: %s status=%s", type(exc).__name__, status)
        if status == 429:
            raise _error(429, "assistant_rate_limited", "The AI service is busy (rate limited). Please wait a moment and try again.") from None
        if status in (401, 403):
            raise _error(503, "assistant_not_configured", "The AI service rejected the server's credentials. Ask an administrator to check GROQ_API_KEY.") from None
        raise _error(502, "assistant_unavailable", "The AI service is unavailable right now. Please try again.") from None
    return resp.choices[0].message


def _audit(db: Session, actor: Actor, tool: str, decision: str, reason: str) -> None:
    audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=actor.role, operation="assistant_tool", purpose="assistant",
                 fields={}, policy=f"assistant/{tool}", decision=decision, reason=reason)


def _validate(tool_name: str, raw_args: str | dict | None, actor: Actor) -> tuple[Tool, object]:
    tool = TOOLS.get(tool_name)
    if tool is None:
        raise ValueError("unknown tool")
    if not tool.available():
        raise LookupError("tool not configured")
    try:
        data = json.loads(raw_args) if isinstance(raw_args, str) and raw_args.strip() else (raw_args or {})
        if not isinstance(data, dict):
            raise ValueError("arguments must be an object")
        args = tool.args.model_validate(data)
    except (ValidationError, ValueError, json.JSONDecodeError):
        raise ValueError("invalid arguments") from None
    if not permitted(tool, actor, args):
        raise PermissionError("not permitted")
    return tool, args


def spoken_summary(reply: str, result: dict | None, confirmation: dict | None) -> str:
    """The line that is spoken aloud. Built from the backend's own result, never from model text, so it cannot claim more than happened."""
    if confirmation:
        return f"{confirmation['summary']} Please confirm on screen."
    if not result:
        return reply
    k = result.get("kind")
    if k == "security_events":
        sev = f"{result['severity'].lower()}-severity " if result.get("severity") else ""
        n = result["total"]
        return f"I found {n} {sev}security event{'s' if n != 1 else ''}." + (f" Showing the {len(result['items'])} most recent." if n else "")
    if k == "scans":
        return f"Here are the {len(result['items'])} most recent scans." if result["items"] else "No scans have been run yet."
    if k == "scan_started":
        s = result["scan"]
        return f"The scan finished with status {s['status'].lower()}. {s['sensitive_found']} of {s['fields_scanned']} fields were sensitive."
    if k == "automation":
        return f"Here is the status of the {len(result['workflows'])} automation workflows."
    if k == "workflow_triggered":
        return f"n8n accepted the request to start the {result['name']}. I will show its result when it reports back."
    if k == "audit_answer":
        return result["reply"].splitlines()[0] if result.get("reply") else reply
    if k == "page_help":
        return result["text"]
    return reply


def _make_confirmation(actor: Actor, tool: Tool, args) -> dict:
    exp = dt.datetime.now(dt.timezone.utc) + CONFIRM_TTL
    token = jwt.encode({"sub": actor.username, "purpose": "assistant-confirm", "tool": tool.name, "args": args.model_dump(), "jti": str(uuid.uuid4()), "exp": exp},
                       get_settings().jwt_secret, algorithm="HS256")
    return {"token": token, "tool": tool.name, "summary": tool.confirm_text or f"Run {tool.name}?", "expires_at": exp}


def _out(reply: str, result: dict | None = None, confirmation: dict | None = None, **extra) -> dict:
    return {"reply": reply, "result": result, "confirmation": confirmation, "spoken": spoken_summary(reply, result, confirmation), **extra}


def handle_chat(db: Session, actor: Actor, message: str, page: str, history: list[dict]) -> dict:
    limiter.check(f"assistant:{actor.username}", 20, 60)
    msg = _llm_choose(actor, message, page, history)
    calls = getattr(msg, "tool_calls", None) or []
    text = (getattr(msg, "content", None) or "").strip()[:600]
    if not calls:
        return _out(text or "I can show security events, scans and automation status, explain a page, open a page, or start a scan. What would you like?")
    call = calls[0]  # at most one action per message
    try:
        tool, args = _validate(call.function.name, call.function.arguments, actor)
    except PermissionError:
        _audit(db, actor, str(call.function.name)[:40], "DENY", "assistant tool request refused: not permitted for role")
        return _out("Your role is not permitted to do that, so I did not run it.", refused=True)
    except LookupError:
        _audit(db, actor, str(call.function.name)[:40], "DENY", "assistant tool request refused: capability not configured")
        return _out("That capability is not configured on the server yet, so I did not run it.", refused=True)
    except ValueError:
        _audit(db, actor, str(call.function.name)[:40], "DENY", "assistant tool request refused: not an approved tool or invalid arguments")
        return _out("I can only use approved TrustLayer tools, and that request was not one of them, so I did not run it.", refused=True)
    if tool.consequential:
        _audit(db, actor, tool.name, "ALLOW", "assistant proposed a consequential action; awaiting user confirmation")
        return _out(text or tool.confirm_text, confirmation=_make_confirmation(actor, tool, args))
    result = tool.run(Ctx(db, actor), args)
    _audit(db, actor, tool.name, "ALLOW", f"assistant ran read-only tool {tool.name}")
    reply = result.get("reply") if isinstance(result, dict) and result.get("kind") in ("dataset_answer", "audit_answer") else None  # backend-computed facts, never the model's wording
    return _out(reply or text or "Here is what I found.", result=result)


def handle_confirm(db: Session, actor: Actor, token: str) -> dict:
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        raise _error(400, "confirmation_invalid", "That confirmation is invalid or has expired. Ask me again.") from None
    if claims.get("purpose") != "assistant-confirm" or claims.get("sub") != actor.username:
        raise _error(403, "confirmation_invalid", "That confirmation does not belong to you.")
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    for k in [k for k, v in _used_confirmations.items() if v < now]:
        _used_confirmations.pop(k, None)
    jti = claims.get("jti", "")
    if jti in _used_confirmations:
        raise _error(409, "confirmation_used", "That confirmation was already used.")
    try:
        tool, args = _validate(claims.get("tool", ""), claims.get("args"), actor)  # re-checked: role may have changed since the proposal
    except LookupError:
        raise _error(503, "workflow_not_configured", "That capability is not configured on the server any more.") from None
    except (PermissionError, ValueError):
        raise _error(403, "confirmation_invalid", "That action is no longer permitted.") from None
    if not tool.consequential:
        raise _error(400, "confirmation_invalid", "That action does not need confirmation.")
    _used_confirmations[jti] = float(claims.get("exp", now))
    result = tool.run(Ctx(db, actor), args)
    _audit(db, actor, tool.name, "ALLOW", f"assistant ran confirmed action {tool.name}")
    return _out(result.get("note") or "Done. This is the status the server reported.", result=result)
