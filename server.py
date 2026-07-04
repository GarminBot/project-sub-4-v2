"""
Garmin MCP Server
==================

Remote MCP-Server (Streamable HTTP) fuer Garmin Connect, absichert per
selbst gehostetem OAuth-2.1-Mini-Server (siehe oauth_provider.py).

Wird als "Custom Connector" in Claude (Settings -> Connectors) eingebunden.
"""

import asyncio
import datetime
import os

from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP

from garmin_client import call_with_relogin, get_client
from oauth_provider import GarminAuthProvider
from workouts import build_custom_workout, build_easy_run_workout, build_interval_workout, upload_and_schedule

ISSUER_URL = os.environ["ISSUER_URL"]  # z.B. https://garmin-mcp.onrender.com (OHNE trailing slash)
LOGIN_PASSWORD = os.environ["MCP_LOGIN_PASSWORD"]

auth_provider = GarminAuthProvider(issuer_url=ISSUER_URL, password=LOGIN_PASSWORD)

mcp = FastMCP(
    "garmin_mcp",
    auth_server_provider=auth_provider,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(ISSUER_URL),
        resource_server_url=AnyHttpUrl(ISSUER_URL),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["garmin"],
            default_scopes=["garmin"],
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=["garmin"],
    ),
)


def _daterange(days: int) -> tuple[str, str]:
    today = datetime.date.today()
    return (today - datetime.timedelta(days=days)).isoformat(), today.isoformat()


# ---------------------------------------------------------------------------
# Tools: Lesen
# ---------------------------------------------------------------------------

