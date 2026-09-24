"""Tools der Module direkt aufrufen – ohne LLM, schnell und deterministisch."""

import datetime as dt
import json

import pytest
from conftest import BERLIN, bestaetigt, kontext_fuer
from livekit.agents import ToolError

from smith.module import aktive_module
from smith.module.info import FAQ_IM_PROMPT_MAX, InfoModul
from smith.module.rueckruf import RueckrufModul
from smith.module.termine import TermineModul, nummer_sprechen
from smith.module.weiterleitung import WeiterleitungModul
from smith.profil import FAQ


def tool_namen(modul) -> set[str]:
    return {t.id for t in modul.tools}


# --- Modulauswahl ----------------------------------------------------------


def test_module_folgen_dem_profil(friseur, handwerk, tmp_path):
    friseur_module = {m.id for m in aktive_module(kontext_fuer(friseur, tmp_path))}
    handwerk_module = {m.id for m in aktive_module(kontext_fuer(handwerk, tmp_path))}
    assert friseur_module == {"info", "termine", "rueckruf"}
    assert handwerk_module == {"info", "termine", "rueckruf", "weiterleitung"}


def test_faq_tool_nur_bei_vielen_eintraegen(friseur, tmp_path):
    assert "wissen_nachschlagen" not in tool_namen(
        InfoModul(kontext_fuer(friseur, tmp_path))
    )
    gross = friseur.model_copy(
        update={
            "faq": [
                FAQ(frage=f"Frage {i}", antwort="x")
                for i in range(FAQ_IM_PROMPT_MAX + 1)
            ]
        }
    )
    assert "wissen_nachschlagen" in tool_namen(InfoModul(kontext_fuer(gross, tmp_path)))


# --- Info --------------------------------------------------------------------


async def test_oeffnungszeiten_am(kontext):
    info = InfoModul(kontext)
    assert await info.oeffnungszeiten_am("2026-09-29") == "heute: 9 Uhr bis 18 Uhr"
    assert "geschlossen (Weihnachtspause)" in await info.oeffnungszeiten_am(
        "2026-12-24"
    )
    with pytest.raises(ToolError):
        await info.oeffnungszeiten_am("nächsten Dienstag")


async def test_wissen_nachschlagen(friseur, tmp_path):
    info = InfoModul(kontext_fuer(friseur, tmp_path))
    antwort = await info.wissen_nachschlagen("Wie ist das mit Parkplätzen?")
    assert "Straßenparkplätze" in antwort
    assert (
        await info.wissen_nachschlagen("Verkaufen Sie Autos?")
        == "Dazu ist nichts hinterlegt."
    )


# --- Termine -----------------------------------------------------------------


async def test_freie_termine_respektieren_vorlauf(kontext):
    # Jetzt ist 8 Uhr, Vorlauf 2 Stunden -> frühestens 10 Uhr
    frei = await TermineModul(kontext).freie_zeiten(
        kontext.profil.leistung_finden("Herrenhaarschnitt"), dt.date(2026, 9, 29)
    )
    assert frei[0].time() == dt.time(10, 0)
    assert frei[-1].time() == dt.time(17, 30)


async def test_freie_termine_suchen_springt_bei_ruhetag_weiter(kontext):
    # Montag, 5.10. ist Ruhetag -> Dienstag, 6.10.
    antwort = await TermineModul(kontext).freie_termine_suchen(
        "Damenhaarschnitt", "2026-10-05"
    )
    assert "Am Wunschtag ist nichts frei" in antwort
    assert "2026-10-06" in antwort
    assert "9 Uhr" in antwort


async def test_tageszeit_filter(kontext):
    antwort = await TermineModul(kontext).freie_termine_suchen(
        "Herrenhaarschnitt", "2026-10-01", "abend"
    )
    # Donnerstag 10-20 Uhr, abends = ab 17 Uhr
    assert "17 Uhr" in antwort
    assert "10 Uhr" not in antwort


