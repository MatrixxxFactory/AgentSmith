import pytest
import yaml
from pydantic import ValidationError

from smith.profil import (
    PROFIL_ORDNER,
    SPRECHER,
    Profil,
    Stimme,
    alle_profile,
    profil_laden,
    profil_waehlen,
)


def test_sprecher_werden_aufgeloest():
    assert Stimme().tts == "gradium/default"
    assert Stimme().voice == SPRECHER["annika"][1]
    assert Stimme(sprecher="Mats").voice == SPRECHER["mats"][1]
    # Direkte Angabe hat Vorrang
    eigene = Stimme(tts="fishaudio/s2.1-pro", voice="abc")
    assert (eigene.tts, eigene.voice) == ("fishaudio/s2.1-pro", "abc")


def test_ungueltige_stimmenangaben():
    with pytest.raises(ValidationError, match="Verfügbar"):
        Stimme(sprecher="gibtsnicht")
    with pytest.raises(ValidationError, match="nur zusammen"):
        Stimme(voice="abc")


def test_beispielprofile_nutzen_annika_und_mats():
    stimmen = {p.id: p.stimme.voice for p in alle_profile()}
    assert stimmen["handwerk-sanitaer-mueller"] == SPRECHER["mats"][1]
    assert stimmen["friseur-schnittpunkt"] == SPRECHER["annika"][1]


MINIMAL = {
    "firma": {"name": "Test", "branche": "Test"},
    "assistent": {"begruessung": "Hallo"},
    "oeffnungszeiten": {"montag": ["09:00-17:00"]},
}


def test_alle_beispielprofile_und_vorlage_sind_gueltig():
    profile = alle_profile()
    assert len(profile) >= 4
    assert "_vorlage" not in {p.id for p in profile}
    profil_laden(PROFIL_ORDNER / "_vorlage.yaml")


def test_profil_id_kommt_aus_dateiname():
    assert (
        profil_laden(PROFIL_ORDNER / "friseur-schnittpunkt.yaml").id
        == "friseur-schnittpunkt"
    )


def test_fehlende_wochentage_gelten_als_geschlossen():
    profil = Profil.model_validate(MINIMAL)
    assert profil.oeffnungszeiten["montag"] == ["09:00-17:00"]
    assert profil.oeffnungszeiten["sonntag"] == []


@pytest.mark.parametrize(
    "zeiten",
    [["9-17"], ["17:00-09:00"], ["25:00-26:00"]],
)
def test_ungueltige_zeitspannen_werden_abgelehnt(zeiten):
    with pytest.raises(ValidationError):
        Profil.model_validate({**MINIMAL, "oeffnungszeiten": {"montag": zeiten}})


def test_unbekannter_wochentag_und_tippfehler_fallen_auf():
    with pytest.raises(ValidationError):
        Profil.model_validate(
            {**MINIMAL, "oeffnungszeiten": {"mondag": ["09:00-17:00"]}}
        )
    with pytest.raises(ValidationError):
        Profil.model_validate({**MINIMAL, "leistungn": []})


def test_weiterleitung_braucht_nummer():
    with pytest.raises(ValidationError):
        Profil.model_validate({**MINIMAL, "module": {"weiterleitung": {"aktiv": True}}})


def test_profil_wahl_nach_angerufener_nummer(tmp_path):
    for name, nummer in (("a-betrieb", "+49301111"), ("b-betrieb", "+49302222")):
        daten = {**MINIMAL, "telefonnummern": [nummer]}
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(daten), encoding="utf-8")

    assert profil_waehlen("+49302222", ordner=tmp_path).id == "b-betrieb"
    assert profil_waehlen("0049 30 2222", ordner=tmp_path).id == "b-betrieb"
    # Unbekannte Nummer -> Standard bzw. erstes Profil
    assert profil_waehlen("+4999", ordner=tmp_path).id == "a-betrieb"
    assert profil_waehlen(None, standard="b-betrieb", ordner=tmp_path).id == "b-betrieb"
    with pytest.raises(FileNotFoundError):
        profil_waehlen(None, standard="gibt-es-nicht", ordner=tmp_path)


def test_leistung_finden_ist_tolerant(friseur):
    assert friseur.leistung_finden("herrenhaarschnitt").name == "Herrenhaarschnitt"
    assert friseur.leistung_finden("Haarschnitt für Herren") is None
    assert friseur.leistung_finden("Balayage bitte").name == "Balayage"


def test_stt_schluesselwoerter_enthalten_firma_und_leistungen(friseur):
    woerter = friseur.stt_schluesselwoerter
    assert "Salon Schnittpunkt" in woerter
    assert "Balayage" in woerter
    assert len(woerter) == len(set(woerter))