@mcp.tool(
    annotations={"title": "Get Activities", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def get_activities(days: int = 28) -> dict:
    """Laufaktivitaeten (und andere Sportarten) der letzten N Tage von Garmin Connect.

    Args:
        days: Anzahl Tage zurueck (Default 28)

    Returns:
        Liste von Aktivitaets-Objekten: Distanz, Dauer, Durchschnitts-/Max-HF,
        Pace, Kadenz, Hoehenmeter, aerober/anaerober Trainingseffekt, VO2max.
    """
    start, end = _daterange(days)
    return await asyncio.to_thread(call_with_relogin, "get_activities_by_date", start, end)


@mcp.tool(
    annotations={"title": "Get Training Status", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def get_training_status() -> dict:
    """Aktueller Garmin Trainingsstatus: VO2max, Fitnessalter, Weekly Training Load,
    Load Tunnel (optimaler Belastungskorridor) und Trend-Indikatoren."""
    today = datetime.date.today().isoformat()
    return await asyncio.to_thread(call_with_relogin, "get_training_status", today)


@mcp.tool(
    annotations={"title": "Get Training Readiness", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def get_training_readiness() -> dict:
    """Garmin Training-Readiness-Score fuer heute (kombiniert Erholung, Schlaf, HRV, Load)."""
    today = datetime.date.today().isoformat()
    return await asyncio.to_thread(call_with_relogin, "get_training_readiness", today)


@mcp.tool(
    annotations={"title": "Get Race Predictions", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def get_race_predictions() -> dict:
    """Garmins vorhergesagte Wettkampfzeiten (5km, 10km, Halbmarathon, Marathon) basierend auf aktueller Fitness."""
    return await asyncio.to_thread(call_with_relogin, "get_race_predictions")


@mcp.tool(
    annotations={"title": "Get Sleep Data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def get_sleep(date: str | None = None) -> dict:
    """Schlafdaten fuer ein bestimmtes Datum (Default: heute).

    Args:
        date: Datum im Format YYYY-MM-DD, optional (Default heute)
    """
    date = date or datetime.date.today().isoformat()
    return await asyncio.to_thread(call_with_relogin, "get_sleep_data", date)


@mcp.tool(
    annotations={"title": "Get HRV", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def get_hrv(date: str | None = None) -> dict:
    """Herzfrequenzvariabilitaet (HRV) der letzten Nacht fuer ein bestimmtes Datum (Default: heute)."""
    date = date or datetime.date.today().isoformat()
    return await asyncio.to_thread(call_with_relogin, "get_hrv_data", date)


@mcp.tool(
    annotations={"title": "Get Body Battery", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def get_body_battery(days: int = 7) -> dict:
    """Body-Battery-Verlauf (Energie-Level) der letzten N Tage."""
    start, end = _daterange(days)
    return await asyncio.to_thread(call_with_relogin, "get_body_battery", start, end)


@mcp.tool(
    annotations={"title": "Get Stress", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def get_stress(date: str | None = None) -> dict:
    """Stress-Werte (All-Day-Stress) fuer ein bestimmtes Datum (Default: heute)."""
    date = date or datetime.date.today().isoformat()
    return await asyncio.to_thread(call_with_relogin, "get_all_day_stress", date)


@mcp.tool(
    annotations={"title": "Get Scheduled Workouts", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def get_scheduled_workouts(year: int | None = None, month: int | None = None) -> dict:
    """Bereits geplante/eingetragene Workouts fuer einen Monat (Default: aktueller Monat)."""
    today = datetime.date.today()
    return await asyncio.to_thread(call_with_relogin, "get_scheduled_workouts", year or today.year, month or today.month)


@mcp.tool(
    annotations={"title": "Get Full Export", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def get_full_export(days: int = 28) -> dict:
    """Kombinierter Export: Aktivitaeten, Trainingsstatus, Readiness, Race Predictions,
    HRV, Schlaf, Body Battery und Stress in einem Aufruf. Praktisch fuer die
    woechentliche Trainingsplan-Analyse, statt 8 einzelne Tools aufzurufen.

    Args:
        days: Zeitraum in Tagen fuer Aktivitaeten/Body-Battery (Default 28)
    """
    start, end = _daterange(days)
    today = datetime.date.today().isoformat()

    def safe(fn_name, *args):
        try:
            return call_with_relogin(fn_name, *args)
        except Exception as e:
            return {"error": str(e)}

    def _do():
        return {
            "export_range": {"start": start, "end": end},
            "activities": safe("get_activities_by_date", start, end),
            "training_status": safe("get_training_status", today),
            "training_readiness": safe("get_training_readiness", today),
            "race_predictions": safe("get_race_predictions"),
            "hrv_last_night": safe("get_hrv_data", today),
            "sleep_last_night": safe("get_sleep_data", today),
            "body_battery": safe("get_body_battery", start, end),
            "all_day_stress": safe("get_all_day_stress", today),
        }

    return await asyncio.to_thread(_do)


# ---------------------------------------------------------------------------
# Tools: Schreiben (Workouts erstellen/planen/loeschen)
# ---------------------------------------------------------------------------

@mcp.tool(
    annotations={"title": "Create Interval Workout", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
)
async def create_interval_workout(
    name: str = "Intervalltraining",
    warmup_secs: int = 600,
    interval_meters: float = 800.0,
    interval_count: int = 6,
    recovery_secs: int = 120,
    cooldown_secs: int = 600,
    schedule_date: str | None = None,
) -> dict:
    """Erstellt ein strukturiertes Intervall-Workout (Warmup - N x Intervall/Erholung -
    Cooldown) und laedt es zu Garmin Connect hoch. Optional wird es direkt auf ein
    Datum eingeplant, damit es automatisch aufs Geraet synct.

    Args:
        name: Name des Workouts, z.B. "6x800m Intervalle"
        warmup_secs: Warmup-Dauer in Sekunden
        interval_meters: Distanz pro Intervall in Metern
        interval_count: Anzahl Wiederholungen
        recovery_secs: Erholungsdauer zwischen Intervallen in Sekunden
        cooldown_secs: Cooldown-Dauer in Sekunden
        schedule_date: Optional, Datum im Format YYYY-MM-DD zum Einplanen
    """

    def _do():
        workout = build_interval_workout(name, warmup_secs, interval_meters, interval_count, recovery_secs, cooldown_secs)
        return upload_and_schedule(get_client(), workout, schedule_date)

    return await asyncio.to_thread(_do)


@mcp.tool(
    annotations={"title": "Create Easy Run", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
)
async def create_easy_run(name: str = "Easy Run", duration_secs: int = 1800, schedule_date: str | None = None) -> dict:
    """Erstellt einen einfachen, unstrukturierten lockeren Dauerlauf und laedt ihn hoch.

    Args:
        name: Name des Workouts
        duration_secs: Dauer in Sekunden
        schedule_date: Optional, Datum im Format YYYY-MM-DD zum Einplanen
    """

    def _do():
        workout = build_easy_run_workout(name, duration_secs)
        return upload_and_schedule(get_client(), workout, schedule_date)

    return await asyncio.to_thread(_do)


@mcp.tool(
    annotations={"title": "Create Custom Workout", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
)
async def create_custom_workout(name: str, steps: list[dict], schedule_date: str | None = None) -> dict:
    """Erstellt ein voll flexibles, individuell strukturiertes Workout (z.B. Pyramiden,
    Fahrtspiel, Tempowechsel) aus einer Liste von Steps und laedt es hoch.

    Erlaubte step-Dicts:
      {"type": "warmup", "duration_seconds": 600}
      {"type": "cooldown", "duration_seconds": 600}
      {"type": "interval", "duration_seconds": 300}  ODER {"type": "interval", "distance_meters": 1000}
      {"type": "recovery", "duration_seconds": 90}   ODER {"type": "recovery", "distance_meters": 200}
      {"type": "repeat", "count": 4, "steps": [ ... verschachtelte Steps ... ]}

    Args:
        name: Name des Workouts
        steps: Liste der Workout-Steps (siehe oben)
        schedule_date: Optional, Datum im Format YYYY-MM-DD zum Einplanen
    """

    def _do():
        workout = build_custom_workout(name, steps)
        return upload_and_schedule(get_client(), workout, schedule_date)

    return await asyncio.to_thread(_do)


@mcp.tool(
    annotations={"title": "Delete Workout", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True}
)
async def delete_workout(workout_id: int) -> dict:
    """Loescht ein bestehendes Workout von Garmin Connect anhand seiner ID.

    Args:
        workout_id: Die ID des zu loeschenden Workouts (kommt aus create_*-Antworten
            oder get_scheduled_workouts)
    """

    def _do():
        get_client().delete_workout(workout_id)
        return {"deleted": workout_id}

    return await asyncio.to_thread(_do)


# ---------------------------------------------------------------------------
# Eigene Login-Seite (Teil des Mini-OAuth-Servers, siehe oauth_provider.py)
# ---------------------------------------------------------------------------

LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"><title>Garmin MCP Login</title>
<style>
  body {{ font-family: sans-serif; max-width: 400px; margin: 80px auto; }}
  input {{ width: 100%; padding: 8px; margin: 8px 0; box-sizing: border-box; }}
  button {{ padding: 8px 16px; }}
  .error {{ color: #c00; }}
</style></head>
<body>
  <h2>Zugriff auf deinen Garmin MCP Server</h2>
  <p>{error}</p>
  <form method="post" action="/login">
    <input type="hidden" name="request_id" value="{request_id}">
    <input type="password" name="password" placeholder="Passwort" autofocus required>
    <button type="submit">Freigeben</button>
  </form>
</body>
</html>
"""


async def login_get(request: Request) -> HTMLResponse:
    request_id = request.query_params.get("request_id", "")
    return HTMLResponse(LOGIN_PAGE.format(request_id=request_id, error=""))


async def login_post(request: Request):
    form = await request.form()
    request_id = str(form.get("request_id", ""))
    password = str(form.get("password", ""))

    if auth_provider.get_pending(request_id) is None:
        return HTMLResponse("Session abgelaufen. Bitte den Connector in Claude erneut verbinden.", status_code=400)

    if password != LOGIN_PASSWORD:
        return HTMLResponse(
            LOGIN_PAGE.format(request_id=request_id, error='<span class="error">Falsches Passwort.</span>'),
            status_code=401,
        )

    redirect_url = auth_provider.complete_login(request_id)
    return RedirectResponse(redirect_url, status_code=302)


async def health(request: Request):
    from starlette.responses import PlainTextResponse

    return PlainTextResponse("ok")


app = mcp.streamable_http_app()
app.add_route("/login", login_get, methods=["GET"])
app.add_route("/login", login_post, methods=["POST"])
app.add_route("/health", health, methods=["GET"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
