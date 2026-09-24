import asyncio
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from smith import benachrichtigung as b
from smith.benachrichtigung import (
    Benachrichtiger,
    EmailKanal,
    NtfyKanal,
    WebhookKanal,
    einstellung,
    kanaele_fuer,
    meldung_bauen,
)

TERMIN = {
    "leistung": "Damenhaarschnitt",
    "beginn": "2026-09-29T15:00:00+02:00",
    "ende": "2026-09-29T16:00:00+02:00",
    "name": "Julia Neumann",
    "telefon": "0151 23456789",
    "notiz": "Spitzen schneiden",
}


@pytest.fixture(autouse=True)
def _saubere_umgebung(monkeypatch):
    # .env.local (von test_agent.py geladen) darf diese Tests nicht beeinflussen
    import os

    for schluessel in list(os.environ):
        if schluessel.startswith(("SMITH_", "SMTP_")):
            monkeypatch.delenv(schluessel)


# --- Texte ------------------------------------------------------------------


def test_meldung_termin(friseur):
    m = meldung_bauen(friseur, "termin_gebucht", TERMIN)
    assert m.titel == "Neuer Termin – Salon Schnittpunkt"
    assert m.text.splitlines() == [
        "Damenhaarschnitt",
        "Dienstag, 29.09.2026 um 15:00 Uhr",
        "Julia Neumann, 0151 23456789",
        "Notiz: Spitzen schneiden",
    ]
    assert not m.dringend


def test_meldung_dringender_rueckruf(handwerk):
    m = meldung_bauen(
        handwerk,
        "rueckruf",
        {"name": "Tom", "telefon": "0170 1", "anliegen": "Rohrbruch", "dringend": True},
    )
    assert m.titel.startswith("DRINGEND: Rückrufbitte")
    assert "Rohrbruch" in m.text
    assert m.dringend


def test_zeit_wird_in_zeitzone_des_betriebs_angezeigt(friseur):
    utc = {**TERMIN, "beginn": "2026-09-29T13:00:00+00:00"}
    assert "15:00 Uhr" in meldung_bauen(friseur, "termin_gebucht", utc).text


# --- Einstellungen ------------------------------------------------------------


def test_einstellung_pro_profil_hat_vorrang(friseur, handwerk, monkeypatch):
    monkeypatch.setenv("SMITH_NTFY_THEMA", "allgemein")
    monkeypatch.setenv("SMITH_FRISEUR_SCHNITTPUNKT_NTFY_THEMA", "salon")
    assert einstellung(friseur, "NTFY_THEMA") == "salon"
    assert einstellung(handwerk, "NTFY_THEMA") == "allgemein"


def test_kanaele_nach_konfiguration(friseur, monkeypatch):
    assert kanaele_fuer(friseur) == []

    monkeypatch.setenv("SMITH_NTFY_THEMA", "geheim123")
    monkeypatch.setenv("SMITH_EMAIL_AN", "chef@example.de")
    # E-Mail ohne SMTP-Zugang wird übersprungen, statt später zu scheitern
    assert [k.name for k in kanaele_fuer(friseur)] == ["ntfy"]

    for s, w in {
        "SMITH_SMTP_SERVER": "mail.example.de",
        "SMITH_SMTP_BENUTZER": "bot@example.de",
        "SMITH_SMTP_PASSWORT": "x",
        "SMITH_WEBHOOK_URL": "https://hook.example.de",
    }.items():
        monkeypatch.setenv(s, w)
    assert [k.name for k in kanaele_fuer(friseur)] == ["ntfy", "email", "webhook"]


# --- Kanäle gegen echten lokalen Server ----------------------------------------


@pytest.fixture
async def empfaenger():
    erhalten: list[dict] = []

    async def annehmen(anfrage: web.Request) -> web.Response:
        erhalten.append(
            {
                "pfad": anfrage.path,
                "json": await anfrage.json(),
                "auth": anfrage.headers.get("Authorization"),
            }
        )
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/{pfad:.*}", annehmen)
    server = TestServer(app)
    await server.start_server()
    yield str(server.make_url("/")).rstrip("/"), erhalten
    await server.close()


async def test_ntfy_kanal(friseur, empfaenger):
    url, erhalten = empfaenger
    meldung = meldung_bauen(friseur, "termin_gebucht", TERMIN)
    await NtfyKanal(url, "mein-thema", token="tk").zustellen(friseur, meldung)
    daten = erhalten[0]["json"]
    assert daten["topic"] == "mein-thema"
    assert daten["title"] == "Neuer Termin – Salon Schnittpunkt"
    assert daten["priority"] == 3
    assert erhalten[0]["auth"] == "Bearer tk"


async def test_webhook_kanal(friseur, empfaenger):
    url, erhalten = empfaenger
    meldung = meldung_bauen(friseur, "termin_gebucht", TERMIN)
    await WebhookKanal(f"{url}/hook").zustellen(friseur, meldung)
    assert erhalten[0]["pfad"] == "/hook"
    assert erhalten[0]["json"]["daten"]["name"] == "Julia Neumann"
    assert erhalten[0]["json"]["profil"] == "friseur-schnittpunkt"


async def test_email_kanal(friseur, monkeypatch):
    gesendet = []

    class FakeSMTP:
        def __init__(self, server, port, timeout):
            self.server, self.port = server, port

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def starttls(self):
            gesendet.append("tls")

        def login(self, benutzer, passwort):
            gesendet.append(("login", benutzer))

        def send_message(self, nachricht):
            gesendet.append(nachricht)

    monkeypatch.setattr(b.smtplib, "SMTP", FakeSMTP)
    kanal = EmailKanal(
        "chef@example.de", "mail.example.de", 587, "bot@example.de", "pw"
    )
    await kanal.zustellen(friseur, meldung_bauen(friseur, "termin_gebucht", TERMIN))

    assert gesendet[:2] == ["tls", ("login", "bot@example.de")]
    mail = gesendet[2]
    assert mail["To"] == "chef@example.de"
    assert mail["Subject"] == "Neuer Termin – Salon Schnittpunkt"
    assert "Julia Neumann" in mail.get_content()


# --- Versand im Hintergrund --------------------------------------------------


class LangsamerKanal:
    name = "langsam"

    def __init__(self):
        self.angekommen = []

    async def zustellen(self, profil, meldung):
        await asyncio.sleep(0.3)
        self.angekommen.append(meldung.titel)


class KaputterKanal:
    name = "kaputt"

    async def zustellen(self, profil, meldung):
        raise ConnectionError("Server weg")


async def test_versand_blockiert_das_gespraech_nicht(friseur):
    langsam = LangsamerKanal()
    benachrichtiger = Benachrichtiger(friseur, kanaele=[langsam, KaputterKanal()])

    start = time.perf_counter()
    await benachrichtiger.senden("termin_gebucht", TERMIN)
    assert time.perf_counter() - start < 0.05  # kehrt sofort zurück
    assert langsam.angekommen == []

    # Am Anrufende wird gewartet; der kaputte Kanal wirft keinen Fehler nach außen
    await benachrichtiger.abschliessen()
    assert langsam.angekommen == ["Neuer Termin – Salon Schnittpunkt"]
