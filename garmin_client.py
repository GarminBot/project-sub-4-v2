"""
Haelt eine einzige, wiederverwendete Garmin-Session fuer die Lebensdauer des Prozesses.
Loggt bei Bedarf automatisch neu ein (z.B. nach Cold-Start auf Render).
"""

import logging
import os
import threading

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

logger = logging.getLogger("garmin_client")

_client: Garmin | None = None
_lock = threading.Lock()


def _do_login() -> Garmin:
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError("GARMIN_EMAIL / GARMIN_PASSWORD sind nicht als Env-Variablen gesetzt.")

    client = Garmin(email=email, password=password)
    client.login()
    logger.info("Garmin-Login erfolgreich.")
    return client


def get_client() -> Garmin:
    global _client
    with _lock:
        if _client is None:
            _client = _do_login()
        return _client


def call_with_relogin(fn_name: str, *args, **kwargs):
    global _client
    client = get_client()
    fn = getattr(client, fn_name)
    try:
        return fn(*args, **kwargs)
    except (GarminConnectAuthenticationError, GarminConnectConnectionError) as e:
        logger.warning(f"Garmin-Aufruf fehlgeschlagen ({e}), versuche Re-Login...")
        with _lock:
            _client = _do_login()
        fn = getattr(_client, fn_name)
        return fn(*args, **kwargs)
    except GarminConnectTooManyRequestsError as e:
        raise RuntimeError(f"Garmin Rate-Limit erreicht: {e}")
