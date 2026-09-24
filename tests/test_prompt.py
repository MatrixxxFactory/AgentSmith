from conftest import JETZT, kontext_fuer

from smith.module import aktive_module
from smith.profil import alle_profile
from smith.prompt import systemprompt


def prompt_fuer(profil, tmp_path, anrufer="+491701234567"):
    kontext = kontext_fuer(profil, tmp_path, anrufer=anrufer)
    return systemprompt(profil, aktive_module(kontext), JETZT, anrufer)


def test_prompt_enthaelt_betrieb_zeit_und_leistungen(friseur, tmp_path):
    prompt = prompt_fuer(friseur, tmp_path)
    assert "Du bist Lena" in prompt
    assert "Salon Schnittpunkt" in prompt
    assert "Jetzt: Dienstag, 2026-09-29 08:00" in prompt
    assert "Di 2026-10-06" in prompt  # Kalender der nächsten Tage
    assert "Balayage, ab 149 Euro" in prompt
    assert "Kann man mit Karte zahlen?" in prompt
    assert "Der Anruf kommt von +491701234567" in prompt


def test_prompt_enthaelt_nur_aktive_module(friseur, handwerk, tmp_path):
    friseur_prompt = prompt_fuer(friseur, tmp_path)
    handwerk_prompt = prompt_fuer(handwerk, tmp_path)
    assert "an_mitarbeiter_weiterleiten" not in friseur_prompt
    assert "an_mitarbeiter_weiterleiten" in handwerk_prompt
    assert "Wasserrohrbruch" in handwerk_prompt
    assert "# Notfälle" not in friseur_prompt


def test_prompt_ohne_anrufernummer(friseur, tmp_path):
    assert "Nummer des Anrufers ist unbekannt" in prompt_fuer(
        friseur, tmp_path, anrufer=""
    )


def test_prompts_bleiben_kompakt(tmp_path):
    # Grober Latenz-Schutz: Prompts sollen nicht unbemerkt ausufern
    for profil in alle_profile():
        assert len(prompt_fuer(profil, tmp_path)) < 6000, profil.id
