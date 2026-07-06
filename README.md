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

Lesen:

- `get_activities`
- `get_training_status`
- `get_training_readiness`
- `get_race_predictions`
- `get_sleep`
- `get_hrv`
- `get_body_battery`
- `get_stress`
- `get_scheduled_workouts`
- `get_full_export`

Schreiben:

- `create_interval_workout`
- `create_easy_run`
- `create_custom_workout`
- `delete_workout`

## Lokal testen

```bash
pip install -r requirements.txt
ISSUER_URL=http://localhost:8000 MCP_AUTO_APPROVE=true python server.py
```

Health Check:

```text
http://localhost:8000/health
```
