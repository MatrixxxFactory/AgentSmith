import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from smith import AnrufKontext, JsonAblage
from smith.benachrichtigung import Benachrichtiger
from smith.profil import PROFIL_ORDNER, Profil, profil_laden

BERLIN = ZoneInfo("Europe/Berlin")
# Dienstag, 29.09.2026, 8 Uhr – fester "Jetzt"-Zeitpunkt für alle Tests
JETZT = dt.datetime(2026, 9, 29, 8, 0, tzinfo=BERLIN)


class FakeBenachrichtiger(Benachrichtiger):
    def __init__(self, profil: Profil) -> None:
        super().__init__(profil, kanaele=[])
        self.gesendet: list[tuple[str, dict]] = []

    async def senden(self, ereignis: str, daten: dict) -> None:
        self.gesendet.append((ereignis, daten))


def kontext_fuer(
    profil: Profil, ordner, jetzt: dt.datetime = JETZT, anrufer: str = "+491701234567"
) -> AnrufKontext:
    ablage = JsonAblage(ordner)
    return AnrufKontext(
        profil=profil,
        kalender=ablage,
        postfach=ablage,
        protokoll=ablage,
        benachrichtiger=FakeBenachrichtiger(profil),
        anrufer_nummer=anrufer,
        uhr=lambda: jetzt,
    )


@pytest.fixture
def friseur() -> Profil:
    return profil_laden(PROFIL_ORDNER / "friseur-schnittpunkt.yaml")


@pytest.fixture
def handwerk() -> Profil:
    return profil_laden(PROFIL_ORDNER / "handwerk-sanitaer-mueller.yaml")


@pytest.fixture
def kontext(friseur, tmp_path) -> AnrufKontext:
    return kontext_fuer(friseur, tmp_path)
