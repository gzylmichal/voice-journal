"""pipeline/notify.py — ntfy.sh push notification transport.

Iron rule: a notify failure NEVER raises — log warning and return False.
The pipeline must work identically with notifications disabled (NTFY_TOPIC empty).
"""

import logging
import requests
from pipeline import config

logger = logging.getLogger(__name__)


def send_notification(message, title="Voice Journal", priority="default"):
    """Send a push notification via ntfy.sh.

    Returns True on success, False if disabled or on any error.
    """
    if not config.NTFY_TOPIC:
        return False
    url = f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}"
    try:
        resp = requests.post(
            url,
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority},
            timeout=10,
        )
        return resp.status_code < 300
    except Exception as exc:
        logger.warning("ntfy notification failed: %s", exc)
        return False
