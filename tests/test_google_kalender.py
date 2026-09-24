"""GoogleKalender gegen einen lokalen Nachbau der Google-Calendar-API."""

import datetime as dt
import itertools

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from conftest import BERLIN, FakeBenachrichtiger
from livekit.agents import ToolError

from smith import AnrufKontext, JsonAblage, kalender_fuer
from smith.module.termine import TermineModul
from smith.speicher.google_kalender import GoogleKalender

KALENDER_ID = "salon@group.calendar.google.com"
JETZT = dt.datetime(2026, 9, 29, 8, 0, tzinfo=BERLIN)


def _zeit(angabe: dict) -> dt.datetime:
    if "dateTime" in angabe:
        return dt.datetime.fromisoformat(angabe["dateTime"])
    return dt.datetime.combine(
        dt.date.fromisoformat(angabe["date"]), dt.time(0), BERLIN
    )


class FakeGoogle:
    """Kleiner Nachbau der Events-API: list (mit Filtern/Seiten), insert, delete."""

    SEITENGROESSE = 2  # klein, damit die Seitenumbrüche mitgetestet werden

    def __init__(self) -> None:
        self.events: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self.anfragen: list[str] = []

    def eintragen(self, **event) -> None:
        event.setdefault("id", f"e{next(self._ids)}")
        event.setdefault("status", "confirmed")
        self.events[event["id"]] = event

    def app(self) -> web.Application:
        app = web.Application()
        pfad = "/calendars/{kal}/events"
        app.router.add_get(pfad, self._liste)
        app.router.add_post(pfad, self._neu)
        app.router.add_delete(pfad + "/{id}", self._loeschen)
        return app

    def _pruefen(self, anfrage: web.Request) -> None:
        assert anfrage.match_info["kal"] == KALENDER_ID
        if anfrage.headers.get("Authorization") != "Bearer test-token":
            raise web.HTTPUnauthorized()
        self.anfragen.append(f"{anfrage.method} {anfrage.query_string}")

    async def _liste(self, anfrage: web.Request) -> web.Response:
        self._pruefen(anfrage)
        q = anfrage.query
        treffer = [e for e in self.events.values() if e["status"] != "cancelled"]
        if "timeMin" in q:
            von = dt.datetime.fromisoformat(q["timeMin"])
            treffer = [e for e in treffer if _zeit(e["end"]) > von]
        if "timeMax" in q:
            bis = dt.datetime.fromisoformat(q["timeMax"])
            treffer = [e for e in treffer if _zeit(e["start"]) < bis]
        if "privateExtendedProperty" in q:
            k, v = q["privateExtendedProperty"].split("=", 1)
            treffer = [
                e
                for e in treffer
                if e.get("extendedProperties", {}).get("private", {}).get(k) == v
            ]
        treffer.sort(key=lambda e: _zeit(e["start"]))
        start = int(q.get("pageToken", 0))
        seite = treffer[start : start + self.SEITENGROESSE]
        antwort: dict = {"items": seite}
        if start + self.SEITENGROESSE < len(treffer):
            antwort["nextPageToken"] = str(start + self.SEITENGROESSE)
        return web.json_response(antwort)

    async def _neu(self, anfrage: web.Request) -> web.Response:
        self._pruefen(anfrage)
        event = await anfrage.json()
        self.eintragen(**event)
        return web.json_response(event)

    async def _loeschen(self, anfrage: web.Request) -> web.Response:
        self._pruefen(anfrage)
        self.events[anfrage.match_info["id"]]["status"] = "cancelled"
        return web.Response(status=204)


@pytest.fixture
async def google():
    fake = FakeGoogle()
    server = TestServer(fake.app())
    await server.start_server()
    fake.url = str(server.make_url("/")).rstrip("/")
    yield fake
    await server.close()


async def _token() -> str:
    return "test-token"


@pytest.fixture
def termine(friseur, google, tmp_path):
    kalender = GoogleKalender(KALENDER_ID, _token, api=google.url)
    ablage = JsonAblage(tmp_path)
    kontext = AnrufKontext(
        profil=friseur,
        kalender=kalender,
        postfach=ablage,
        protokoll=ablage,
        benachrichtiger=FakeBenachrichtiger(friseur),
        anrufer_nummer="+491701234567",
        uhr=lambda: JETZT,
    )
    return TermineModul(kontext)


