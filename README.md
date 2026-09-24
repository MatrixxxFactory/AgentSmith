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
  zeit.py                 Öffnungszeiten, Sonderzeiten, "ist offen?", Sprechformat
  prompt.py               Systemprompt aus Profil + aktiven Modulen (bewusst kompakt)
  rezeptionist.py         Der Agent: Begrüßung, Module, Anruf beenden
  benachrichtigung.py     Webhook bei Buchung/Absage/Rückruf (→ n8n, Make, Zapier)
  module/                 Fähigkeiten, je Profil an- und abschaltbar
    info.py               Öffnungszeiten an einem Datum, FAQ-Suche bei großem Wissen
    termine.py            Freie Zeiten, buchen, eigene Termine finden, absagen
    rueckruf.py           Rückrufbitten/Nachrichten aufnehmen
    weiterleitung.py      Weiterleitung an einen Menschen per SIP REFER
  speicher/               Schnittstellen + JSON-Ablage (austauschbar gegen echten Kalender)
tests/                    Unit-Tests (ohne LLM) und Verhaltenstests (mit LLM)
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
| Sprachausgabe | `fishaudio/s2.1-pro` | ja; Alternative: `cartesia/sonic-3` |

Die Standardstimme stammt aus der englischen Vorlage. Für einen natürlichen Klang eine
deutsche Stimme auf [fish.audio](https://fish.audio) wählen und ihre ID bei `stimme.voice` eintragen.

## Telefonie

1. Rufnummer über LiveKit Phone Numbers oder einen SIP-Trunk (z. B. Twilio, Plivo, sipgate) anbinden:
   [Telefonie-Doku](https://docs.livekit.io/telephony/)
2. Dispatch-Regel auf den Agentennamen `agent-smith` zeigen lassen
3. Nummer in `telefonnummern` des Profils eintragen
4. Für Weiterleitungen muss der Trunk SIP REFER erlauben ([Anleitung](https://docs.livekit.io/telephony/features/transfers/cold/))

## Tests

```bash
python -m uv run pytest                    # alles; LLM-Tests nur mit .env.local
python -m uv run ruff format; python -m uv run ruff check
lk agent simulate --scenarios scenarios.yaml   # ganze Anrufe simulieren (kostet Inference)
```

Die Unit-Tests nutzen einen festen "Jetzt"-Zeitpunkt (Di, 29.09.2026, 8 Uhr) und laufen ohne Netz.

## Rechtliches (vor dem Echtbetrieb klären)

- Anrufer darauf hinweisen, dass sie mit einer KI sprechen (Begrüßung im Profil)
- Anrufprotokolle enthalten personenbezogene Daten: Aufbewahrungsfrist festlegen, Datenschutzerklärung anpassen,
  Auftragsverarbeitungsverträge mit LiveKit und den Modellanbietern abschließen
- Für EU-Datenhaltung LiveKit-Inference-Modelle mit EU-Endpunkt bevorzugen

## Deployment

Das mitgelieferte `Dockerfile` ist produktionsreif:
[Deployment auf LiveKit Cloud](https://docs.livekit.io/deploy/agents/) mit `lk agent deploy`.
Für den Betrieb mit mehreren Agent-Prozessen die JSON-Ablage durch einen echten Kalender
oder eine Datenbank ersetzen (`src/smith/speicher/`).

## Lizenz

MIT – siehe [LICENSE](LICENSE). Basiert auf dem LiveKit Agents Starter für Python.
