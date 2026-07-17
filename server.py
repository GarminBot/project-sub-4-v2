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
import typing
from typing import Any

from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from garmin_client import call_with_relogin, get_client
from oauth_provider import GarminAuthProvider
from workouts import build_custom_workout, build_easy_run_workout, build_interval_workout, upload_and_schedule

ISSUER_URL = os.environ["ISSUER_URL"]  # z.B. https://garmin-mcp.onrender.com (OHNE trailing slash)
LOGIN_PASSWORD = os.environ["MCP_LOGIN_PASSWORD"]

# Hostname aus ISSUER_URL extrahieren, damit die DNS-Rebinding-Schutzpruefung
# der SDK Anfragen an genau diesen Host durchlaesst (sonst 421 Misdirected Request).
_issuer_host = ISSUER_URL.split("://", 1)[-1].split("/", 1)[0]

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
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[_issuer_host, "localhost", "127.0.0.1"],
        allowed_origins=["https://claude.ai", "https://*.claude.ai", "https://*.anthropic.com"],
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
    target_hr_min: int | None = None,
    target_hr_max: int | None = None,
    target_pace_fast_sec_per_km: int | None = None,
    target_pace_slow_sec_per_km: int | None = None,
) -> dict:
    """Erstellt ein strukturiertes Intervall-Workout (Warmup - N x Intervall/Erholung -
    Cooldown) und laedt es zu Garmin Connect hoch. Optional wird es direkt auf ein
    Datum eingeplant, damit es automatisch aufs Geraet synct. Die Uhr zeigt waehrend
    des Laufs jeden Step einzeln an (nicht nur "Aufwaermen" fuer die ganze Dauer).

    Fuer die Intervall-Steps kann optional EIN Ziel angegeben werden: entweder ein
    Puls-Bereich (target_hr_min/max) ODER ein Pace-Bereich (target_pace_*), nicht beides.

    Args:
        name: Name des Workouts, z.B. "6x800m Intervalle"
        warmup_secs: Warmup-Dauer in Sekunden
        interval_meters: Distanz pro Intervall in Metern
        interval_count: Anzahl Wiederholungen
        recovery_secs: Erholungsdauer zwischen Intervallen in Sekunden
        cooldown_secs: Cooldown-Dauer in Sekunden
        schedule_date: Optional, Datum im Format YYYY-MM-DD zum Einplanen
        target_hr_min: Optional, untere Pulsgrenze in bpm fuer die Intervalle
        target_hr_max: Optional, obere Pulsgrenze in bpm fuer die Intervalle
        target_pace_fast_sec_per_km: Optional, schnellere Pace-Grenze in Sek/km (z.B. 270 = 4:30/km)
        target_pace_slow_sec_per_km: Optional, langsamere Pace-Grenze in Sek/km (z.B. 300 = 5:00/km)
    """

    def _do():
        workout = build_interval_workout(
            name, warmup_secs, interval_meters, interval_count, recovery_secs, cooldown_secs,
            target_hr_min=target_hr_min, target_hr_max=target_hr_max,
            target_pace_fast_sec_per_km=target_pace_fast_sec_per_km,
            target_pace_slow_sec_per_km=target_pace_slow_sec_per_km,
        )
        return upload_and_schedule(get_client(), workout, schedule_date)

    return await asyncio.to_thread(_do)


