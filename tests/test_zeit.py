import datetime as dt

from conftest import BERLIN

from smith.zeit import (
    ist_offen,
    naechste_oeffnung,
    status_text,
    uhrzeit_sprechen,
    wochenplan_text,
    zeiten_am,
)


def t(tag: int, stunde: int, minute: int = 0, monat: int = 9) -> dt.datetime:
    return dt.datetime(2026, monat, tag, stunde, minute, tzinfo=BERLIN)


def test_ist_offen_mit_mittagspause(handwerk):
    # Montag, 28.09.2026
    assert ist_offen(handwerk, t(28, 7))
    assert not ist_offen(handwerk, t(28, 12, 30))
    assert ist_offen(handwerk, t(28, 13))
    assert not ist_offen(handwerk, t(28, 16, 30))


def test_naechste_oeffnung_ueber_wochenende(handwerk):
    # Freitag 14 Uhr -> Montag 7 Uhr
    assert naechste_oeffnung(handwerk, t(2, 14, monat=10)) == t(5, 7, monat=10)


def test_sonderzeiten_haben_vorrang(friseur):
    heiligabend = dt.date(2026, 12, 24)  # regulär Donnerstag
    assert zeiten_am(friseur, heiligabend) == []
    silvester = dt.date(2026, 12, 31)
    assert zeiten_am(friseur, silvester) == [(dt.time(9), dt.time(13))]


def test_status_text(friseur):
    assert "geöffnet, heute noch bis 18 Uhr" in status_text(friseur, t(29, 10))
    # Montag geschlossen -> Dienstag
    assert "Nächste Öffnung: morgen um 9 Uhr" in status_text(friseur, t(28, 10))
    assert "Weihnachtspause" in status_text(friseur, t(24, 10, monat=12))


def test_wochenplan_fasst_gleiche_tage_zusammen(handwerk):
    plan = wochenplan_text(handwerk)
    assert "Montag bis Donnerstag: 7 Uhr bis 12 Uhr und 13 Uhr bis 16 Uhr 30" in plan
    assert "Samstag und Sonntag: geschlossen" in plan


def test_uhrzeit_sprechen():
    assert uhrzeit_sprechen(dt.time(9, 0)) == "9 Uhr"
    assert uhrzeit_sprechen(dt.time(14, 5)) == "14 Uhr 05"


def test_gesetzliche_feiertage_sind_geschlossen(friseur, handwerk):
    from smith.profil import PROFIL_ORDNER, profil_laden

    # Tag der Deutschen Einheit 2026 ist ein Samstag – der Salon hätte regulär offen
    einheit = dt.date(2026, 10, 3)
    assert zeiten_am(friseur, einheit) == []
    assert "Feiertag: Tag der Deutschen Einheit" in status_text(
        friseur, t(3, 10, monat=10)
    )
    # Fronleichnam gilt in NRW (Sanitär Müller), nicht in Berlin
    fronleichnam = dt.date(2026, 6, 4)
    assert zeiten_am(handwerk, fronleichnam) == []
    assert zeiten_am(friseur, fronleichnam) != []
    # Restaurants haben an Feiertagen geöffnet (feiertage_geschlossen: false)
    restaurant = profil_laden(PROFIL_ORDNER / "restaurant-luna.yaml")
    assert zeiten_am(restaurant, einheit) != []


def test_sonderzeit_schlaegt_feiertag(friseur):
    from smith.profil import Sonderzeit

    profil = friseur.model_copy(
        update={
            "sonderzeiten": [
                Sonderzeit(
                    von=dt.date(2026, 10, 3),
                    zeiten=["10:00-14:00"],
                    hinweis="Sonderöffnung",
                )
            ]
        }
    )
    assert zeiten_am(profil, dt.date(2026, 10, 3)) == [(dt.time(10), dt.time(14))]


def test_unbekanntes_bundesland_faellt_auf(friseur):
    import pytest
    from pydantic import ValidationError

    from smith.profil import Profil

    with pytest.raises(ValidationError, match="Bundesland"):
        Profil.model_validate({**friseur.model_dump(), "bundesland": "XY"})
