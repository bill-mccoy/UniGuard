from __future__ import annotations
import os
import logging
import asyncio
import base64
import time
import random
from typing import Optional, List, Dict, Any, Union

logger = logging.getLogger("uniguard.emailer")

# --- Configuration from environment ---
MAILJET_API_KEY = os.getenv("MAILJET_API_KEY")
MAILJET_API_SECRET = os.getenv("MAILJET_API_SECRET")
MAILJET_FROM_EMAIL = os.getenv("MAILJET_FROM_EMAIL", os.getenv("EMAIL_FROM", "no-reply@example.com"))
MAILJET_FROM_NAME = os.getenv("MAILJET_FROM_NAME", "Discord Bot")

# Behavior tuning
_MAX_MESSAGES_PER_BATCH = int(os.getenv("MAILJET_MAX_BATCH", 50))
_DEFAULT_RETRIES = int(os.getenv("MAILJET_RETRIES", 4))
_BACKOFF_BASE = float(os.getenv("MAILJET_BACKOFF_BASE", 1.0))   # seconds
_BACKOFF_FACTOR = float(os.getenv("MAILJET_BACKOFF_FACTOR", 2.0))
_JITTER_PCT = float(os.getenv("MAILJET_JITTER_PCT", 0.3))      # percent of backoff to jitter


# Lazy client holder
_mailjet_client = None

def _init_mailjet_client() -> Optional[Any]:
    """Lazy-initialize and return the Mailjet client instance.
    Returns None if credentials are missing or import fails.
    """
    global _mailjet_client
    if _mailjet_client is not None:
        return _mailjet_client

    if not (MAILJET_API_KEY and MAILJET_API_SECRET):
        logger.error("[emailer] MAILJET_API_KEY / MAILJET_API_SECRET not set in environment.")
        return None

    try:
        # import inside function to avoid hard dependency at import-time
        from mailjet_rest import Client
    except Exception as e:
        logger.exception(f"[emailer] Could not import mailjet_rest: {e}")
        return None

    try:
        _mailjet_client = Client(auth=(MAILJET_API_KEY, MAILJET_API_SECRET), version="v3.1")
        logger.info("[emailer] Mailjet client initialized.")
        return _mailjet_client
    except Exception as e:
        logger.exception(f"[emailer] Error initializing Mailjet client: {e}")
        _mailjet_client = None
        return None


# --- Helpers for templates / attachments ---
def _render_verification_html(code: str, recipient_name: Optional[str] = None) -> str:
    name = f" {recipient_name}" if recipient_name else ""
    return f"""
    <html>
      <body style="font-family: Arial, sans-serif; color:#111;">
        <p>Hola{name},</p>
        <p>Tu código de verificación es:</p>
        <div style="display:inline-block;padding:12px;border-radius:6px;background:#f6f8fa;">
          <strong style="font-size:18px;letter-spacing:2px;">{code}</strong>
        </div>
        <p>Ingresa este código en el bot de Discord para completar la verificación.</p>
        <p>Si no solicitaste este correo, ignóralo.</p>
        <br/>
        <small>Atentamente,<br/>Equipo</small>
      </body>
    </html>
    """

def _render_verification_text(code: str, recipient_name: Optional[str] = None) -> str:
    name = f" {recipient_name}" if recipient_name else ""
    return (
        f"Hola{name},\n\n"
        f"Tu código de verificación es: {code}\n\n"
        "Ingresa este código en el bot de Discord para completar la verificación.\n\n"
        "Si no solicitaste este correo, ignóralo.\n\n"
        "Saludos,\nEquipo"
    )

def _prepare_attachments(attachments: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, str]]]:
    """
    Accept attachments: list of dicts with keys:
      - filename: str
      - content: bytes or str (if str, will be encoded to bytes then base64)
      - mime_type: optional
    Returns Mailjet 'Attachments' list or None.
    """
    if not attachments:
        return None
    out = []
    for item in attachments:
        filename = item.get("filename")
        content = item.get("content")
        mime_type = item.get("mime_type", "application/octet-stream")
        if filename is None or content is None:
            continue
        if isinstance(content, str):
            content_bytes = content.encode()
        else:
            content_bytes = content
        try:
            b64 = base64.b64encode(content_bytes).decode()
            out.append({
                "ContentType": mime_type,
                "Filename": filename,
                "Base64Content": b64
            })
        except Exception as e:
            logger.warning(f"[emailer] Skipping attachment {filename}: {e}")
    return out or None


