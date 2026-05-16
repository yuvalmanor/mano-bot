"""FastAPI entry point.

Task 2: WhatsApp webhook — GET verification + POST (signature-verified) that
returns 200 immediately and echoes the message back in a BackgroundTask.
"""

from __future__ import annotations

import json
import logging

from fastapi import BackgroundTasks, FastAPI, Request, Response

import config
from security.auth import verify_webhook_signature
from whatsapp.client import send_message
from whatsapp.webhook import parse_incoming

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Mano Bot")


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


async def _echo_task(to_phone: str, text: str) -> None:
    """Background task: echo the text back to the sender."""
    ok = await send_message(to_phone, text)
    if not ok:
        logger.error("Echo failed for message to ****%s", to_phone[-4:])


@app.post("/webhook")
async def receive_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> Response:
    """Receive a WhatsApp message. Verify signature, then echo in background.

    Always returns 200 to Meta on parseable/authorized requests so they don't
    retry. Returns 403 only when the signature is invalid.
    """
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    if not verify_webhook_signature(raw, signature):
        return Response(status_code=403)

    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        logger.warning("Webhook received non-JSON body")
        return Response(status_code=200)

    parsed = parse_incoming(payload)
    if parsed is None:
        return Response(status_code=200)

    background_tasks.add_task(_echo_task, parsed["from_phone"], parsed["text"])
    return Response(status_code=200)
