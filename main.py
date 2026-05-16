"""FastAPI entry point with Claude integration and security pipeline."""

from __future__ import annotations

import json
import logging
from collections import deque

from fastapi import BackgroundTasks, FastAPI, Request, Response

import config
import router
from security.audit import log_action
from security.auth import authorize_sender, verify_webhook_signature
from security.rate_limiter import check_rate_limit, get_rate_limit_message
from whatsapp.client import send_message
from whatsapp.webhook import parse_incoming

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Mano Bot")

SEEN_MESSAGE_IDS: set[str] = set()
SEEN_MESSAGE_IDS_QUEUE: deque[str] = deque(maxlen=1000)


def is_duplicate(message_id: str) -> bool:
    """Return True if ``message_id`` was seen before. Records it otherwise.

    Uses a bounded FIFO so memory cannot grow unbounded; oldest IDs fall out
    after the 1000-entry capacity is reached.
    """
    if message_id in SEEN_MESSAGE_IDS:
        return True
    if len(SEEN_MESSAGE_IDS_QUEUE) == SEEN_MESSAGE_IDS_QUEUE.maxlen:
        SEEN_MESSAGE_IDS.discard(SEEN_MESSAGE_IDS_QUEUE[0])
    SEEN_MESSAGE_IDS.add(message_id)
    SEEN_MESSAGE_IDS_QUEUE.append(message_id)
    return False


@app.get("/")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/webhook")
async def verify_webhook(request: Request) -> Response:
    """Meta webhook verification handshake."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == config.WHATSAPP_VERIFY_TOKEN and challenge:
        return Response(content=challenge, media_type="text/plain", status_code=200)
    return Response(status_code=403)


@app.post("/webhook")
async def receive_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> Response:
    """Receive a WhatsApp message and run it through the security pipeline.

    Pipeline order: signature → kill switch → parse → dedup → authorize →
    rate-limit → enqueue background handler. Always returns 200 except for
    invalid signatures (403), so Meta does not retry on application-level
    rejections.
    """
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    if not verify_webhook_signature(raw, signature):
        return Response(status_code=403)

    if not config.BOT_ENABLED:
        return Response(status_code=200)

    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        logger.warning("Webhook received non-JSON body")
        return Response(status_code=200)

    parsed = parse_incoming(payload)
    if parsed is None:
        return Response(status_code=200)

    if is_duplicate(parsed["message_id"]):
        return Response(status_code=200)

    from_phone = parsed["from_phone"]
    if not authorize_sender(from_phone):
        return Response(status_code=200)

    if not check_rate_limit(from_phone):
        log_action(from_phone, "rate_limited", "over 20/10min", "blocked")
        background_tasks.add_task(send_message, from_phone, get_rate_limit_message())
        return Response(status_code=200)

    background_tasks.add_task(router.handle_message, from_phone, parsed["text"])
    return Response(status_code=200)
