import os

import requests

ENABLED = str(os.getenv("WHATSAPP_ENABLED", "false")).lower() in {
    "1",
    "true",
    "t",
    "y",
    "yes",
    "ja",
    "j",
}
TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
TO = os.getenv("WHATSAPP_TO", "")


def send_whatsapp(text: str) -> bool:
    if not ENABLED:
        return False
    if not (TOKEN and PHONE_ID and TO):
        raise RuntimeError(
            "WhatsApp ENV unvollständig: WHATSAPP_TOKEN/PHONE_ID/TO"
        )

    url = f"https://graph.facebook.com/v21.0/{PHONE_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": TO,
        "type": "text",
        "text": {"body": text[:4000]},
    }
    r = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=15,
    )
    r.raise_for_status()
    return True
