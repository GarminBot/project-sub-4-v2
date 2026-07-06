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
LOGIN_PASSWORD = os.environ.get("MCP_LOGIN_PASSWORD", "")
MCP_AUTO_APPROVE = os.environ.get("MCP_AUTO_APPROVE", "true").lower() in {"1", "true", "yes", "on"}
TOKEN_STORE_PATH = os.environ.get("TOKEN_STORE_PATH", "/tmp/mcp_oauth_store.json")

# Hostname aus ISSUER_URL extrahieren, damit die DNS-Rebinding-Schutzpruefung
# der SDK Anfragen an genau diesen Host durchlaesst (sonst 421 Misdirected Request).
_issuer_host = ISSUER_URL.split("://", 1)[-1].split("/", 1)[0]

auth_provider = GarminAuthProvider(
    issuer_url=ISSUER_URL,
    password=LOGIN_PASSWORD,
    auto_approve=MCP_AUTO_APPROVE,
    store_path=TOKEN_STORE_PATH,
)

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
# Tools: Erweiterte Garmin-Lesedaten
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.date.today().isoformat()


def _month_range(year: int | None = None, month: int | None = None) -> tuple[str, str]:
    today = datetime.date.today()
    y = year or today.year
    m = month or today.month
    start = datetime.date(y, m, 1)
    if m == 12:
        end = datetime.date(y + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end = datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)
    return start.isoformat(), end.isoformat()


READ_ONLY_GARMIN_METHODS = {
    "count_activities", "get_activities", "get_activities_by_date", "get_activities_fordate",
    "get_activity", "get_activity_details", "get_activity_exercise_sets", "get_activity_gear",
    "get_activity_hr_in_timezones", "get_activity_power_in_timezones", "get_activity_split_summaries",
    "get_activity_splits", "get_activity_typed_splits", "get_activity_types", "get_activity_weather",
    "get_adaptive_training_plan_by_id", "get_adhoc_challenges", "get_all_day_events",
    "get_all_day_stress", "get_available_badge_challenges", "get_available_badges",
    "get_badge_challenges", "get_blood_pressure", "get_body_battery", "get_body_battery_events",
    "get_body_composition", "get_cycling_ftp", "get_daily_steps", "get_daily_weigh_ins",
    "get_device_alarms", "get_device_last_used", "get_device_settings", "get_device_solar_data",
    "get_devices", "get_earned_badges", "get_endurance_score", "get_fitnessage_data",
    "get_floors", "get_full_name", "get_gear", "get_gear_activities", "get_gear_defaults",
    "get_gear_stats", "get_goals", "get_heart_rates", "get_hill_score", "get_hrv_data",
    "get_hydration_data", "get_in_progress_badges", "get_inprogress_virtual_challenges",
    "get_intensity_minutes_data", "get_lactate_threshold", "get_last_activity",
    "get_lifestyle_logging_data", "get_max_metrics", "get_morning_training_readiness",
    "get_non_completed_badge_challenges", "get_nutrition_daily_food_log", "get_nutrition_daily_meals",
    "get_nutrition_daily_settings", "get_personal_record", "get_primary_training_device",
    "get_progress_summary_between_dates", "get_race_predictions", "get_respiration_data",
    "get_rhr_day", "get_running_tolerance", "get_scheduled_workout_by_id",
    "get_scheduled_workouts", "get_sleep_data", "get_spo2_data", "get_stats", "get_stats_and_body",
    "get_steps_data", "get_stress_data", "get_training_plan_by_id", "get_training_plans",
    "get_training_readiness", "get_training_status", "get_unit_system", "get_user_profile",
    "get_user_summary", "get_userprofile_settings", "get_weekly_intensity_minutes",
    "get_weekly_steps", "get_weekly_stress", "get_weigh_ins", "get_workout_by_id", "get_workouts",
}