async def test_buchen_und_kapazitaet(kontext):
    termine = TermineModul(kontext)
    leistung = kontext.profil.leistung_finden("Herrenhaarschnitt")
    tag = dt.date(2026, 9, 30)
    zehn = dt.datetime(2026, 9, 30, 10, 0, tzinfo=BERLIN)

    # Zwei Stühle: zwei Buchungen um 10 Uhr gehen, die dritte nicht
    for name in ("Anna Berg", "Ben Kraus"):
        await bestaetigt(
            termine,
            "termin_buchen",
            "Herrenhaarschnitt",
            "2026-09-30",
            "10:00",
            name,
            "0170 111",
        )
    assert zehn not in await termine.freie_zeiten(leistung, tag)
    with pytest.raises(ToolError, match="nicht \\(mehr\\) frei"):
        await bestaetigt(
            termine,
            "termin_buchen",
            "Herrenhaarschnitt",
            "2026-09-30",
            "10:00",
            "Cem Yilmaz",
            "",
        )

    # Ein Damenhaarschnitt (60 min) ab 9:30 würde mit 10 Uhr kollidieren
    damen = kontext.profil.leistung_finden("Damenhaarschnitt")
    assert dt.datetime(
        2026, 9, 30, 9, 30, tzinfo=BERLIN
    ) not in await termine.freie_zeiten(damen, tag)

    ereignisse = [e for e, _ in kontext.benachrichtiger.gesendet]
    assert ereignisse == ["termin_gebucht", "termin_gebucht"]


async def test_buchen_nimmt_anrufernummer_und_prueft_eingaben(kontext, tmp_path):
    termine = TermineModul(kontext)
    antwort = await bestaetigt(
        termine,
        "termin_buchen",
        "Kinderhaarschnitt",
        "2026-09-30",
        "11:00",
        "Mia Sommer",
        "",
    )
    assert antwort.startswith("Gebucht: Kinderhaarschnitt")
    gespeichert = json.loads((tmp_path / "termine.json").read_text(encoding="utf-8"))
    assert gespeichert[0]["telefon"] == "+491701234567"

    with pytest.raises(ToolError, match="Name"):
        await bestaetigt(
            termine,
            "termin_buchen",
            "Kinderhaarschnitt",
            "2026-09-30",
            "12:00",
            " ",
            "",
        )
    with pytest.raises(ToolError, match="gibt es nicht"):
        await bestaetigt(
            termine, "termin_buchen", "Dauerwelle", "2026-09-30", "12:00", "Mia", ""
        )
    with pytest.raises(ToolError, match="Vergangenheit"):
        await termine.freie_termine_suchen("Kinderhaarschnitt", "2026-09-01")
    with pytest.raises(ToolError, match="Tage im Voraus"):
        await termine.freie_termine_suchen("Kinderhaarschnitt", "2027-06-01")


async def test_termin_finden_und_absagen(kontext):
    termine = TermineModul(kontext)
    await bestaetigt(
        termine,
        "termin_buchen",
        "Färben",
        "2026-10-02",
        "09:00",
        "Lea Wolf",
        "0170 1234567",
    )

    # Gleiche Nummer in anderer Schreibweise wird gefunden
    liste = await termine.termine_des_anrufers_finden("")
    assert "Färben" in liste and "Lea Wolf" in liste
    termin_id = liste.split("[id ")[1].split("]")[0]

    assert (await bestaetigt(termine, "termin_absagen", termin_id)).startswith(
        "Abgesagt: Färben"
    )
    assert "keine kommenden Termine" in await termine.termine_des_anrufers_finden("")
    with pytest.raises(ToolError):
        await bestaetigt(termine, "termin_absagen", termin_id)


# --- Rückruf -----------------------------------------------------------------


async def test_rueckruf_notieren(kontext, tmp_path):
    rueckruf = RueckrufModul(kontext)
    await rueckruf.rueckruf_notieren(
        "Tom Hahn", "Frage zu Hochzeitsfrisur", dringend=True
    )
    gespeichert = json.loads(
        (tmp_path / "nachrichten.json").read_text(encoding="utf-8")
    )
    assert gespeichert[0]["telefon"] == "+491701234567"
    assert gespeichert[0]["dringend"] is True
    assert kontext.benachrichtiger.gesendet[0][0] == "rueckruf"


async def test_rueckruf_ohne_nummer_fragt_nach(friseur, tmp_path):
    rueckruf = RueckrufModul(kontext_fuer(friseur, tmp_path, anrufer=""))
    with pytest.raises(ToolError, match=r"unterdrückt.*gültige Rückrufnummer"):
        await rueckruf.rueckruf_notieren("Tom Hahn", "Frage")


# --- Weiterleitung -----------------------------------------------------------


