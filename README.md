# Garmin MCP Server

Remote-MCP-Server fuer Garmin Connect, damit Claude deine Garmin-Daten lesen und Workouts erstellen/planen kann.

## Was in dieser Version geaendert wurde

- **Keine Passwortabfrage mehr beim Verbinden mit Claude**  
  `MCP_AUTO_APPROVE=true` gibt die Claude-Verbindung automatisch frei.

- **Claude bleibt deutlich stabiler verbunden**  
  OAuth-Clients und Tokens werden nicht mehr nur im RAM gespeichert, sondern in eine JSON-Datei geschrieben:  
  `TOKEN_STORE_PATH=/var/data/mcp_oauth_store.json`

- **Tokens laufen viel laenger**  
  Access Tokens sind neu 365 Tage gueltig.

- **Render ist auf Always-on ausgelegt**  
  `render.yaml` ist auf `plan: starter` gestellt und nutzt eine persistente Disk unter `/var/data`.

## Wichtig

Ganz ohne Passwort ist bequemer, aber weniger geschuetzt. Jeder, der deine Render-URL kennt und einen OAuth-Flow startet, koennte theoretisch Zugriff freigeben. Verwende deshalb ein **privates GitHub-Repo** und teile die Render-URL nicht oeffentlich.

„Immer verbunden“ funktioniert zuverlaessig nur, wenn Render den Dienst nicht staendig schlafen legt und die Token-Datei erhalten bleibt. Darum ist in `render.yaml` ein **Starter/Always-on Plan mit persistenter Disk** vorgesehen. Auf dem Free Plan kann Render den Dienst trotzdem schlafen legen oder neu starten; dann kann Claude je nach Situation wieder eine Neuverbindung brauchen.

## Render Environment Variables

Setze in Render diese Werte:

```text
GARMIN_EMAIL=deine Garmin E-Mail
GARMIN_PASSWORD=dein Garmin Passwort
ISSUER_URL=https://deine-render-url.onrender.com
MCP_AUTO_APPROVE=true
TOKEN_STORE_PATH=/var/data/mcp_oauth_store.json
```

`MCP_LOGIN_PASSWORD` ist nur noch noetig, wenn du die Passwortabfrage wieder aktivieren willst.

## Passwortabfrage wieder aktivieren

Falls du spaeter wieder ein Login-Passwort willst:

```text
MCP_AUTO_APPROVE=false
MCP_LOGIN_PASSWORD=dein eigenes Passwort
```

Danach Render neu deployen.

## Deployment

1. Dateien in dein privates GitHub-Repo hochladen.
2. Render Web Service mit dem Repo verbinden.
3. Environment Variables setzen.
4. Nach dem ersten Deploy die definitive Render-URL als `ISSUER_URL` eintragen.
5. Neu deployen.
6. In Claude den Custom Connector mit dieser URL verbinden:

```text
https://DEINE-URL.onrender.com/mcp
```

Claude sollte nun ohne Passwortabfrage durchverbinden.

## Verfuegbare Tools

Diese Version enthaelt deutlich mehr Garmin-Tools. Die wichtigsten Tools fuer deinen Laufplan sind weiterhin direkt verfuegbar; zusaetzlich gibt es viele Detail-, Analyse-, Profil-, Geraete-, Gesundheits-, Gear- und Planungsfunktionen.

### Basis fuer Trainingsplanung

- `get_full_export`
- `get_activities`
- `get_training_status`
- `get_training_readiness`
- `get_morning_training_readiness`
- `get_race_predictions`
- `get_race_predictions_history`
- `get_sleep`
- `get_hrv`
- `get_body_battery`
- `get_stress`
- `get_user_summary`
- `get_stats`
- `get_stats_and_body`

### Aktivitaeten und Detailanalyse

- `count_activities`
- `get_activities_page`
- `get_activities_for_date`
- `get_activity`
- `get_activity_details`
- `get_activity_splits`
- `get_activity_split_summaries`
- `get_activity_typed_splits`
- `get_activity_hr_in_timezones`
- `get_activity_power_in_timezones`
- `get_activity_weather`
- `get_activity_gear`
- `get_activity_exercise_sets`
- `get_last_activity`
- `get_activity_types`

### Form, Zonen und Leistungsmetriken

- `get_lactate_threshold`
- `get_cycling_ftp`
- `get_endurance_score`
- `get_hill_score`
- `get_running_tolerance`
- `get_personal_record`
- `get_progress_summary_between_dates`
- `get_max_metrics`
- `get_fitnessage_data`

### Gesundheit, Erholung und Alltag

- `get_heart_rates`
- `get_rhr_day`
- `get_respiration_data`
- `get_spo2_data`
- `get_body_battery_events`
- `get_all_day_events`
- `get_stress_data`
- `get_steps_data`
- `get_daily_steps`
- `get_weekly_steps`
- `get_weekly_stress`
- `get_intensity_minutes_data`
- `get_weekly_intensity_minutes`
- `get_floors`
- `get_body_composition`
- `get_weigh_ins`
- `get_daily_weigh_ins`
- `get_blood_pressure`
- `get_hydration_data`
- `get_lifestyle_logging_data`
- `get_nutrition_daily_food_log`
- `get_nutrition_daily_meals`
- `get_nutrition_daily_settings`

### Profil, Geraete und Ausruestung

- `get_user_profile`
- `get_userprofile_settings`
- `get_unit_system`
- `get_full_name`
- `get_devices`
- `get_primary_training_device`
- `get_device_last_used`
- `get_device_settings`
- `get_device_solar_data`
- `get_gear`
- `get_gear_defaults`
- `get_gear_stats`
- `get_gear_activities`

### Workouts, Kalender und Trainingsplaene

- `get_scheduled_workouts`
- `get_scheduled_workout_by_id`
- `get_workouts`
- `get_workout_by_id`
- `get_training_plans`
- `get_training_plan_by_id`
- `get_adaptive_training_plan_by_id`
- `get_goals`
- `create_interval_workout`
- `create_easy_run`
- `create_custom_workout`
- `schedule_existing_workout`
- `unschedule_workout`
- `delete_workout`

### Badges und Challenges

- `get_earned_badges`
- `get_available_badges`
- `get_in_progress_badges`
- `get_badge_challenges`
- `get_available_badge_challenges`
- `get_non_completed_badge_challenges`
- `get_adhoc_challenges`
- `get_inprogress_virtual_challenges`

### Fallback fuer seltene Garmin-Leseendpunkte

- `get_garmin_raw`

`get_garmin_raw` ist bewusst nur fuer freigegebene Read-only-Methoden gedacht. Loeschende oder schreibende Garmin-Methoden sind dort nicht erlaubt.

## Lokal testen

```bash
pip install -r requirements.txt
ISSUER_URL=http://localhost:8000 MCP_AUTO_APPROVE=true python server.py
```

Health Check:

```text
http://localhost:8000/health
```