async def _garmin(fn_name: str, *args, **kwargs):
    return await asyncio.to_thread(call_with_relogin, fn_name, *args, **kwargs)


@mcp.tool(annotations={"title": "Get Activity Details", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_details(activity_id: str, maxchart: int = 2000, maxpoly: int = 4000) -> dict:
    """Detaildaten einer einzelnen Aktivitaet: Charts, GPS/Polyline, Pace, Herzfrequenz und weitere Messpunkte."""
    return await _garmin("get_activity_details", activity_id, maxchart, maxpoly)


@mcp.tool(annotations={"title": "Get Activity Splits", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_splits(activity_id: str) -> dict:
    """Runden/Splits einer Aktivitaet, nuetzlich fuer Intervall- und Pace-Analyse."""
    return await _garmin("get_activity_splits", activity_id)


@mcp.tool(annotations={"title": "Get Activity Split Summaries", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_split_summaries(activity_id: str) -> dict:
    """Zusammenfassung der Splits einer Aktivitaet."""
    return await _garmin("get_activity_split_summaries", activity_id)


@mcp.tool(annotations={"title": "Get Activity Typed Splits", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_typed_splits(activity_id: str) -> dict:
    """Garmin Typed Splits einer Aktivitaet, falls vorhanden."""
    return await _garmin("get_activity_typed_splits", activity_id)


@mcp.tool(annotations={"title": "Get Activity HR Zones", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_hr_in_timezones(activity_id: str) -> dict:
    """Zeit in Herzfrequenzzonen fuer eine Aktivitaet."""
    return await _garmin("get_activity_hr_in_timezones", activity_id)


@mcp.tool(annotations={"title": "Get Activity Power Zones", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_power_in_timezones(activity_id: str) -> dict:
    """Zeit in Leistungszonen fuer eine Aktivitaet, falls Leistungsmessung vorhanden ist."""
    return await _garmin("get_activity_power_in_timezones", activity_id)


@mcp.tool(annotations={"title": "Get Activity Weather", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_weather(activity_id: str) -> dict:
    """Wetterdaten zu einer Aktivitaet."""
    return await _garmin("get_activity_weather", activity_id)


@mcp.tool(annotations={"title": "Get Activity Gear", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_gear(activity_id: str) -> dict:
    """Ausrustung/Schuhe, die einer Aktivitaet zugeordnet sind."""
    return await _garmin("get_activity_gear", activity_id)


@mcp.tool(annotations={"title": "Get Activity Exercise Sets", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_exercise_sets(activity_id: str) -> dict:
    """Exercise-Sets einer Aktivitaet, vor allem Kraft-/Gym-Workouts."""
    return await _garmin("get_activity_exercise_sets", activity_id)


@mcp.tool(annotations={"title": "Get Last Activity", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_last_activity() -> dict:
    """Die zuletzt synchronisierte Aktivitaet."""
    return await _garmin("get_last_activity")


@mcp.tool(annotations={"title": "Count Activities", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def count_activities() -> int:
    """Anzahl Aktivitaeten im Garmin-Konto."""
    return await _garmin("count_activities")


@mcp.tool(annotations={"title": "Get Activities Page", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activities_page(start: int = 0, limit: int = 20, activitytype: str | None = None) -> dict | list:
    """Aktivitaeten paginiert abrufen. Optional activitytype, z.B. running, cycling."""
    return await _garmin("get_activities", start, limit, activitytype)


@mcp.tool(annotations={"title": "Get Activity By Date", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activities_for_date(date: str | None = None) -> dict:
    """Alle Aktivitaeten an einem bestimmten Datum."""
    return await _garmin("get_activities_fordate", date or _today())


@mcp.tool(annotations={"title": "Get Activity", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity(activity_id: str) -> dict:
    """Basisdaten einer einzelnen Aktivitaet."""
    return await _garmin("get_activity", activity_id)


@mcp.tool(annotations={"title": "Get User Profile", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_user_profile() -> dict:
    """Garmin Benutzerprofil, z.B. Profileinstellungen und UserProfileNumber."""
    return await _garmin("get_user_profile")


@mcp.tool(annotations={"title": "Get User Profile Settings", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_userprofile_settings() -> dict:
    """Garmin Profil- und Sporteinstellungen, inkl. Einheiten und moeglichen Trainingszonen, wenn Garmin sie liefert."""
    return await _garmin("get_userprofile_settings")


@mcp.tool(annotations={"title": "Get Unit System", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_unit_system() -> str | None:
    """Aktuelles Garmin Einheitensystem."""
    return await _garmin("get_unit_system")


@mcp.tool(annotations={"title": "Get Full Name", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_full_name() -> str | None:
    """Im Garmin-Konto hinterlegter Name."""
    return await _garmin("get_full_name")


@mcp.tool(annotations={"title": "Get Devices", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_devices() -> list:
    """Verknuepfte Garmin-Geraete."""
    return await _garmin("get_devices")


@mcp.tool(annotations={"title": "Get Primary Training Device", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_primary_training_device() -> dict:
    """Primaeres Trainingsgeraet."""
    return await _garmin("get_primary_training_device")


@mcp.tool(annotations={"title": "Get Device Last Used", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_device_last_used() -> dict:
    """Zuletzt genutztes Garmin-Geraet."""
    return await _garmin("get_device_last_used")


@mcp.tool(annotations={"title": "Get Device Settings", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_device_settings(device_id: str) -> dict:
    """Einstellungen eines Garmin-Geraets anhand der device_id."""
    return await _garmin("get_device_settings", device_id)


@mcp.tool(annotations={"title": "Get Device Solar Data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_device_solar_data(device_id: str, startdate: str, enddate: str | None = None) -> list:
    """Solar-Daten eines Geraets fuer einen Zeitraum, falls vom Geraet unterstuetzt."""
    return await _garmin("get_device_solar_data", device_id, startdate, enddate)


@mcp.tool(annotations={"title": "Get User Summary", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_user_summary(date: str | None = None) -> dict:
    """Tageszusammenfassung mit Schritten, Kalorien, Distanz, Intensitaet usw."""
    return await _garmin("get_user_summary", date or _today())


@mcp.tool(annotations={"title": "Get Stats", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_stats(date: str | None = None) -> dict:
    """Garmin Tagesstatistik."""
    return await _garmin("get_stats", date or _today())


@mcp.tool(annotations={"title": "Get Stats And Body", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_stats_and_body(date: str | None = None) -> dict:
    """Tagesstatistik plus Body-Daten."""
    return await _garmin("get_stats_and_body", date or _today())


@mcp.tool(annotations={"title": "Get Heart Rates", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_heart_rates(date: str | None = None) -> dict:
    """Herzfrequenzverlauf eines Tages."""
    return await _garmin("get_heart_rates", date or _today())


@mcp.tool(annotations={"title": "Get Resting HR Day", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_rhr_day(date: str | None = None) -> dict:
    """Ruhepuls fuer einen Tag."""
    return await _garmin("get_rhr_day", date or _today())


@mcp.tool(annotations={"title": "Get Respiration Data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_respiration_data(date: str | None = None) -> dict:
    """Atemfrequenzdaten eines Tages."""
    return await _garmin("get_respiration_data", date or _today())


@mcp.tool(annotations={"title": "Get SpO2 Data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_spo2_data(date: str | None = None) -> dict:
    """Pulsoximeter-/Sauerstoffsattigungsdaten eines Tages, falls vorhanden."""
    return await _garmin("get_spo2_data", date or _today())


@mcp.tool(annotations={"title": "Get Body Battery Events", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_body_battery_events(date: str | None = None) -> list:
    """Body-Battery-Ereignisse eines Tages."""
    return await _garmin("get_body_battery_events", date or _today())


@mcp.tool(annotations={"title": "Get All Day Events", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_all_day_events(date: str | None = None) -> dict:
    """Garmin All-Day-Events fuer einen Tag."""
    return await _garmin("get_all_day_events", date or _today())


@mcp.tool(annotations={"title": "Get Stress Data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_stress_data(date: str | None = None) -> dict:
    """Detaillierte Stressdaten eines Tages."""
    return await _garmin("get_stress_data", date or _today())


@mcp.tool(annotations={"title": "Get Steps Data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_steps_data(date: str | None = None) -> list:
    """Schrittdaten eines Tages."""
    return await _garmin("get_steps_data", date or _today())


@mcp.tool(annotations={"title": "Get Daily Steps", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_daily_steps(days: int = 28) -> list:
    """Taegliche Schritte fuer die letzten N Tage."""
    start, end = _daterange(days)
    return await _garmin("get_daily_steps", start, end)


@mcp.tool(annotations={"title": "Get Weekly Steps", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_weekly_steps(weeks: int = 12, end: str | None = None) -> list:
    """Woechentliche Schritte rueckwirkend ab Enddatum."""
    return await _garmin("get_weekly_steps", end or _today(), weeks)


@mcp.tool(annotations={"title": "Get Weekly Stress", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_weekly_stress(weeks: int = 12, end: str | None = None) -> list:
    """Woechentlicher Stress rueckwirkend ab Enddatum."""
    return await _garmin("get_weekly_stress", end or _today(), weeks)


@mcp.tool(annotations={"title": "Get Intensity Minutes", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_intensity_minutes_data(date: str | None = None) -> dict:
    """Intensitaetsminuten fuer einen Tag."""
    return await _garmin("get_intensity_minutes_data", date or _today())


@mcp.tool(annotations={"title": "Get Weekly Intensity Minutes", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_weekly_intensity_minutes(days: int = 28) -> list:
    """Woechentliche Intensitaetsminuten fuer einen Zeitraum."""
    start, end = _daterange(days)
    return await _garmin("get_weekly_intensity_minutes", start, end)


@mcp.tool(annotations={"title": "Get Floors", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_floors(date: str | None = None) -> dict:
    """Stockwerke/Hoehenmeter im Alltag fuer einen Tag."""
    return await _garmin("get_floors", date or _today())


@mcp.tool(annotations={"title": "Get Max Metrics", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_max_metrics(date: str | None = None) -> dict:
    """Garmin Max-Metriken eines Tages, wenn verfuegbar."""
    return await _garmin("get_max_metrics", date or _today())


@mcp.tool(annotations={"title": "Get Fitnessage Data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_fitnessage_data(date: str | None = None) -> dict:
    """Fitnessalter-Daten eines Tages, wenn verfuegbar."""
    return await _garmin("get_fitnessage_data", date or _today())


@mcp.tool(annotations={"title": "Get Lactate Threshold", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_lactate_threshold(latest: bool = True, start_date: str | None = None, end_date: str | None = None, aggregation: str = "daily") -> dict:
    """Laktatschwelle, falls Garmin sie berechnet. Wichtig fuer Pace-/HF-Zonen."""
    return await _garmin("get_lactate_threshold", latest=latest, start_date=start_date, end_date=end_date, aggregation=aggregation)


@mcp.tool(annotations={"title": "Get Cycling FTP", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_cycling_ftp() -> dict | list:
    """Garmin Cycling FTP, falls vorhanden."""
    return await _garmin("get_cycling_ftp")


@mcp.tool(annotations={"title": "Get Endurance Score", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_endurance_score(days: int = 28) -> dict:
    """Garmin Endurance Score fuer einen Zeitraum, falls verfuegbar."""
    start, end = _daterange(days)
    return await _garmin("get_endurance_score", start, end)


@mcp.tool(annotations={"title": "Get Hill Score", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_hill_score(days: int = 28) -> dict:
    """Garmin Hill Score fuer einen Zeitraum, falls verfuegbar."""
    start, end = _daterange(days)
    return await _garmin("get_hill_score", start, end)


@mcp.tool(annotations={"title": "Get Running Tolerance", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_running_tolerance(days: int = 56, aggregation: str = "weekly") -> list:
    """Garmin Running Tolerance / Belastungsvertraeglichkeit, falls verfuegbar."""
    start, end = _daterange(days)
    return await _garmin("get_running_tolerance", start, end, aggregation)


@mcp.tool(annotations={"title": "Get Morning Training Readiness", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_morning_training_readiness(date: str | None = None) -> dict | None:
    """Morning-Report Training Readiness fuer einen Tag, falls verfuegbar."""
    return await _garmin("get_morning_training_readiness", date or _today())


@mcp.tool(annotations={"title": "Get Personal Records", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_personal_record() -> dict:
    """Persoenliche Rekorde aus Garmin."""
    return await _garmin("get_personal_record")


@mcp.tool(annotations={"title": "Get Progress Summary", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_progress_summary_between_dates(startdate: str, enddate: str, metric: str = "distance", groupbyactivities: bool = True) -> dict:
    """Fortschrittszusammenfassung zwischen zwei Daten, z.B. distance, duration, calories."""
    return await _garmin("get_progress_summary_between_dates", startdate, enddate, metric, groupbyactivities)


@mcp.tool(annotations={"title": "Get Race Predictions History", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_race_predictions_history(startdate: str | None = None, enddate: str | None = None, prediction_type: str | None = None) -> dict:
    """Race Predictions optional mit Zeitraum und Typ, falls Garmin historische Werte liefert."""
    return await _garmin("get_race_predictions", startdate, enddate, prediction_type)


@mcp.tool(annotations={"title": "Get Workouts", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_workouts(start: int = 0, limit: int = 100) -> list:
    """Workout-Bibliothek aus Garmin Connect."""
    return await _garmin("get_workouts", start, limit)


@mcp.tool(annotations={"title": "Get Workout By ID", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_workout_by_id(workout_id: str) -> dict:
    """Ein Workout aus der Garmin-Bibliothek anhand der ID."""
    return await _garmin("get_workout_by_id", workout_id)


@mcp.tool(annotations={"title": "Get Scheduled Workout By ID", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_scheduled_workout_by_id(scheduled_workout_id: str) -> dict:
    """Ein geplantes Workout anhand der Scheduled-Workout-ID."""
    return await _garmin("get_scheduled_workout_by_id", scheduled_workout_id)


@mcp.tool(annotations={"title": "Get Training Plans", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_training_plans() -> dict:
    """Garmin Trainingsplaene."""
    return await _garmin("get_training_plans")


@mcp.tool(annotations={"title": "Get Training Plan By ID", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_training_plan_by_id(plan_id: str) -> dict:
    """Garmin Trainingsplan anhand der ID."""
    return await _garmin("get_training_plan_by_id", plan_id)


@mcp.tool(annotations={"title": "Get Adaptive Training Plan By ID", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_adaptive_training_plan_by_id(plan_id: str) -> dict:
    """Adaptiver Garmin Trainingsplan anhand der ID."""
    return await _garmin("get_adaptive_training_plan_by_id", plan_id)


@mcp.tool(annotations={"title": "Get Goals", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_goals(status: str = "active", start: int = 0, limit: int = 30) -> list:
    """Garmin Ziele, z.B. aktive Ziele."""
    return await _garmin("get_goals", status, start, limit)


@mcp.tool(annotations={"title": "Get Gear", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_gear(userProfileNumber: str) -> dict:
    """Ausrustung/Schuhe im Garmin-Konto. userProfileNumber kommt aus get_user_profile."""
    return await _garmin("get_gear", userProfileNumber)


@mcp.tool(annotations={"title": "Get Gear Defaults", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_gear_defaults(userProfileNumber: str) -> dict:
    """Standard-Ausrustung nach Aktivitaetstyp."""
    return await _garmin("get_gear_defaults", userProfileNumber)


@mcp.tool(annotations={"title": "Get Gear Stats", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_gear_stats(gearUUID: str) -> dict:
    """Statistik einer Ausrustung, z.B. Kilometer pro Schuh."""
    return await _garmin("get_gear_stats", gearUUID)


@mcp.tool(annotations={"title": "Get Gear Activities", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_gear_activities(gearUUID: str, limit: int = 1000) -> list:
    """Aktivitaeten, die einer Ausrustung zugeordnet sind."""
    return await _garmin("get_gear_activities", gearUUID, limit)


@mcp.tool(annotations={"title": "Get Body Composition", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_body_composition(days: int = 28) -> dict:
    """Koerperzusammensetzung/Gewicht fuer einen Zeitraum, falls vorhanden."""
    start, end = _daterange(days)
    return await _garmin("get_body_composition", start, end)


@mcp.tool(annotations={"title": "Get Weigh Ins", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_weigh_ins(days: int = 28) -> dict:
    """Gewichtseintraege fuer einen Zeitraum."""
    start, end = _daterange(days)
    return await _garmin("get_weigh_ins", start, end)


@mcp.tool(annotations={"title": "Get Daily Weigh Ins", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_daily_weigh_ins(date: str | None = None) -> dict:
    """Gewichtseintrag eines Tages."""
    return await _garmin("get_daily_weigh_ins", date or _today())


@mcp.tool(annotations={"title": "Get Blood Pressure", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_blood_pressure(days: int = 28) -> dict:
    """Blutdruckdaten fuer einen Zeitraum, falls in Garmin erfasst."""
    start, end = _daterange(days)
    return await _garmin("get_blood_pressure", start, end)


@mcp.tool(annotations={"title": "Get Hydration Data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_hydration_data(date: str | None = None) -> dict:
    """Hydrationsdaten eines Tages, falls erfasst."""
    return await _garmin("get_hydration_data", date or _today())


@mcp.tool(annotations={"title": "Get Lifestyle Logging Data", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_lifestyle_logging_data(date: str | None = None) -> dict:
    """Lifestyle-Logging-Daten eines Tages."""
    return await _garmin("get_lifestyle_logging_data", date or _today())


@mcp.tool(annotations={"title": "Get Nutrition Daily Food Log", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_nutrition_daily_food_log(date: str | None = None) -> dict:
    """Ernaehrungs-/Food-Log eines Tages, falls mit Garmin verbunden."""
    return await _garmin("get_nutrition_daily_food_log", date or _today())


@mcp.tool(annotations={"title": "Get Nutrition Daily Meals", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_nutrition_daily_meals(date: str | None = None) -> dict:
    """Mahlzeiten eines Tages, falls mit Garmin verbunden."""
    return await _garmin("get_nutrition_daily_meals", date or _today())


@mcp.tool(annotations={"title": "Get Nutrition Daily Settings", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_nutrition_daily_settings(date: str | None = None) -> dict:
    """Ernaehrungseinstellungen fuer einen Tag, falls vorhanden."""
    return await _garmin("get_nutrition_daily_settings", date or _today())


@mcp.tool(annotations={"title": "Get Earned Badges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_earned_badges() -> list:
    """Verdiente Garmin Badges."""
    return await _garmin("get_earned_badges")


@mcp.tool(annotations={"title": "Get Available Badges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_available_badges() -> list:
    """Verfuegbare Garmin Badges."""
    return await _garmin("get_available_badges")


@mcp.tool(annotations={"title": "Get In Progress Badges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_in_progress_badges() -> list:
    """Badges in Bearbeitung."""
    return await _garmin("get_in_progress_badges")


@mcp.tool(annotations={"title": "Get Badge Challenges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_badge_challenges(start: int = 0, limit: int = 20) -> dict:
    """Badge Challenges."""
    return await _garmin("get_badge_challenges", start, limit)


@mcp.tool(annotations={"title": "Get Available Badge Challenges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_available_badge_challenges(start: int = 0, limit: int = 20) -> dict:
    """Verfuegbare Badge Challenges."""
    return await _garmin("get_available_badge_challenges", start, limit)


@mcp.tool(annotations={"title": "Get Non Completed Badge Challenges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_non_completed_badge_challenges(start: int = 0, limit: int = 20) -> dict:
    """Nicht abgeschlossene Badge Challenges."""
    return await _garmin("get_non_completed_badge_challenges", start, limit)


@mcp.tool(annotations={"title": "Get Adhoc Challenges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_adhoc_challenges(start: int = 0, limit: int = 20) -> dict:
    """Adhoc Challenges."""
    return await _garmin("get_adhoc_challenges", start, limit)


@mcp.tool(annotations={"title": "Get Inprogress Virtual Challenges", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_inprogress_virtual_challenges(start: int = 0, limit: int = 20) -> dict:
    """Virtuelle Challenges in Bearbeitung."""
    return await _garmin("get_inprogress_virtual_challenges", start, limit)


@mcp.tool(annotations={"title": "Get Activity Types", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_activity_types() -> dict:
    """Garmin Aktivitaetstypen."""
    return await _garmin("get_activity_types")


@mcp.tool(annotations={"title": "Get Raw Garmin Read Tool", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def get_garmin_raw(method_name: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None) -> Any:
    """Whitelist-Zugriff auf weitere reine Lese-Methoden der Python-Bibliothek garminconnect.

    Damit bleiben auch neue/seltene Garmin-Leseendpunkte nutzbar, ohne dass fuer jeden
    Endpunkt ein eigenes MCP-Tool geschrieben werden muss. Schreibende oder loeschende
    Methoden sind hier bewusst gesperrt.
    """
    if method_name not in READ_ONLY_GARMIN_METHODS:
        return {
            "error": "Methode ist nicht in der Read-only-Whitelist freigegeben.",
            "allowed_methods": sorted(READ_ONLY_GARMIN_METHODS),
        }
    return await _garmin(method_name, *(args or []), **(kwargs or {}))


@mcp.tool(annotations={"title": "Schedule Existing Workout", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def schedule_existing_workout(workout_id: str, schedule_date: str) -> dict:
    """Ein bestehendes Garmin-Workout auf ein Datum einplanen."""
    return await _garmin("schedule_workout", workout_id, schedule_date)


@mcp.tool(annotations={"title": "Unschedule Workout", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True})
async def unschedule_workout(scheduled_workout_id: str) -> dict:
    """Ein geplantes Workout aus dem Garmin-Kalender entfernen, ohne das Workout selbst zu loeschen."""
    result = await _garmin("unschedule_workout", scheduled_workout_id)
    return {"unscheduled": scheduled_workout_id, "result": result}

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
    if MCP_AUTO_APPROVE:
        if auth_provider.get_pending(request_id) is None:
            return HTMLResponse("Auto-Freigabe ist aktiv. Bitte den Connector direkt aus Claude verbinden.", status_code=400)
        redirect_url = auth_provider.complete_login(request_id)
        return RedirectResponse(redirect_url, status_code=302)
    return HTMLResponse(LOGIN_PAGE.format(request_id=request_id, error=""))


async def login_post(request: Request):
    form = await request.form()
    request_id = str(form.get("request_id", ""))
    password = str(form.get("password", ""))

    if auth_provider.get_pending(request_id) is None:
        return HTMLResponse("Session abgelaufen. Bitte den Connector in Claude erneut verbinden.", status_code=400)

    if not MCP_AUTO_APPROVE and password != LOGIN_PASSWORD:
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
