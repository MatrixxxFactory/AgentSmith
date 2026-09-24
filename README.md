# Agent Smith – KI-Telefonagent für kleine Betriebe

Ein modularer Voice-AI-Telefonagent auf Basis von [LiveKit Agents](https://github.com/livekit/agents).
Er nimmt Anrufe entgegen, beantwortet Fragen, vergibt Termine, notiert Rückrufe und
leitet an Menschen weiter – auf Deutsch.

**Die Branche ist austauschbar:** Der Code kennt keinen Friseur und keinen Handwerker.
Alles Betriebsspezifische steht in einer YAML-Datei unter [`profile/`](profile/).
Neue Zielgruppe = neue Profildatei, kein Code.

## Aufbau

```
profile/                  Ein Betrieb pro YAML-Datei (Branche, Zeiten, Leistungen, Module …)
  _vorlage.yaml           Kommentierte Vorlage für neue Profile
src/agent.py              LiveKit-Einstieg: wählt Profil, baut Sprach-Pipeline
src/smith/
  profil.py               Profil-Schema (pydantic) – Tippfehler im YAML fallen sofort auf
  zeit.py                 Öffnungszeiten, Sonderzeiten, gesetzliche Feiertage, Sprechformat
  prompt.py               Systemprompt aus Profil + aktiven Modulen (bewusst kompakt)
  rezeptionist.py         Der Agent: Begrüßung, Module, Anruf beenden
  benachrichtigung.py     Push (ntfy), E-Mail, Webhook bei Buchung/Absage/Rückruf – im Hintergrund
  module/                 Fähigkeiten, je Profil an- und abschaltbar
    info.py               Öffnungszeiten an einem Datum, FAQ-Suche bei großem Wissen
    termine.py            Freie Zeiten, buchen, eigene Termine finden, absagen
    rueckruf.py           Rückrufbitten/Nachrichten aufnehmen
    weiterleitung.py      Weiterleitung an einen Menschen per SIP REFER
  speicher/               Schnittstellen, JSON-Ablage und Google Calendar
tests/                    Unit-Tests (ohne LLM) und Verhaltenstests (mit LLM)
telefonie/                Weiterleitungsregel + Skript zum Verbinden einer Rufnummer
scenarios.yaml            Ganze simulierte Anrufe (lk agent simulate)
```

Mitgelieferte Beispielprofile:

| Profil | Branche | Besonderheit |
|---|---|---|
| `friseur-schnittpunkt` | Friseursalon | 2 Stühle parallel, Stornoregeln |
| `handwerk-sanitaer-mueller` | Sanitär/Heizung | Notfälle (Gas, Rohrbruch), Weiterleitung rund um die Uhr |
| `physio-bewegt` | Physiotherapie | Keine medizinische Beratung, Hinweis auf 112/116 117 |
| `restaurant-luna` | Restaurant | Tischreservierung über das Terminmodul |

## Einrichtung

Voraussetzungen: Python 3.10+, [uv](https://docs.astral.sh/uv/), [LiveKit CLI](https://docs.livekit.io/intro/basics/cli/) (`winget install LiveKit.LiveKitCLI`).

```bash
python -m uv sync
python -m uv run python src/agent.py download-files
lk cloud auth
lk app env --write --destination .env.local
```

## Benutzen

**Am einfachsten (Windows):** Doppelklick auf `Agent Smith starten.bat`, Betrieb auswählen.
Nach ein paar Sekunden öffnet sich der LiveKit-Browser-Playground: auf *Start* klicken,
Mikrofon erlauben, lossprechen.

Oder im Terminal:

```bash
# Im Terminal mit dem Agenten sprechen (Standardprofil)
lk agent console

# Bestimmtes Profil (PowerShell: $env:SMITH_PROFIL="handwerk-sanitaer-mueller")
SMITH_PROFIL=handwerk-sanitaer-mueller lk agent console

# Für Web-Playground und Telefonie, mit Hot Reload
lk agent dev
```

Welches Profil antwortet?
1. Bei Telefonanrufen: das Profil, dessen `telefonnummern` die gewählte Nummer enthält.
   So bedient **ein** Agent beliebig viele Betriebe.
2. Sonst das Profil aus der Umgebungsvariable `SMITH_PROFIL`.
3. Sonst das alphabetisch erste Profil.

Termine, Rückrufe und Anrufprotokolle landen unter `daten/<profil-id>/` (per `.gitignore`
ausgeschlossen, da personenbezogen).

## Neuen Betrieb / neue Branche anlegen

1. `profile/_vorlage.yaml` kopieren, z. B. nach `profile/kosmetik-anna.yaml`
2. Firma, Begrüßung, Öffnungszeiten, Leistungen, FAQ, Regeln ausfüllen
3. Module an-/abschalten (`termine`, `rueckruf`, `weiterleitung`)
4. `python -m uv run pytest` – prüft u. a., dass jedes Profil gültig ist
5. `SMITH_PROFIL=kosmetik-anna lk agent console` und ausprobieren

## Neues Modul entwickeln

1. Datei in `src/smith/module/` anlegen, Klasse von `Modul` ableiten
2. `ist_aktiv(profil)` – wann läuft das Modul mit (meist ein Schalter im Profil)
3. `anweisungen()` – ein kurzer Absatz für den Prompt: wann welches Tool
4. Tools mit `@function_tool` als Methoden; Zugriff auf alles über `self.k` (`AnrufKontext`)
5. In `ALLE_MODULE` in `src/smith/module/__init__.py` eintragen, Schalter in `profil.py` ergänzen
6. Tests in `tests/test_module.py` schreiben (Tools lassen sich direkt aufrufen)

Ideen für weitere Module: Google Calendar / Cal.com als `Kalender`, SMS-Bestätigung,
Bestellannahme, Auftragsstatus aus einer Warenwirtschaft, mehrsprachige Anrufer.

## Stimme und Modelle

Pro Profil einstellbar unter `stimme:`. Standard über LiveKit Inference (keine eigenen API-Keys nötig):

| Baustein | Standard | Deutsch |
|---|---|---|
| Spracherkennung | `assemblyai/universal-3-5-pro` | ja (`de`, `de-AT`, `de-CH`) |
| Sprachmodell | `google/gemma-4-31b-it` | ja |
| Sprachausgabe | `gradium/default` (Sprecher Annika / Mats) | ja, native deutsche Stimmen |

Stimme wählen: `stimme: {sprecher: annika}` (weiblich) oder `mats` (männlich). Beide sind offizielle
deutsche Kundenservice-Stimmen von Gradium und beginnen nach ~0,4–0,5 s zu sprechen (die Fish-Audio-Stimme
der Vorlage brauchte ~1,3 s). Weitere Sprecher in `SPRECHER` in `src/smith/profil.py` eintragen; eine
beliebige Stimme geht auch direkt über `tts:` + `voice:`
([Gradium-Stimmen](https://docs.gradium.ai/guides/voices/flagship-voices)).

## Benachrichtigungen

Bei jeder Buchung, Absage, Rückrufbitte und Weiterleitung bekommt der Betrieb eine kurze
Nachricht. Der Versand läuft im Hintergrund, ein langsamer Dienst bremst nie das Gespräch.
Alle Werte gehören in `.env.local` (Vorlage: `.env.example`), **nie** ins Profil – das Repo ist öffentlich.

| Kanal | Einstellungen | Hinweis |
|---|---|---|
| Push aufs Handy | `SMITH_NTFY_THEMA` | App [ntfy](https://ntfy.sh) installieren, Thema abonnieren. Das Thema wirkt wie ein Passwort. |
| E-Mail | `SMITH_EMAIL_AN`, `SMITH_SMTP_SERVER`, `…_PORT`, `…_BENUTZER`, `…_PASSWORT` | z. B. GMX: `mail.gmx.net`, Port 587 |
| Webhook | `SMITH_WEBHOOK_URL` | JSON an n8n/Make/Zapier, z. B. für WhatsApp oder Slack |

Mehrere Betriebe? Jeder Wert lässt sich pro Profil überschreiben: `SMITH_<PROFIL>_<NAME>`,
z. B. `SMITH_HANDWERK_SANITAER_MUELLER_NTFY_THEMA`.

Datenschutz: ntfy.sh ist ein öffentlicher Dienst. Für den Echtbetrieb mit Kundendaten einen
eigenen ntfy-Server (`SMITH_NTFY_SERVER`) oder E-Mail verwenden.

## Google Calendar

Mit `kalender: {art: google}` im Profil landen Termine direkt im Google Calendar des Betriebs.
Einträge, die der Betrieb selbst anlegt, blockieren Zeiten: ganztägige (Urlaub) den ganzen Tag,
Einträge mit „Verfügbarkeit: frei“ gar nicht.

Einmalige Einrichtung (etwa 10 Minuten):
1. [Google Cloud Console](https://console.cloud.google.com/) → neues Projekt → **Google Calendar API** aktivieren
2. *IAM & Verwaltung → Dienstkonten* → Dienstkonto anlegen → *Schlüssel → JSON* herunterladen
3. Die Datei sicher ablegen, z. B. `C:\Users\<du>\.agentsmith\dienstkonto.json` (nicht ins Repo!)
4. In Google Calendar: Kalender → *Einstellungen und Freigabe* → *Für bestimmte Personen freigeben*
   → E-Mail-Adresse des Dienstkontos (`…@….iam.gserviceaccount.com`) mit
   **„Änderungen an Terminen vornehmen“**
5. Unter *Kalender integrieren* die **Kalender-ID** kopieren
6. In `.env.local`:
   ```
   SMITH_GOOGLE_KALENDER_ID=…@group.calendar.google.com
   SMITH_GOOGLE_DIENSTKONTO=C:\Users\<du>\.agentsmith\dienstkonto.json
   ```
   Für die Cloud statt des Pfads den kompletten Dateiinhalt eintragen (eine Zeile JSON).

## Telefonie

LiveKit verkauft selbst nur US-Nummern. Deutsche Nummern kommen über einen SIP-Anbieter
(z. B. sipgate trunking, Telnyx, Twilio, easybell):

1. Beim Anbieter eine Nummer buchen und eingehende Anrufe an die **SIP URI** deines
   LiveKit-Projekts leiten (LiveKit Cloud → *Settings* → *Project*)
2. Nummer mit LiveKit verbinden:
   ```bash
   powershell -ExecutionPolicy Bypass -File telefonie\nummer-verbinden.ps1 -Nummer +4930123456
   ```
3. Nummer in `telefonnummern:` des passenden Profils eintragen
4. Die Weiterleitungsregel zum Agenten `agent-smith` ([`telefonie/dispatch-regel.json`](telefonie/dispatch-regel.json))
   gilt für alle Nummern; angelegt mit `lk sip dispatch create telefonie/dispatch-regel.json`
5. Der Agent muss laufen: lokal per Startdatei oder dauerhaft in der Cloud (siehe Deployment)
6. Für Weiterleitungen an Mitarbeiter muss der Anbieter SIP REFER erlauben
   ([Anleitung](https://docs.livekit.io/telephony/features/transfers/cold/))

## Tests

```bash
python -m uv run pytest                    # alles; LLM-Tests nur mit .env.local
python -m uv run ruff format; python -m uv run ruff check
```

Die Unit-Tests nutzen einen festen "Jetzt"-Zeitpunkt (Di, 29.09.2026, 8 Uhr) und laufen ohne Netz.

**Ganze Anrufe simulieren** (kostet etwas LiveKit-Inference): Agent mit dem passenden Profil
starten (Startdatei oder `lk agent dev`), dann

```bash
lk agent simulate text --scenarios scenarios.yaml --agent-name agent-smith
```

`scenarios.yaml` enthält 10 Friseur-Anrufe (Buchung, Korrektur, Absage, Feiertag, englischer
Anrufer, Manipulationsversuch …), `scenarios-handwerk.yaml` 4 Sanitär-Anrufe (Gasgeruch,
Rohrbruch, Wartung, Kostenvoranschlag). Achtung: Der Prüfer der Simulation urteilt nicht
immer richtig – bei "failed" das Gespräch im Agent-Log nachlesen.

### Schutzmechanismen, die nicht vom Sprachmodell abhängen

Aus Tests mit echten und simulierten Anrufen; alle im Code erzwungen und getestet:

| Problem | Schutz |
|---|---|
| Modell verrechnet Wochentage ("Mittwoch" → Donnerstag) | Tools prüfen den genannten Wochentag gegen das Datum |
| Modell fragt "Soll ich buchen?" und bucht sofort | Buchen/Absagen zweistufig: erst vorlesen, ausgeführt erst nach einer Antwort des Anrufers |
| Modell sagt "gebucht" und legt auf, obwohl nur vorgemerkt | Auflegen wird dann einmal verweigert |
| "unbekannt" als Telefonnummer, "Unbekannt" als Name | Werden abgelehnt; dringende Nachrichten gehen notfalls ohne Nummer raus |
| Termine an Feiertagen | Gesetzliche Feiertage je Bundesland automatisch geschlossen |
| Agent startet nicht (gegenseitiges Warten, Absturz unter Last) | Anrufer-Erkennung per Server-API mit Zeitlimit, Start-Reihenfolge wie LiveKit-Vorlage |
| Englisches "Nachdenken" nach dem Auflegen | Kein Nachsatz nach `end_call` |

## Rechtliches (vor dem Echtbetrieb klären)

- Anrufer darauf hinweisen, dass sie mit einer KI sprechen (Begrüßung im Profil)
- Anrufprotokolle enthalten personenbezogene Daten: Aufbewahrungsfrist festlegen, Datenschutzerklärung anpassen,
  Auftragsverarbeitungsverträge mit LiveKit und den Modellanbietern abschließen
- Für EU-Datenhaltung LiveKit-Inference-Modelle mit EU-Endpunkt bevorzugen

## Deployment

Das mitgelieferte `Dockerfile` ist produktionsreif:
[Deployment auf LiveKit Cloud](https://docs.livekit.io/deploy/agents/) mit `lk agent deploy`.
Vorher `kalender: {art: google}` nutzen – die JSON-Ablage liegt in der Cloud nur im
flüchtigen Container. Die Werte aus `.env.local` als Secrets mitgeben
(`lk agent update-secrets`), das Google-Dienstkonto dabei als JSON-Inhalt statt als Pfad.

## Lizenz

MIT – siehe [LICENSE](LICENSE). Basiert auf dem LiveKit Agents Starter für Python.
