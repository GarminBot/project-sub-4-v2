# Garmin MCP Server

Echter Remote-MCP-Server für Garmin Connect (Streamable HTTP + eigener
OAuth-2.1-Mini-Server). Damit kann Claude direkt als "Custom Connector"
(Claude-Einstellungen → Connectors) angebunden werden – funktioniert dann in
claude.ai, Claude Desktop, Mobile und Cowork gleichermassen, und Claude kann
sowohl Daten lesen als auch (richtig, per Tool-Call statt GET-Trick) Workouts
erstellen.

## Dein Login-Passwort

```
x-kg927YDuER31Q2YN6EiYxv1mqWhcDd
```

Das ist NICHT dein Garmin-Passwort, sondern das Passwort für die Login-Seite
des MCP-Servers selbst (die du einmalig beim Verbinden im Browser siehst).
Halte es geheim, nicht auf GitHub committen.

## 1. Code auf GitHub bringen

Gleich wie beim letzten Mal (siehe vorheriges README), z.B. über die
GitHub-Weboberfläche: neues **privates** Repo erstellen, alle Dateien aus
`garmin_mcp/` hochladen (ausser `.env`, falls vorhanden).

## 2. Web Service auf Render.com erstellen

1. **New → Web Service**, dein Repo verbinden
2. Einstellungen:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn server:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** Free
3. **Environment Variables** hinzufügen:
   - `GARMIN_EMAIL` = deine Garmin-Login-Email
   - `GARMIN_PASSWORD` = dein Garmin-Passwort
   - `MCP_LOGIN_PASSWORD` = das Passwort von oben
   - `ISSUER_URL` = **musst du nach dem ersten Deploy nachtragen** (siehe Schritt 3)
4. **Create Web Service**

## 3. ISSUER_URL nachtragen (wichtig!)

Render gibt dir erst nach dem ersten Deploy deine endgültige URL, z.B.
`https://garmin-mcp-xyz1.onrender.com`. Diese URL musst du:

1. Als `ISSUER_URL` in die Environment Variables eintragen (ohne Slash am Ende!)
2. Danach: **Manual Deploy → Deploy latest commit**, damit der Server mit der
   korrekten URL neu startet (der OAuth-Server muss seine eigene URL kennen,
   um korrekte Redirect-Links zu bauen).

## 4. Als Custom Connector in Claude verbinden

1. Claude-Einstellungen → **Connectors** → **Add custom connector**
2. URL eintragen: `https://DEINE-URL.onrender.com/mcp`
3. **Connect** klicken → du wirst zu deiner eigenen Login-Seite weitergeleitet
4. Passwort (von oben) eingeben → **Freigeben**
5. Claude zeigt "Connected" – fertig

Danach kannst du den Connector pro Chat über den "+"-Button unten links
(„Connectors") ein-/ausschalten.

## 5. Dauerhafte Verbindung einrichten (Upstash Redis)

**Warum das nötig ist:** Ohne diesen Schritt gehen alle Verbindungen bei jedem
Render-Neustart verloren (Cold-Start nach 15 Min. Inaktivität, oder Redeploy) -
du müsstest den Connector in Claude dann jedes Mal neu verbinden. Mit Upstash
bleibt die Verbindung dauerhaft bestehen, genau wie bei Strava.

1. Gratis-Account auf **upstash.com** erstellen (keine Kreditkarte nötig)
2. **Create Database** → Typ **Redis** → Region möglichst nah an deiner Render-Region wählen
3. Auf der Datenbank-Seite unter **REST API** findest du zwei Werte:
   - `UPSTASH_REDIS_REST_URL`
   - `UPSTASH_REDIS_REST_TOKEN`
4. Beide als Environment Variables in deinem Render Web Service eintragen
   (gleiche Stelle wie `GARMIN_EMAIL` etc.)
5. Render deployed automatisch neu

Danach bleiben Client-Registrierung, Access-Token und Refresh-Token dauerhaft
gespeichert - ein Neustart des Render-Prozesses hat keinen Einfluss mehr auf
eine bestehende Claude-Verbindung. Falls du diesen Schritt auslässt, läuft
alles trotzdem (Fallback auf In-Memory-Speicherung), nur eben mit dem
"jedes Mal neu verbinden"-Problem.

## Wichtige Einschränkungen (Free Tier)

- **Cold Start:** 30–60 Sekunden nach 15 Minuten Inaktivität, wie beim letzten
  Server auch.
- **Sessions gehen bei Neustart verloren, falls Upstash nicht eingerichtet
  ist** (siehe Schritt 5): ohne Upstash liegen OAuth-Tokens nur im
  Arbeitsspeicher, dann musst du den Connector nach jedem Neustart neu
  verbinden. Mit Upstash (empfohlen, kostenlos) bleibt die Verbindung
  dauerhaft bestehen.
- **2FA:** bleibt aus (wie besprochen), sonst müsste der Server interaktiv
  einen Code abfragen können, was bei einem automatischen Login nicht geht.

## Für deinen Vater: komplett separate zweite Instanz

Einfachste und sauberste Lösung – **kein gemeinsamer Code, keine gemeinsame
Instanz:**

1. Denselben Ordner (`garmin_mcp/`) in ein zweites, ebenfalls privates
   GitHub-Repo hochladen (z.B. `garmin-mcp-papa`)
2. Zweiten Web Service auf Render erstellen, mit **seinen** Zugangsdaten:
   - `GARMIN_EMAIL` / `GARMIN_PASSWORD` = seine Garmin-Zugangsdaten
   - `MCP_LOGIN_PASSWORD` = ein neues, eigenes Passwort für ihn
   - `ISSUER_URL` = seine eigene Render-URL
3. Er verbindet diese zweite URL als eigenen Custom Connector in **seinem
   eigenen** Claude-Account

Die beiden Instanzen haben keinerlei Berührungspunkte – dein Server sieht nie
seine Garmin-Daten und umgekehrt. Du müsstest ihm nur beim einmaligen Setup
helfen (Render-Account, GitHub-Repo), das kannst du 1:1 nach dieser Anleitung
für ihn wiederholen.

## Verfügbare Tools

**Lesen:**
`get_activities`, `get_training_status`, `get_training_readiness`,
`get_race_predictions`, `get_sleep`, `get_hrv`, `get_body_battery`,
`get_stress`, `get_scheduled_workouts`, `get_full_export`

**Schreiben:**
`create_interval_workout`, `create_easy_run`, `create_custom_workout`,
`delete_workout`

Alle Tools sind vollständig dokumentiert (Docstrings), Claude sieht die
Beschreibungen automatisch beim Verbinden und weiss, wie es sie einsetzt.

## Lokal testen (optional, vor dem Deployment)

```bash
pip install -r requirements.txt
# .env-Datei anlegen (siehe .env.example), ISSUER_URL=http://localhost:8000
python server.py
```

Dann im Browser: `http://localhost:8000/.well-known/oauth-authorization-server`
sollte JSON zurückgeben. Den kompletten Verbindungs-Flow kannst du aber nur
über einen echten Claude-Connector oder den MCP Inspector (`npx
@modelcontextprotocol/inspector`) end-to-end testen.