async def test_buchung_landet_als_kalendereintrag(termine, google):
    antwort = await termine.termin_buchen(
        "Damenhaarschnitt", "2026-09-30", "10:00", "Julia Neumann", "", "Spitzen"
    )
    assert antwort.startswith("Gebucht")
    (event,) = google.events.values()
    assert event["summary"] == "Damenhaarschnitt – Julia Neumann"
    assert event["start"]["dateTime"].startswith("2026-09-30T10:00:00+02:00")
    assert event["end"]["dateTime"].startswith("2026-09-30T11:00:00+02:00")
    privat = event["extendedProperties"]["private"]
    assert privat["telefon"] == "1701234567"  # normalisiert fürs Wiederfinden
    assert "Spitzen" in event["description"]


async def test_kapazitaet_ueber_den_kalender(termine):
    # Zwei Stühle: zwei Buchungen um 10 Uhr, die dritte scheitert
    for name in ("Anna Berg", "Ben Kraus"):
        await termine.termin_buchen(
            "Herrenhaarschnitt", "2026-09-30", "10:00", name, "0170 1"
        )
    with pytest.raises(ToolError, match="nicht \\(mehr\\) frei"):
        await termine.termin_buchen(
            "Herrenhaarschnitt", "2026-09-30", "10:00", "Cem", "0170 2"
        )


async def test_eigene_eintraege_des_betriebs_blockieren(termine, google):
    leistung = termine.k.profil.leistung_finden("Herrenhaarschnitt")

    # Ganztägiger Urlaub blockiert den ganzen Tag, trotz zwei Stühlen
    google.eintragen(
        summary="Urlaub", start={"date": "2026-10-01"}, end={"date": "2026-10-02"}
    )
    assert await termine.freie_zeiten(leistung, dt.date(2026, 10, 1)) == []

    # Ein Termin mit "Verfügbarkeit: frei" blockiert nichts
    google.eintragen(
        summary="Erinnerung",
        transparency="transparent",
        start={"dateTime": "2026-10-02T09:00:00+02:00"},
        end={"dateTime": "2026-10-02T18:00:00+02:00"},
    )
    frei = await termine.freie_zeiten(leistung, dt.date(2026, 10, 2))
    assert dt.datetime(2026, 10, 2, 9, 0, tzinfo=BERLIN) in frei

    # Zwei normale Einträge des Chefs belegen beide Stühle
    for titel in ("Zahnarzt", "Lieferant"):
        google.eintragen(
            summary=titel,
            start={"dateTime": "2026-10-02T12:00:00+02:00"},
            end={"dateTime": "2026-10-02T13:00:00+02:00"},
        )
    frei = await termine.freie_zeiten(leistung, dt.date(2026, 10, 2))
    assert dt.datetime(2026, 10, 2, 12, 0, tzinfo=BERLIN) not in frei


async def test_termine_finden_und_absagen(termine, google):
    for tag in ("2026-09-30", "2026-10-02", "2026-10-06"):
        await termine.termin_buchen(
            "Herrenhaarschnitt", tag, "11:00", "Lea Wolf", "0170 1234567"
        )
    # Fremder Kunde soll nicht auftauchen
    await termine.termin_buchen(
        "Herrenhaarschnitt", "2026-09-30", "12:00", "Max", "0151 999"
    )

    # Drei Treffer über zwei Seiten der API, sortiert
    liste = await termine.termine_des_anrufers_finden("")
    assert liste.count("Lea Wolf") == 3 and "Max" not in liste
    termin_id = liste.split("[id ")[1].split("]")[0]

    assert (await termine.termin_absagen(termin_id)).startswith("Abgesagt")
    assert (await termine.termine_des_anrufers_finden("")).count("Lea Wolf") == 2
    with pytest.raises(ToolError):
        await termine.termin_absagen(termin_id)


async def test_fehler_der_api_wird_gemeldet(friseur, google):
    async def falsches_token() -> str:
        return "abgelaufen"

    kalender = GoogleKalender(KALENDER_ID, falsches_token, api=google.url)
    with pytest.raises(RuntimeError, match="401"):
        await kalender.termine_zwischen(JETZT, JETZT + dt.timedelta(days=1))


def test_kalender_auswahl(friseur, tmp_path, monkeypatch):
    ablage = JsonAblage(tmp_path)
    assert kalender_fuer(friseur, ablage) is ablage

    google = friseur.model_copy(deep=True)
    google.kalender.art = "google"
    monkeypatch.delenv("SMITH_GOOGLE_KALENDER_ID", raising=False)
    monkeypatch.delenv("SMITH_GOOGLE_DIENSTKONTO", raising=False)
    with pytest.raises(RuntimeError, match="SMITH_GOOGLE_KALENDER_ID"):
        kalender_fuer(google, ablage)