def test_weiterleitung_ausserhalb_der_oeffnungszeiten(friseur, tmp_path):
    profil = friseur.model_copy(deep=True)
    profil.module.weiterleitung.aktiv = True
    profil.module.weiterleitung.nummer = "+49301234"
    sonntag = dt.datetime(2026, 10, 4, 12, 0, tzinfo=BERLIN)
    dienstag = dt.datetime(2026, 9, 29, 12, 0, tzinfo=BERLIN)
    assert (
        "Rückruf"
        in WeiterleitungModul(kontext_fuer(profil, tmp_path, sonntag))._pruefen()
    )
    assert (
        WeiterleitungModul(kontext_fuer(profil, tmp_path, dienstag))._pruefen() is None
    )

    # Notdienst-Betriebe leiten rund um die Uhr weiter
    profil.module.weiterleitung.nur_waehrend_oeffnungszeiten = False
    assert (
        WeiterleitungModul(kontext_fuer(profil, tmp_path, sonntag))._pruefen() is None
    )


async def test_leere_notizen_werden_nicht_gespeichert(kontext, tmp_path):
    termine = TermineModul(kontext)
    await bestaetigt(
        termine,
        "termin_buchen",
        "Kinderhaarschnitt",
        "2026-09-30",
        "11:00",
        "Mia",
        "",
        "Keine.",
    )
    gespeichert = json.loads((tmp_path / "termine.json").read_text(encoding="utf-8"))
    assert gespeichert[0]["notiz"] == ""


async def test_falscher_wochentag_wird_abgefangen(kontext):
    # Genau der Fehler aus dem ersten echten Gespräch: "Mittwoch" -> 1.10. (Donnerstag)
    termine = TermineModul(kontext)
    with pytest.raises(
        ToolError, match=r"ist ein Donnerstag, kein Mittwoch.*2026-09-30"
    ):
        await termine.freie_termine_suchen("Färben", "2026-10-01", wochentag="Mittwoch")
    with pytest.raises(ToolError, match="kein Mittwoch"):
        await bestaetigt(
            termine,
            "termin_buchen",
            "Färben",
            "2026-10-01",
            "13:30",
            "Max Berg",
            "",
            wochentag="mittwochs",
        )
    # Richtig kombiniert oder ohne Wochentag klappt es
    assert "2026-09-30" in await termine.freie_termine_suchen(
        "Färben", "2026-09-30", wochentag="Mi"
    )
    assert await InfoModul(kontext).oeffnungszeiten_am("2026-10-01", "Donnerstag")


async def test_buchen_erst_nach_antwort_des_anrufers(kontext, tmp_path):
    termine = TermineModul(kontext)
    args = ("Herrenhaarschnitt", "2026-09-30", "10:00", "Tom Berger", "0170 1234567")

    # Erster Aufruf: nur Zusammenfassung, nichts gebucht
    antwort = await termine.termin_buchen(*args, wochentag="Mittwoch")
    assert antwort.startswith("NOCH NICHT GEBUCHT")
    assert "Mittwoch, den 30.9. um 10 Uhr" in antwort and "0170 1234567" in antwort
    # Sofort nochmal (Modell fragt und bucht im selben Zug) -> weiterhin nicht gebucht
    assert (await termine.termin_buchen(*args)).startswith("NOCH NICHT")
    assert not (tmp_path / "termine.json").exists()

    # Anrufer hat die Zusammenfassung gehört und korrigiert nur die Nummer:
    # gebucht wird mit seiner eigenen, korrigierten Angabe (keine Schleife)
    kontext.anrufer_hat_gesprochen()
    korrigiert = (*args[:4], "0170 1234576")
    antwort = await termine.termin_buchen(*korrigiert)
    assert antwort.startswith("Gebucht") and "0170 1234576" in antwort
    gespeichert = json.loads((tmp_path / "termine.json").read_text(encoding="utf-8"))
    assert [t["telefon"] for t in gespeichert] == ["0170 1234576"]


async def test_andere_uhrzeit_braucht_neue_bestaetigung(kontext, tmp_path):
    termine = TermineModul(kontext)
    await termine.termin_buchen(
        "Herrenhaarschnitt", "2026-09-30", "10:00", "Tom", "0170 1234567"
    )
    kontext.anrufer_hat_gesprochen()
    # Anrufer will doch lieber 11 Uhr -> das muss erst wieder vorgelesen werden
    antwort = await termine.termin_buchen(
        "Herrenhaarschnitt", "2026-09-30", "11:00", "Tom", "0170 1234567"
    )
    assert antwort.startswith("NOCH NICHT")
    assert not (tmp_path / "termine.json").exists()