@mcp.tool(
    annotations={"title": "Create Easy Run", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
)
async def create_easy_run(
    name: str = "Easy Run",
    duration_secs: int = 1800,
    schedule_date: str | None = None,
    target_hr_min: int | None = None,
    target_hr_max: int | None = None,
    target_pace_fast_sec_per_km: int | None = None,
    target_pace_slow_sec_per_km: int | None = None,
) -> dict:
    """Erstellt einen einfachen, unstrukturierten lockeren Dauerlauf und laedt ihn hoch.
    Optional mit einem Puls- oder Pace-Zielbereich (z.B. um sicherzustellen, dass der
    Lauf wirklich locker/Zone 2 bleibt).

    Args:
        name: Name des Workouts
        duration_secs: Dauer in Sekunden
        schedule_date: Optional, Datum im Format YYYY-MM-DD zum Einplanen
        target_hr_min: Optional, untere Pulsgrenze in bpm
        target_hr_max: Optional, obere Pulsgrenze in bpm
        target_pace_fast_sec_per_km: Optional, schnellere Pace-Grenze in Sek/km
        target_pace_slow_sec_per_km: Optional, langsamere Pace-Grenze in Sek/km
    """

    def _do():
        workout = build_easy_run_workout(
            name, duration_secs,
            target_hr_min=target_hr_min, target_hr_max=target_hr_max,
            target_pace_fast_sec_per_km=target_pace_fast_sec_per_km,
            target_pace_slow_sec_per_km=target_pace_slow_sec_per_km,
        )
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

    Jeder Step (ausser repeat) kann optional ein "target" enthalten:
      {"kind": "heart_rate", "min_bpm": 150, "max_bpm": 165}
      {"kind": "pace", "fast_sec_per_km": 270, "slow_sec_per_km": 300}
    Beispiel: {"type": "interval", "distance_meters": 1000, "target": {"kind": "heart_rate", "min_bpm": 165, "max_bpm": 178}}

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

    pending = await auth_provider.get_pending(request_id)
    if pending is None:
        return HTMLResponse("Session abgelaufen. Bitte den Connector in Claude erneut verbinden.", status_code=400)

    if password != LOGIN_PASSWORD:
        return HTMLResponse(
            LOGIN_PAGE.format(request_id=request_id, error='<span class="error">Falsches Passwort.</span>'),
            status_code=401,
        )

    redirect_url = await auth_provider.complete_login(request_id)
    return RedirectResponse(redirect_url, status_code=302)


async def health(request: Request):
    from starlette.responses import PlainTextResponse

    return PlainTextResponse("ok")





# ---------------------------------------------------------------------------
# Automatisch generierte Tools: restliche Garmin-Connect-API-Oberflaeche
# (Schlaf/Ernaehrung/Gewicht/Blutdruck/Geraete/Gear/Abzeichen/Trainingsplaene/
# Golf/Menstruationszyklus/Aktivitaets-Detailmetriken etc.)
# ---------------------------------------------------------------------------


@mcp.tool(annotations={"title": "add_body_composition", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def add_body_composition(timestamp: str | None, weight: float, percent_fat: float | None = None, percent_hydration: float | None = None, visceral_fat_mass: float | None = None, bone_mass: float | None = None, muscle_mass: float | None = None, basal_met: float | None = None, active_met: float | None = None, physique_rating: float | None = None, metabolic_age: float | None = None, visceral_fat_rating: float | None = None, bmi: float | None = None) -> Any:
    """Ruft die Garmin-API-Methode 'add_body_composition' auf."""
    return await asyncio.to_thread(call_with_relogin, "add_body_composition", timestamp=timestamp, weight=weight, percent_fat=percent_fat, percent_hydration=percent_hydration, visceral_fat_mass=visceral_fat_mass, bone_mass=bone_mass, muscle_mass=muscle_mass, basal_met=basal_met, active_met=active_met, physique_rating=physique_rating, metabolic_age=metabolic_age, visceral_fat_rating=visceral_fat_rating, bmi=bmi)


@mcp.tool(annotations={"title": "add_gear_to_activity", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def add_gear_to_activity(gearUUID: str, activity_id: int | str) -> Any:
    """Associates gear with an activity. Requires a gearUUID and an activity_id. Args: gearUUID: UID for gear to add to activity. Findable though the get_gear function activity_id: Integer ID for the activity to add the gear to Returns: Dictionary containing information for the added gear"""
    return await asyncio.to_thread(call_with_relogin, "add_gear_to_activity", gearUUID=gearUUID, activity_id=activity_id)


@mcp.tool(annotations={"title": "add_hydration_data", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def add_hydration_data(value_in_ml: float, timestamp: str | None = None, cdate: str | None = None) -> Any:
    """Add hydration data in ml. Defaults to current date and current timestamp if left empty :param float required - value_in_ml: The number of ml of water you wish to add (positive) or subtract (negative) :param timestamp optional - timestamp: The timestamp of the hydration update, format 'YYYY-MM-DDThh:mm:ss.ms' Defaults to current timestamp :param date optional - cdate: The date of the weigh in, format 'YYYY-MM-DD'. Defaults to current date."""
    return await asyncio.to_thread(call_with_relogin, "add_hydration_data", value_in_ml=value_in_ml, timestamp=timestamp, cdate=cdate)


@mcp.tool(annotations={"title": "add_weigh_in", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def add_weigh_in(weight: int | float, unitKey: str = 'kg', timestamp: str = '') -> Any:
    """Add a weigh-in (default to kg)."""
    return await asyncio.to_thread(call_with_relogin, "add_weigh_in", weight=weight, unitKey=unitKey, timestamp=timestamp)


@mcp.tool(annotations={"title": "add_weigh_in_with_timestamps", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def add_weigh_in_with_timestamps(weight: int | float, unitKey: str = 'kg', dateTimestamp: str = '', gmtTimestamp: str = '') -> Any:
    """Add a weigh-in with explicit timestamps (default to kg)."""
    return await asyncio.to_thread(call_with_relogin, "add_weigh_in_with_timestamps", weight=weight, unitKey=unitKey, dateTimestamp=dateTimestamp, gmtTimestamp=gmtTimestamp)


@mcp.tool(annotations={"title": "count_activities", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def count_activities() -> Any:
    """Return total number of activities for the current user account."""
    return await asyncio.to_thread(call_with_relogin, "count_activities" )


@mcp.tool(annotations={"title": "create_manual_activity", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def create_manual_activity(start_datetime: str, time_zone: str, type_key: str, distance_km: float, duration_min: int, activity_name: str) -> Any:
    """Create a private activity manually with a few basic parameters. type_key - Garmin field representing type of activity. See https://connect.garmin.com/modern/main/js/properties/activity_types/activity_types.properties Value to use is the key without 'activity_type_' prefix, e.g. 'resort_skiing' start_datetime - timestamp in this pattern "2023-12-02T10:00:00.000" time_zone - local timezone of the activity, e.g. 'Europe/Paris' distance_km - distance of the activity in kilometers duration_min - duration of the activity in minutes activity_name - the title."""
    return await asyncio.to_thread(call_with_relogin, "create_manual_activity", start_datetime=start_datetime, time_zone=time_zone, type_key=type_key, distance_km=distance_km, duration_min=duration_min, activity_name=activity_name)


@mcp.tool(annotations={"title": "delete_activity", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
async def delete_activity(activity_id: str) -> Any:
    """Delete activity with specified id."""
    return await asyncio.to_thread(call_with_relogin, "delete_activity", activity_id=activity_id)


@mcp.tool(annotations={"title": "delete_blood_pressure", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
async def delete_blood_pressure(version: str, cdate: str) -> Any:
    """Delete specific blood pressure measurement."""
    return await asyncio.to_thread(call_with_relogin, "delete_blood_pressure", version=version, cdate=cdate)


@mcp.tool(annotations={"title": "delete_weigh_in", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
async def delete_weigh_in(weight_pk: str, cdate: str) -> Any:
    """Delete specific weigh-in."""
    return await asyncio.to_thread(call_with_relogin, "delete_weigh_in", weight_pk=weight_pk, cdate=cdate)


@mcp.tool(annotations={"title": "delete_weigh_ins", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
async def delete_weigh_ins(cdate: str, delete_all: bool = False) -> Any:
    """Delete weigh-in for 'cdate' format 'YYYY-MM-DD'. Includes option to delete all weigh-ins for that date."""
    return await asyncio.to_thread(call_with_relogin, "delete_weigh_ins", cdate=cdate, delete_all=delete_all)


@mcp.tool(annotations={"title": "get_activities_paginated", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activities_paginated(start: int = 0, limit: int = 20, activitytype: str | None = None) -> Any:
    """Return available activities. :param start: Starting activity offset, where 0 means the most recent activity :param limit: Number of activities to return :param activitytype: (Optional) Filter activities by type :return: List of activities from Garmin."""
    return await asyncio.to_thread(call_with_relogin, "get_activities", start=start, limit=limit, activitytype=activitytype)


@mcp.tool(annotations={"title": "get_activities_by_date", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activities_by_date(startdate: str, enddate: str | None = None, activitytype: str | None = None, sortorder: str | None = None) -> Any:
    """Fetch available activities between specific dates :param startdate: String in the format YYYY-MM-DD :param enddate: (Optional) String in the format YYYY-MM-DD :param activitytype: (Optional) Type of activity you are searching Possible values are [cycling, running, swimming, multi_sport, fitness_equipment, hiking, walking, other] :param sortorder: (Optional) sorting direction. By default, Garmin uses descending order by startLocal field. Use "asc" to get activities from oldest to newest. :return: list of JSON activities."""
    return await asyncio.to_thread(call_with_relogin, "get_activities_by_date", startdate=startdate, enddate=enddate, activitytype=activitytype, sortorder=sortorder)


@mcp.tool(annotations={"title": "get_activities_fordate", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activities_fordate(fordate: str) -> Any:
    """Return available activities for date."""
    return await asyncio.to_thread(call_with_relogin, "get_activities_fordate", fordate=fordate)


@mcp.tool(annotations={"title": "get_activity", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity(activity_id: str) -> Any:
    """Return activity summary, including basic splits."""
    return await asyncio.to_thread(call_with_relogin, "get_activity", activity_id=activity_id)


@mcp.tool(annotations={"title": "get_activity_details", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_details(activity_id: str, maxchart: int = 2000, maxpoly: int = 4000) -> Any:
    """Return activity details."""
    return await asyncio.to_thread(call_with_relogin, "get_activity_details", activity_id=activity_id, maxchart=maxchart, maxpoly=maxpoly)


@mcp.tool(annotations={"title": "get_activity_exercise_sets", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_exercise_sets(activity_id: int | str) -> Any:
    """Return activity exercise sets."""
    return await asyncio.to_thread(call_with_relogin, "get_activity_exercise_sets", activity_id=activity_id)


@mcp.tool(annotations={"title": "get_activity_gear", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_gear(activity_id: int | str) -> Any:
    """Return gears used for activity id."""
    return await asyncio.to_thread(call_with_relogin, "get_activity_gear", activity_id=activity_id)


@mcp.tool(annotations={"title": "get_activity_hr_in_timezones", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_hr_in_timezones(activity_id: str) -> Any:
    """Return activity heartrate in timezones."""
    return await asyncio.to_thread(call_with_relogin, "get_activity_hr_in_timezones", activity_id=activity_id)


@mcp.tool(annotations={"title": "get_activity_power_in_timezones", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_power_in_timezones(activity_id: str) -> Any:
    """Return activity power in timezones."""
    return await asyncio.to_thread(call_with_relogin, "get_activity_power_in_timezones", activity_id=activity_id)


@mcp.tool(annotations={"title": "get_activity_split_summaries", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_split_summaries(activity_id: str) -> Any:
    """Return activity split summaries."""
    return await asyncio.to_thread(call_with_relogin, "get_activity_split_summaries", activity_id=activity_id)


@mcp.tool(annotations={"title": "get_activity_splits", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_splits(activity_id: str) -> Any:
    """Return activity splits."""
    return await asyncio.to_thread(call_with_relogin, "get_activity_splits", activity_id=activity_id)


@mcp.tool(annotations={"title": "get_activity_typed_splits", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_typed_splits(activity_id: str) -> Any:
    """Return typed activity splits. Contains similar info to `get_activity_splits`, but for certain activity types (e.g., Bouldering), this contains more detail."""
    return await asyncio.to_thread(call_with_relogin, "get_activity_typed_splits", activity_id=activity_id)


@mcp.tool(annotations={"title": "get_activity_types", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_types() -> Any:
    """Ruft die Garmin-API-Methode 'get_activity_types' auf."""
    return await asyncio.to_thread(call_with_relogin, "get_activity_types" )


@mcp.tool(annotations={"title": "get_activity_weather", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_weather(activity_id: str) -> Any:
    """Return activity weather."""
    return await asyncio.to_thread(call_with_relogin, "get_activity_weather", activity_id=activity_id)


@mcp.tool(annotations={"title": "get_adaptive_training_plan_by_id", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_adaptive_training_plan_by_id(plan_id: int | str) -> Any:
    """Return details for a specific adaptive training plan."""
    return await asyncio.to_thread(call_with_relogin, "get_adaptive_training_plan_by_id", plan_id=plan_id)


@mcp.tool(annotations={"title": "get_adhoc_challenges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_adhoc_challenges(start: int, limit: int) -> Any:
    """Return adhoc challenges for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_adhoc_challenges", start=start, limit=limit)


@mcp.tool(annotations={"title": "get_all_day_events", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_all_day_events(cdate: str) -> Any:
    """Return available daily events data 'cdate' format 'YYYY-MM-DD'. Includes autodetected activities, even if not recorded on the watch."""
    return await asyncio.to_thread(call_with_relogin, "get_all_day_events", cdate=cdate)


@mcp.tool(annotations={"title": "get_all_day_stress", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_all_day_stress(cdate: str) -> Any:
    """Return available all day stress data 'cdate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_all_day_stress", cdate=cdate)


@mcp.tool(annotations={"title": "get_available_badge_challenges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_available_badge_challenges(start: int, limit: int) -> Any:
    """Return available badge challenges."""
    return await asyncio.to_thread(call_with_relogin, "get_available_badge_challenges", start=start, limit=limit)


@mcp.tool(annotations={"title": "get_available_badges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_available_badges() -> Any:
    """Return available badges for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_available_badges" )


@mcp.tool(annotations={"title": "get_badge_challenges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_badge_challenges(start: int, limit: int) -> Any:
    """Return badge challenges for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_badge_challenges", start=start, limit=limit)


@mcp.tool(annotations={"title": "get_blood_pressure", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_blood_pressure(startdate: str, enddate: str | None = None) -> Any:
    """Returns blood pressure by day for 'startdate' format 'YYYY-MM-DD' through enddate 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_blood_pressure", startdate=startdate, enddate=enddate)


@mcp.tool(annotations={"title": "get_body_battery_events", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_body_battery_events(cdate: str) -> Any:
    """Return body battery events for date 'cdate' format 'YYYY-MM-DD'. The return value is a list of dictionaries, where each dictionary contains event data for a specific event. Events can include sleep, recorded activities, auto-detected activities, and naps."""
    return await asyncio.to_thread(call_with_relogin, "get_body_battery_events", cdate=cdate)


@mcp.tool(annotations={"title": "get_body_composition", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_body_composition(startdate: str, enddate: str | None = None) -> Any:
    """Return available body composition data for 'startdate' format 'YYYY-MM-DD' through enddate 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_body_composition", startdate=startdate, enddate=enddate)


@mcp.tool(annotations={"title": "get_cycling_ftp", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_cycling_ftp() -> Any:
    """Return cycling Functional Threshold Power (FTP) information."""
    return await asyncio.to_thread(call_with_relogin, "get_cycling_ftp" )


@mcp.tool(annotations={"title": "get_daily_steps", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_daily_steps(start: str, end: str) -> Any:
    """Fetch available steps data 'start' and 'end' format 'YYYY-MM-DD'. Note: The Garmin Connect API has a 28-day limit per request. For date ranges exceeding 28 days, this method automatically splits the range into chunks and makes multiple API calls, then merges the results."""
    return await asyncio.to_thread(call_with_relogin, "get_daily_steps", start=start, end=end)


@mcp.tool(annotations={"title": "get_daily_weigh_ins", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_daily_weigh_ins(cdate: str) -> Any:
    """Get weigh-ins for 'cdate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_daily_weigh_ins", cdate=cdate)


@mcp.tool(annotations={"title": "get_device_alarms", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_device_alarms() -> Any:
    """Get list of active alarms from all devices."""
    return await asyncio.to_thread(call_with_relogin, "get_device_alarms" )


@mcp.tool(annotations={"title": "get_device_last_used", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_device_last_used() -> Any:
    """Return device last used."""
    return await asyncio.to_thread(call_with_relogin, "get_device_last_used" )


@mcp.tool(annotations={"title": "get_device_settings", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_device_settings(device_id: str) -> Any:
    """Return device settings for device with 'device_id'."""
    return await asyncio.to_thread(call_with_relogin, "get_device_settings", device_id=device_id)


@mcp.tool(annotations={"title": "get_device_solar_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_device_solar_data(device_id: str, startdate: str, enddate: str | None = None) -> Any:
    """Return solar data for compatible device with 'device_id'."""
    return await asyncio.to_thread(call_with_relogin, "get_device_solar_data", device_id=device_id, startdate=startdate, enddate=enddate)


@mcp.tool(annotations={"title": "get_devices", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_devices() -> Any:
    """Return available devices for the current user account."""
    return await asyncio.to_thread(call_with_relogin, "get_devices" )


@mcp.tool(annotations={"title": "get_earned_badges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_earned_badges() -> Any:
    """Return earned badges for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_earned_badges" )


@mcp.tool(annotations={"title": "get_endurance_score", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_endurance_score(startdate: str, enddate: str | None = None) -> Any:
    """Return endurance score by day for 'startdate' format 'YYYY-MM-DD' through enddate 'YYYY-MM-DD'. Using a single day returns the precise values for that day. Using a range returns the aggregated weekly values for that week."""
    return await asyncio.to_thread(call_with_relogin, "get_endurance_score", startdate=startdate, enddate=enddate)


@mcp.tool(annotations={"title": "get_fitnessage_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_fitnessage_data(cdate: str) -> Any:
    """Return Fitness Age data for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_fitnessage_data", cdate=cdate)


@mcp.tool(annotations={"title": "get_floors", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_floors(cdate: str) -> Any:
    """Fetch available floors data 'cDate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_floors", cdate=cdate)


@mcp.tool(annotations={"title": "get_full_name", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_full_name() -> Any:
    """Return full name."""
    return await asyncio.to_thread(call_with_relogin, "get_full_name" )


@mcp.tool(annotations={"title": "get_gear", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_gear(userProfileNumber: str) -> Any:
    """Return all user gear."""
    return await asyncio.to_thread(call_with_relogin, "get_gear", userProfileNumber=userProfileNumber)


@mcp.tool(annotations={"title": "get_gear_activities", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_gear_activities(gearUUID: str, limit: int = 1000) -> Any:
    """Return activities where gear uuid was used. :param gearUUID: UUID of the gear to get activities for :param limit: Maximum number of activities to return (default: 1000) :return: List of activities where the specified gear was used."""
    return await asyncio.to_thread(call_with_relogin, "get_gear_activities", gearUUID=gearUUID, limit=limit)


@mcp.tool(annotations={"title": "get_gear_defaults", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_gear_defaults(userProfileNumber: str) -> Any:
    """Ruft die Garmin-API-Methode 'get_gear_defaults' auf."""
    return await asyncio.to_thread(call_with_relogin, "get_gear_defaults", userProfileNumber=userProfileNumber)


@mcp.tool(annotations={"title": "get_gear_stats", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_gear_stats(gearUUID: str) -> Any:
    """Ruft die Garmin-API-Methode 'get_gear_stats' auf."""
    return await asyncio.to_thread(call_with_relogin, "get_gear_stats", gearUUID=gearUUID)


@mcp.tool(annotations={"title": "get_goals", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_goals(status: str = 'active', start: int = 0, limit: int = 30) -> Any:
    """Fetch all goals based on status :param status: Status of goals (valid options are "active", "future", or "past") :type status: str :param start: Initial goal index :type start: int :param limit: Pagination limit when retrieving goals :type limit: int :return: list of goals in JSON format."""
    return await asyncio.to_thread(call_with_relogin, "get_goals", status=status, start=start, limit=limit)


@mcp.tool(annotations={"title": "get_golf_scorecard", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_golf_scorecard(scorecard_id: int | str) -> Any:
    """Return golf scorecard detail by scorecard ID. Args: scorecard_id: The scorecard ID to retrieve. Returns: Dictionary containing the golf scorecard detail."""
    return await asyncio.to_thread(call_with_relogin, "get_golf_scorecard", scorecard_id=scorecard_id)


@mcp.tool(annotations={"title": "get_golf_shot_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_golf_shot_data(scorecard_id: int | str, hole_numbers: str = '1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18') -> Any:
    """Return golf shot data for a scorecard and specific holes. Args: scorecard_id: The scorecard ID to get shot data for. hole_numbers: Comma-separated hole numbers (default: all 18). Returns: Dictionary containing shot data per hole."""
    return await asyncio.to_thread(call_with_relogin, "get_golf_shot_data", scorecard_id=scorecard_id, hole_numbers=hole_numbers)


@mcp.tool(annotations={"title": "get_golf_summary", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_golf_summary(start: int = 0, limit: int = 100) -> Any:
    """Return golf scorecard summary. Args: start: Starting offset for pagination. limit: Maximum number of results to return. Returns: List of golf scorecard summaries."""
    return await asyncio.to_thread(call_with_relogin, "get_golf_summary", start=start, limit=limit)


@mcp.tool(annotations={"title": "get_heart_rates", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_heart_rates(cdate: str) -> Any:
    """Fetch available heart rates data 'cDate' format 'YYYY-MM-DD'. Args: cdate: Date string in format 'YYYY-MM-DD' Returns: Dictionary containing heart rate data for the specified date Raises: ValueError: If cdate format is invalid GarminConnectConnectionError: If no data received GarminConnectAuthenticationError: If authentication fails"""
    return await asyncio.to_thread(call_with_relogin, "get_heart_rates", cdate=cdate)


@mcp.tool(annotations={"title": "get_hill_score", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_hill_score(startdate: str, enddate: str | None = None) -> Any:
    """Return hill score by day from 'startdate' format 'YYYY-MM-DD' to enddate 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_hill_score", startdate=startdate, enddate=enddate)


@mcp.tool(annotations={"title": "get_hrv_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_hrv_data(cdate: str) -> Any:
    """Return Heart Rate Variability (hrv) data for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_hrv_data", cdate=cdate)


@mcp.tool(annotations={"title": "get_hydration_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_hydration_data(cdate: str) -> Any:
    """Return available hydration data 'cdate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_hydration_data", cdate=cdate)


@mcp.tool(annotations={"title": "get_in_progress_badges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_in_progress_badges() -> Any:
    """Return in progress badges for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_in_progress_badges" )


@mcp.tool(annotations={"title": "get_inprogress_virtual_challenges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_inprogress_virtual_challenges(start: int, limit: int) -> Any:
    """Return in-progress virtual challenges for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_inprogress_virtual_challenges", start=start, limit=limit)


@mcp.tool(annotations={"title": "get_intensity_minutes_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_intensity_minutes_data(cdate: str) -> Any:
    """Return available Intensity Minutes data 'cdate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_intensity_minutes_data", cdate=cdate)


@mcp.tool(annotations={"title": "get_lactate_threshold", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_lactate_threshold(*, latest: bool = True, start_date: str | datetime.date | None = None, end_date: str | datetime.date | None = None, aggregation: str = 'daily') -> Any:
    """Returns Running Lactate Threshold information, including heart rate, power, and speed. :param bool (Required) - latest: Whether to query for the latest Lactate Threshold info or a range. False if querying a range :param date (Optional) - start_date: The first date in the range to query, format 'YYYY-MM-DD'. Required if `latest` is False. Ignored if `latest` is True :param date (Optional) - end_date: The last date in the range to query, format 'YYYY-MM-DD'. Defaults to current data. Ignored if `latest` is True :param str (Optional) - aggregation: How to aggregate the data. Must be one of `daily`, `weekly`, `monthly`, `yearly`."""
    return await asyncio.to_thread(call_with_relogin, "get_lactate_threshold", latest=latest, start_date=start_date, end_date=end_date, aggregation=aggregation)


@mcp.tool(annotations={"title": "get_last_activity", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_last_activity() -> Any:
    """Return last activity."""
    return await asyncio.to_thread(call_with_relogin, "get_last_activity" )


@mcp.tool(annotations={"title": "get_lifestyle_logging_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_lifestyle_logging_data(cdate: str) -> Any:
    """Return lifestyle logging data for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_lifestyle_logging_data", cdate=cdate)


@mcp.tool(annotations={"title": "get_max_metrics", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_max_metrics(cdate: str) -> Any:
    """Return available max metric data for 'cdate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_max_metrics", cdate=cdate)


@mcp.tool(annotations={"title": "get_menstrual_calendar_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_menstrual_calendar_data(startdate: str, enddate: str) -> Any:
    """Return summaries of cycles that have days between startdate and enddate."""
    return await asyncio.to_thread(call_with_relogin, "get_menstrual_calendar_data", startdate=startdate, enddate=enddate)


@mcp.tool(annotations={"title": "get_menstrual_data_for_date", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_menstrual_data_for_date(fordate: str) -> Any:
    """Return menstrual data for date."""
    return await asyncio.to_thread(call_with_relogin, "get_menstrual_data_for_date", fordate=fordate)


@mcp.tool(annotations={"title": "get_morning_training_readiness", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_morning_training_readiness(cdate: str) -> Any:
    """Return morning training readiness data for current user. This returns the Training Readiness score calculated immediately after waking up, which is shown in Garmin's Morning Report feature. It filters for entries with inputContext == 'AFTER_WAKEUP_RESET'. Args: cdate: Date string in format 'YYYY-MM-DD' Returns: Dictionary containing morning training readiness data, or None if no morning data is available for the specified date. Note: Not all devices/firmware versions populate the inputContext field. If inputContext is null for all entries, this method returns the first entry as a fallback (typically the morning reading)."""
    return await asyncio.to_thread(call_with_relogin, "get_morning_training_readiness", cdate=cdate)


@mcp.tool(annotations={"title": "get_non_completed_badge_challenges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_non_completed_badge_challenges(start: int, limit: int) -> Any:
    """Return badge non-completed challenges for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_non_completed_badge_challenges", start=start, limit=limit)


@mcp.tool(annotations={"title": "get_nutrition_daily_food_log", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_nutrition_daily_food_log(cdate: str) -> Any:
    """Return food log summary for 'cdate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_nutrition_daily_food_log", cdate=cdate)


@mcp.tool(annotations={"title": "get_nutrition_daily_meals", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_nutrition_daily_meals(cdate: str) -> Any:
    """Return meals summary for 'cdate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_nutrition_daily_meals", cdate=cdate)


@mcp.tool(annotations={"title": "get_nutrition_daily_settings", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_nutrition_daily_settings(cdate: str) -> Any:
    """Return nutrition settings for 'cdate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_nutrition_daily_settings", cdate=cdate)


@mcp.tool(annotations={"title": "get_personal_record", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_personal_record() -> Any:
    """Return personal records for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_personal_record" )


@mcp.tool(annotations={"title": "get_pregnancy_summary", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_pregnancy_summary() -> Any:
    """Return snapshot of pregnancy data."""
    return await asyncio.to_thread(call_with_relogin, "get_pregnancy_summary" )


@mcp.tool(annotations={"title": "get_primary_training_device", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_primary_training_device() -> Any:
    """Return detailed information around primary training devices, included the specified device and the priority of all devices."""
    return await asyncio.to_thread(call_with_relogin, "get_primary_training_device" )


@mcp.tool(annotations={"title": "get_progress_summary_between_dates", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_progress_summary_between_dates(startdate: str, enddate: str, metric: str = 'distance', groupbyactivities: bool = True) -> Any:
    """Fetch progress summary data between specific dates :param startdate: String in the format YYYY-MM-DD :param enddate: String in the format YYYY-MM-DD :param metric: metric to be calculated in the summary: "elevationGain", "duration", "distance", "movingDuration" :param groupbyactivities: group the summary by activity type :return: list of JSON activities with their aggregated progress summary."""
    return await asyncio.to_thread(call_with_relogin, "get_progress_summary_between_dates", startdate=startdate, enddate=enddate, metric=metric, groupbyactivities=groupbyactivities)


@mcp.tool(annotations={"title": "get_respiration_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_respiration_data(cdate: str) -> Any:
    """Return available respiration data 'cdate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_respiration_data", cdate=cdate)


@mcp.tool(annotations={"title": "get_rhr_day", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_rhr_day(cdate: str) -> Any:
    """Return resting heartrate data for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_rhr_day", cdate=cdate)


@mcp.tool(annotations={"title": "get_running_tolerance", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_running_tolerance(startdate: str, enddate: str, aggregation: str = 'weekly') -> Any:
    """Return running tolerance data for date range. Args: startdate: Start date in 'YYYY-MM-DD' format. enddate: End date in 'YYYY-MM-DD' format. aggregation: 'daily' or 'weekly' (default: 'weekly'). Returns: List of running tolerance data points."""
    return await asyncio.to_thread(call_with_relogin, "get_running_tolerance", startdate=startdate, enddate=enddate, aggregation=aggregation)


@mcp.tool(annotations={"title": "get_scheduled_workout_by_id", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_scheduled_workout_by_id(scheduled_workout_id: int | str) -> Any:
    """Return scheduled workout by ID."""
    return await asyncio.to_thread(call_with_relogin, "get_scheduled_workout_by_id", scheduled_workout_id=scheduled_workout_id)


@mcp.tool(annotations={"title": "get_sleep_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_sleep_data(cdate: str) -> Any:
    """Return sleep data for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_sleep_data", cdate=cdate)


@mcp.tool(annotations={"title": "get_spo2_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_spo2_data(cdate: str) -> Any:
    """Return available SpO2 data 'cdate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_spo2_data", cdate=cdate)


@mcp.tool(annotations={"title": "get_stats", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_stats(cdate: str) -> Any:
    """Return user activity summary for 'cdate' format 'YYYY-MM-DD' (compat for garminconnect)."""
    return await asyncio.to_thread(call_with_relogin, "get_stats", cdate=cdate)


@mcp.tool(annotations={"title": "get_stats_and_body", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_stats_and_body(cdate: str) -> Any:
    """Return activity data and body composition (compat for garminconnect)."""
    return await asyncio.to_thread(call_with_relogin, "get_stats_and_body", cdate=cdate)


@mcp.tool(annotations={"title": "get_steps_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_steps_data(cdate: str) -> Any:
    """Fetch available steps data 'cDate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_steps_data", cdate=cdate)


@mcp.tool(annotations={"title": "get_stress_data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_stress_data(cdate: str) -> Any:
    """Return stress data for current user."""
    return await asyncio.to_thread(call_with_relogin, "get_stress_data", cdate=cdate)


@mcp.tool(annotations={"title": "get_training_plan_by_id", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_training_plan_by_id(plan_id: int | str) -> Any:
    """Return details for a specific training plan."""
    return await asyncio.to_thread(call_with_relogin, "get_training_plan_by_id", plan_id=plan_id)


@mcp.tool(annotations={"title": "get_training_plans", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_training_plans() -> Any:
    """Return all available training plans."""
    return await asyncio.to_thread(call_with_relogin, "get_training_plans" )


@mcp.tool(annotations={"title": "get_unit_system", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_unit_system() -> Any:
    """Return unit system."""
    return await asyncio.to_thread(call_with_relogin, "get_unit_system" )


@mcp.tool(annotations={"title": "get_user_profile", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_user_profile() -> Any:
    """Get all users settings."""
    return await asyncio.to_thread(call_with_relogin, "get_user_profile" )


@mcp.tool(annotations={"title": "get_user_summary", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_user_summary(cdate: str) -> Any:
    """Return user activity summary for 'cdate' format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_user_summary", cdate=cdate)


@mcp.tool(annotations={"title": "get_userprofile_settings", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_userprofile_settings() -> Any:
    """Get user settings."""
    return await asyncio.to_thread(call_with_relogin, "get_userprofile_settings" )


@mcp.tool(annotations={"title": "get_weekly_intensity_minutes", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_weekly_intensity_minutes(start: str, end: str) -> Any:
    """Fetch weekly intensity minutes aggregates. Args: start: Start date string in format 'YYYY-MM-DD' end: End date string in format 'YYYY-MM-DD' Returns: List of weekly intensity minute aggregates containing: - weeklyGoal: Weekly intensity minutes goal - moderateValue: Moderate intensity minutes - vigorousValue: Vigorous intensity minutes - calendarDate: Week start date"""
    return await asyncio.to_thread(call_with_relogin, "get_weekly_intensity_minutes", start=start, end=end)


@mcp.tool(annotations={"title": "get_weekly_steps", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_weekly_steps(end: str, weeks: int = 52) -> Any:
    """Fetch weekly steps aggregates. Args: end: End date string in format 'YYYY-MM-DD' weeks: Number of weeks to fetch (default 52 = 1 year) Returns: List of weekly step aggregates containing: - totalSteps: Total steps for the week - averageSteps: Average daily steps - totalDistance: Total distance in meters - averageDistance: Average daily distance - wellnessDataDaysCount: Days with data"""
    return await asyncio.to_thread(call_with_relogin, "get_weekly_steps", end=end, weeks=weeks)


@mcp.tool(annotations={"title": "get_weekly_stress", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_weekly_stress(end: str, weeks: int = 52) -> Any:
    """Fetch weekly stress aggregates. Args: end: End date string in format 'YYYY-MM-DD' weeks: Number of weeks to fetch (default 52 = 1 year) Returns: List of weekly stress aggregates containing: - value: Overall stress value for the week - calendarDate: Week start date"""
    return await asyncio.to_thread(call_with_relogin, "get_weekly_stress", end=end, weeks=weeks)


@mcp.tool(annotations={"title": "get_weigh_ins", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_weigh_ins(startdate: str, enddate: str) -> Any:
    """Get weigh-ins between startdate and enddate using format 'YYYY-MM-DD'."""
    return await asyncio.to_thread(call_with_relogin, "get_weigh_ins", startdate=startdate, enddate=enddate)


@mcp.tool(annotations={"title": "get_workout_by_id", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_workout_by_id(workout_id: int | str) -> Any:
    """Return workout by id."""
    return await asyncio.to_thread(call_with_relogin, "get_workout_by_id", workout_id=workout_id)


@mcp.tool(annotations={"title": "get_workouts", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_workouts(start: int = 0, limit: int = 100) -> Any:
    """Return workouts starting at offset `start` with at most `limit` results."""
    return await asyncio.to_thread(call_with_relogin, "get_workouts", start=start, limit=limit)


@mcp.tool(annotations={"title": "import_activity", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def import_activity(activity_path: str) -> Any:
    """Upload activity as an import (not re-exported to third parties like Strava). Uses the Garmin import endpoint with headers matching Garmin Connect Mobile, so imported activities are treated as imports rather than device-synced activities. Args: activity_path: Path to the activity file (FIT, TCX, or GPX). Returns: Dictionary containing the DetailedImportResult with successes, failures, and activity IDs. Raises: FileNotFoundError: If the activity file does not exist. GarminConnectInvalidFileFormatError: If the file format is invalid. GarminConnectConnectionError: If the upload fails."""
    return await asyncio.to_thread(call_with_relogin, "import_activity", activity_path=activity_path)


@mcp.tool(annotations={"title": "query_garmin_graphql", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def query_garmin_graphql(query: dict[str, typing.Any]) -> Any:
    """Execute a POST to Garmin's GraphQL endpoint. Args: query: A GraphQL request body, e.g. {"query": "...", "variables": {...}} See example.py for example queries. Returns: Parsed JSON response as a dict."""
    return await asyncio.to_thread(call_with_relogin, "query_garmin_graphql", query=query)


@mcp.tool(annotations={"title": "remove_gear_from_activity", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def remove_gear_from_activity(gearUUID: str, activity_id: int | str) -> Any:
    """Removes gear from an activity. Requires a gearUUID and an activity_id. Args: gearUUID: UID for gear to remove from activity. Findable though the get_gear method. activity_id: Integer ID for the activity to remove the gear from Returns: Dictionary containing information about the removed gear"""
    return await asyncio.to_thread(call_with_relogin, "remove_gear_from_activity", gearUUID=gearUUID, activity_id=activity_id)


@mcp.tool(annotations={"title": "request_reload", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def request_reload(cdate: str) -> Any:
    """Request reload of data for a specific date. This is necessary because Garmin offloads older data."""
    return await asyncio.to_thread(call_with_relogin, "request_reload", cdate=cdate)


@mcp.tool(annotations={"title": "set_activity_description", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def set_activity_description(activity_id: str, description: str) -> Any:
    """Set description for activity with id."""
    return await asyncio.to_thread(call_with_relogin, "set_activity_description", activity_id=activity_id, description=description)


@mcp.tool(annotations={"title": "set_activity_exercise_sets", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def set_activity_exercise_sets(activity_id: int | str, payload: dict[str, typing.Any]) -> Any:
    """Replace exercise sets for activity with id. `payload` is the full body sent to the server, in the same shape as the response from `get_activity_exercise_sets`. Replace-all semantics — the existing `exerciseSets` array is overwritten. Garmin validates the `exercises[].category` (parent) and `exercises[].name` (sub-category) against its FIT enum and returns 400 "Invalid Sub-Category Passed" for unknown values; `name=None` is always accepted under a known parent."""
    return await asyncio.to_thread(call_with_relogin, "set_activity_exercise_sets", activity_id=activity_id, payload=payload)


@mcp.tool(annotations={"title": "set_activity_name", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def set_activity_name(activity_id: str, title: str) -> Any:
    """Set name for activity with id."""
    return await asyncio.to_thread(call_with_relogin, "set_activity_name", activity_id=activity_id, title=title)


@mcp.tool(annotations={"title": "set_activity_type", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def set_activity_type(activity_id: str, type_id: int, type_key: str, parent_type_id: int) -> Any:
    """Ruft die Garmin-API-Methode 'set_activity_type' auf."""
    return await asyncio.to_thread(call_with_relogin, "set_activity_type", activity_id=activity_id, type_id=type_id, type_key=type_key, parent_type_id=parent_type_id)


@mcp.tool(annotations={"title": "set_blood_pressure", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def set_blood_pressure(systolic: int, diastolic: int, pulse: int, timestamp: str = '', notes: str = '') -> Any:
    """Add blood pressure measurement."""
    return await asyncio.to_thread(call_with_relogin, "set_blood_pressure", systolic=systolic, diastolic=diastolic, pulse=pulse, timestamp=timestamp, notes=notes)


@mcp.tool(annotations={"title": "set_gear_default", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def set_gear_default(activityType: str, gearUUID: str, defaultGear: bool = True) -> Any:
    """Ruft die Garmin-API-Methode 'set_gear_default' auf."""
    return await asyncio.to_thread(call_with_relogin, "set_gear_default", activityType=activityType, gearUUID=gearUUID, defaultGear=defaultGear)


app = mcp.streamable_http_app()
app.add_route("/login", login_get, methods=["GET"])
app.add_route("/login", login_post, methods=["POST"])
app.add_route("/health", health, methods=["GET"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