# --- Core sync worker (runs in thread) ---
def _send_messages_sync(client, messages: List[Dict[str, Any]], retries: int = _DEFAULT_RETRIES) -> Dict[str, Any]:
    """
    Synchronous worker that sends the provided messages (Mailjet format).
    Handles retries/backoff for 429 and 5xx.
    Returns dict: { "success": bool, "batches": [ {status_code, body, attempt} ... ] }
    """
    result = {"success": False, "batches": []}
    if client is None:
        logger.error("[emailer] _send_messages_sync called with no client")
        return result

    # Split into batches
    batches = [messages[i:i + _MAX_MESSAGES_PER_BATCH] for i in range(0, len(messages), _MAX_MESSAGES_PER_BATCH)]

    for batch in batches:
        payload = {"Messages": batch}
        attempt = 0
        while attempt < retries:
            attempt += 1
            try:
                response = client.send.create(data=payload)
                status = getattr(response, "status_code", None)
                try:
                    body = response.json()
                except Exception as e:
                    logger.debug(f"[emailer] Response.json() failed: {e}")
                    body = None

                result["batches"].append({"attempt": attempt, "status_code": status, "body": body})

                # success case
                if status in (200, 201):
                    result["success"] = True
                    break

                # rate limit
                if status == 429:
                    backoff = _BACKOFF_BASE * (_BACKOFF_FACTOR ** (attempt - 1))
                    jitter = backoff * _JITTER_PCT * random.random()
                    sleep_time = backoff + jitter
                    logger.warning(f"[emailer] Mailjet 429 received. Backing off {sleep_time:.2f}s (attempt {attempt}).")
                    time.sleep(sleep_time)
                    continue

                # server errors (5xx) -> retry
                if status and 500 <= status < 600:
                    backoff = _BACKOFF_BASE * (_BACKOFF_FACTOR ** (attempt - 1))
                    logger.warning(f"[emailer] Mailjet server error {status}. Retrying in {backoff:.2f}s (attempt {attempt}).")
                    time.sleep(backoff)
                    continue

                # other errors -> don't retry (collect body for diagnostics)
                logger.error(f"[emailer] Non-retriable Mailjet response: status={status}, body={body}")
                break

            except Exception as e:
                # unexpected exception from client library or network -> retry a bit
                backoff = _BACKOFF_BASE * (_BACKOFF_FACTOR ** (attempt - 1))
                logger.exception(f"[emailer] Exception sending batch (attempt {attempt}): {e}. Retrying in {backoff:.2f}s.")
                time.sleep(backoff)
                continue
        else:
            # ran out of retries for this batch
            logger.error("[emailer] Exhausted retries for a batch.")
            # continue to next batch (result.success might remain False)
            continue

    return result


# --- Async public API ---

async def send_email_async(
    to_emails: Union[str, List[str]],
    subject: str,
    html_content: Optional[str] = None,
    text_content: Optional[str] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    retries: int = _DEFAULT_RETRIES
) -> Dict[str, Any]:
    """
    Send one or multiple emails via Mailjet.
    - to_emails: single email or list of emails (each recipient receives a private message)
    - attachments: list of dicts {filename, content (bytes|str), mime_type}
    Returns: dict with 'success' bool and 'batches' detail.
    """
    client = _init_mailjet_client()
    if client is None:
        return {"success": False, "error": "mailjet client not initialized"}

    if isinstance(to_emails, str):
        recipients = [to_emails]
    else:
        # deduplicate while preserving order
        seen = set()
        recipients = []
        for e in to_emails:
            if e and e not in seen:
                seen.add(e)
                recipients.append(e)

    if not recipients:
        return {"success": False, "error": "no recipients provided"}

    from_email = from_email or MAILJET_FROM_EMAIL
    from_name = from_name or MAILJET_FROM_NAME

    mj_attachments = _prepare_attachments(attachments)

    messages = []
    for r in recipients:
        msg: Dict[str, Any] = {
            "From": {"Email": from_email, "Name": from_name},
            "To": [{"Email": r}],
            "Subject": subject
        }
        if text_content:
            msg["TextPart"] = text_content
        if html_content:
            msg["HTMLPart"] = html_content
        if cc:
            msg["Cc"] = [{"Email": c} for c in cc]
        if bcc:
            msg["Bcc"] = [{"Email": b} for b in bcc]
        if mj_attachments:
            msg["Attachments"] = mj_attachments
        messages.append(msg)

    # run blocking send in thread
    try:
        result = await asyncio.to_thread(_send_messages_sync, client, messages, retries)
        if not result.get("success"):
            logger.warning(f"[emailer] Mailjet send_email_async returned unsuccessful: {result}")
        return result
    except Exception as e:
        logger.exception(f"[emailer] Unexpected exception in send_email_async: {e}")
        return {"success": False, "error": str(e)}


async def send_verification_email_async(
    to_email: str,
    code: str,
    recipient_name: Optional[str] = None,
    subject: Optional[str] = None,
    retries: int = _DEFAULT_RETRIES
) -> Dict[str, Any]:
    """
    Convenience helper to send a verification email (default template).
    Returns the same structured dict as send_email_async.
    """
    subject = subject or "Código de verificación"
    html = _render_verification_html(code, recipient_name)
    text = _render_verification_text(code, recipient_name)
    return await send_email_async(
        to_emails=to_email,
        subject=subject,
        html_content=html,
        text_content=text,
        retries=retries
    )


# Quick test helper when running file directly
if __name__ == "__main__":
    import argparse, asyncio, logging
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", help="Recipient email (env TEST_MAIL_TO if omitted)", default=os.getenv("TEST_MAIL_TO"))
    parser.add_argument("--code", help="Code to send", default="TEST123")
    args = parser.parse_args()

    if not args.to:
        logger.error("No recipient provided (use --to or TEST_MAIL_TO env).")
    else:
        async def _t():
            res = await send_verification_email_async(args.to, args.code, recipient_name="Tester")
            logger.info(f"Result: {res}")
        asyncio.run(_t())