async def test_absagen_erst_nach_antwort_des_anrufers(kontext):
    termine = TermineModul(kontext)
    await bestaetigt(
        termine, "termin_buchen", "Färben", "2026-10-02", "09:00", "Lea", ""
    )
    termin_id = (
        (await termine.termine_des_anrufers_finden("")).split("[id ")[1].split("]")[0]
    )
    assert (await termine.termin_absagen(termin_id)).startswith("NOCH NICHT ABGESAGT")
    assert "Färben" in await termine.termine_des_anrufers_finden("")


def test_nummer_zum_vorlesen_gruppieren():
    assert nummer_sprechen("01701234567") == "0170 123 4567"
    assert nummer_sprechen("015123456789") == "0151 234 567 89"
    assert nummer_sprechen("0151 234 567 89") == "0151 234 567 89"  # schon gegliedert
    assert nummer_sprechen("+491701234567") == "0170 123 4567"


async def test_keine_fantasie_nummern(friseur, tmp_path):
    # Aus der Simulation: Anrufer ohne sichtbare Nummer -> Modell trug "unbekannt" ein
    termine = TermineModul(kontext_fuer(friseur, tmp_path, anrufer=""))
    for angabe in ("unbekannt", "die Nummer vom Anruf", "", "12"):
        with pytest.raises(ToolError, match="gültige Rückrufnummer"):
            await termine.termin_buchen(
                "Herrenhaarschnitt", "2026-09-30", "10:00", "Kurt", angabe
            )
    # Mit sichtbarer Anrufernummer wird "unbekannt" durch sie ersetzt
    mit_nummer = TermineModul(kontext_fuer(friseur, tmp_path))
    antwort = await mit_nummer.termin_buchen(
        "Herrenhaarschnitt", "2026-09-30", "10:00", "Kurt", "unbekannt"
    )
    assert "0170 123 4567" in antwort


async def test_dringende_nachricht_auch_ohne_nummer(friseur, tmp_path):
    # Aus der Simulation: Rohrbruch, Nummer unterdrückt -> trotzdem notieren
    kontext = kontext_fuer(friseur, tmp_path, anrufer="")
    rueckruf = RueckrufModul(kontext)
    antwort = await rueckruf.rueckruf_notieren(
        "Jens Koch", "Rohrbruch, Aachener Straße 40", "", dringend=True
    )
    assert "OHNE Rückrufnummer" in antwort and "NICHT möglich" in antwort
    gespeichert = json.loads(
        (tmp_path / "nachrichten.json").read_text(encoding="utf-8")
    )
    assert gespeichert[0]["telefon"] == "OHNE RÜCKRUFNUMMER"
    assert kontext.benachrichtiger.gesendet[0][1]["anliegen"].startswith("Rohrbruch")


async def test_platzhalter_namen_werden_abgelehnt(kontext):
    rueckruf = RueckrufModul(kontext)
    for name in ("Unbekannt", "anrufer", ""):
        with pytest.raises(ToolError, match="Name fehlt"):
            await rueckruf.rueckruf_notieren(name, "Rohrbruch", dringend=True)
    assert kontext.benachrichtiger.gesendet == []


async def test_keine_termine_am_feiertag(kontext):
    # Samstag 3.10.2026: regulär offen, aber Feiertag -> nächster freier Tag
    antwort = await TermineModul(kontext).freie_termine_suchen(
        "Herrenhaarschnitt", "2026-10-03", wochentag="Samstag"
    )
    assert "Am Wunschtag ist nichts frei" in antwort
    assert "2026-10-06" in antwort  # Sonntag zu, Montag Ruhetag, Dienstag offen
    assert "(Feiertag: Tag der Deutschen Einheit)" in await InfoModul(
        kontext
    ).oeffnungszeiten_am("2026-10-03")


async def test_nicht_auflegen_solange_nur_vorgemerkt(kontext):
    # Aus der Simulation: Korrektur + Abschied in einem Satz -> Modell sagte "gebucht"
    # und wollte auflegen, obwohl die neue Nummer nie vorgelesen wurde.
    from smith.rezeptionist import Auflegen

    termine = TermineModul(kontext)
    auflegen = Auflegen(kontext, end_instructions=None)
    await termine.termin_buchen(
        "Damenhaarschnitt", "2026-09-30", "10:30", "Anna", "0151 234 567 98"
    )

    assert kontext.unbestaetigt_vorgemerkt()
    with pytest.raises(ToolError, match="Noch nicht auflegen"):
        await auflegen._end_call(None)

    # Nachdem der Anrufer die Zusammenfassung gehört und geantwortet hat, darf aufgelegt werden
    kontext.anrufer_hat_gesprochen()
    assert not kontext.unbestaetigt_vorgemerkt()
