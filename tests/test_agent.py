"""Verhaltenstests mit echtem LLM (LiveKit Testing-Framework).

Laufen nur mit LiveKit-Zugangsdaten in .env.local (LiveKit Inference),
sonst werden sie übersprungen. Doku: https://docs.livekit.io/agents/start/testing/

    python -m uv run pytest tests/test_agent.py
"""

import os

import pytest
from conftest import kontext_fuer
from dotenv import load_dotenv
from livekit.agents import AgentSession, inference, llm
from livekit.agents.voice.run_result import FunctionCallEvent

from smith import Rezeptionist

load_dotenv(".env.local")

pytestmark = pytest.mark.skipif(
    not os.getenv("LIVEKIT_API_KEY"),
    reason="Braucht LiveKit-Zugangsdaten in .env.local (lk app env --write --destination .env.local)",
)


def _judge_llm() -> llm.LLM:
    return inference.LLM(model="openai/gpt-4.1-mini")


def _aufgerufene_tools(result) -> list[str]:
    return [e.item.name for e in result.events if isinstance(e, FunctionCallEvent)]


async def _sitzung(profil, tmp_path):
    kontext = kontext_fuer(profil, tmp_path)
    # SMITH_TEST_LLM erlaubt, andere Modelle mit denselben Tests zu vergleichen
    modell = os.getenv("SMITH_TEST_LLM") or profil.stimme.llm
    session = AgentSession(llm=inference.LLM(model=modell))
    await session.start(Rezeptionist(kontext))
    return session, kontext


async def test_beantwortet_oeffnungszeiten_auf_deutsch(friseur, tmp_path):
    async with _judge_llm() as judge:
        session, _ = await _sitzung(friseur, tmp_path)
        async with session:
            result = await session.run(user_input="Haben Sie montags geöffnet?")
            await result.expect.contains_message(role="assistant").judge(
                judge,
                intent="Antwortet auf Deutsch, dass der Salon montags geschlossen ist. "
                "Kurz, ohne Listen oder Markdown.",
            )


async def test_sucht_termin_mit_richtigem_datum(friseur, tmp_path):
    # Jetzt ist Dienstag, 29.09.2026 -> "morgen" = 2026-09-30
    session, _ = await _sitzung(friseur, tmp_path)
    async with session:
        result = await session.run(
            user_input="Ich hätte gern morgen Vormittag einen Herrenhaarschnitt."
        )
        result.expect.contains_function_call(name="freie_termine_suchen")
        aufruf = next(e.item for e in result.events if isinstance(e, FunctionCallEvent))
        assert "2026-09-30" in aufruf.arguments


async def test_bucht_nicht_ohne_bestaetigung(friseur, tmp_path):
    session, _ = await _sitzung(friseur, tmp_path)
    async with session:
        await session.run(
            user_input="Ich hätte gern morgen Vormittag einen Herrenhaarschnitt."
        )
        result = await session.run(
            user_input="Zehn Uhr klingt gut. Ich bin Tom Berger."
        )
        assert "termin_buchen" not in _aufgerufene_tools(result)


async def test_bucht_nach_bestaetigung(friseur, tmp_path):
    session, _ = await _sitzung(friseur, tmp_path)
    async with session:
        await session.run(
            user_input="Ich hätte gern morgen Vormittag einen Herrenhaarschnitt."
        )
        await session.run(user_input="Zehn Uhr klingt gut. Ich bin Tom Berger.")
        # Der Anrufer bestätigt, bis gebucht wird – aber mehr als dreimal
        # nachfragen wäre am Telefon zu umständlich.
        gebucht = False
        for antwort in (
            "Ja, und die Nummer, von der ich anrufe, passt.",
            "Ja, genau so, bitte buchen.",
            "Ja.",
        ):
            result = await session.run(user_input=antwort)
            if "termin_buchen" in _aufgerufene_tools(result):
                gebucht = True
                break
        assert gebucht, "Termin wurde auch nach dreifacher Bestätigung nicht gebucht"
    assert (tmp_path / "termine.json").exists()


async def test_notfall_gasgeruch(handwerk, tmp_path):
    async with _judge_llm() as judge:
        session, _ = await _sitzung(handwerk, tmp_path)
        async with session:
            result = await session.run(
                user_input="Hilfe, bei mir im Keller riecht es nach Gas!"
            )
            await result.expect.contains_message(role="assistant").judge(
                judge,
                intent="Nimmt den Notfall ernst und gibt Sicherheitshinweise, etwa das Haus "
                "zu verlassen, keine Schalter zu betätigen oder die 112 bzw. den "
                "Gasversorger anzurufen.",
            )


async def test_lehnt_themenfremdes_ab(friseur, tmp_path):
    async with _judge_llm() as judge:
        session, _ = await _sitzung(friseur, tmp_path)
        async with session:
            result = await session.run(
                user_input="Können Sie mir sagen, welche Aktien ich kaufen soll?"
            )
            await result.expect.contains_message(role="assistant").judge(
                judge,
                intent="Lehnt freundlich ab, weil das nicht zum Friseursalon gehört, "
                "und gibt keine Anlagetipps.",
            )


@pytest.mark.parametrize(
    ("satz", "datum"),
    [
        ("Haben Sie am Mittwoch einen Termin zum Färben frei?", "2026-09-30"),
        (
            "Ich hätte gern nächste Woche Mittwoch einen Termin zum Färben.",
            "2026-10-07",
        ),
        ("Geht Färben diesen Donnerstag?", "2026-10-01"),
    ],
)
async def test_wochentage_werden_richtig_aufgeloest(friseur, tmp_path, satz, datum):
    # Jetzt ist Dienstag, 29.09.2026
    session, _ = await _sitzung(friseur, tmp_path)
    async with session:
        result = await session.run(user_input=satz)
        aufrufe = [
            e.item
            for e in result.events
            if isinstance(e, FunctionCallEvent)
            and e.item.name == "freie_termine_suchen"
        ]
        if not aufrufe:
            # Eine Rückfrage ("Welchen Mittwoch meinen Sie?") ist in Ordnung – raten nicht
            antwort = result.expect.contains_message(role="assistant").event().item
            assert "?" in antwort.text_content, (
                f"Weder gesucht noch nachgefragt: {antwort}"
            )
            return
        # Der letzte Aufruf zählt: ein falscher erster wird vom Tool abgelehnt und korrigiert
        assert datum in aufrufe[-1].arguments


async def test_kein_nachsatz_nach_dem_auflegen(friseur, tmp_path):
    session, _ = await _sitzung(friseur, tmp_path)
    async with session:
        result = await session.run(user_input="Das war alles, vielen Dank. Tschüss!")
        namen = [
            e.item.name if isinstance(e, FunctionCallEvent) else e.type
            for e in result.events
        ]
        # Auflegen ist erwünscht, aber nicht Pflicht (der Anrufer legt ohnehin auf).
        # Entscheidend: Nach dem Auflegen darf nichts mehr gesagt werden.
        if "end_call" in namen:
            danach = namen[namen.index("end_call") + 1 :]
            assert "message" not in danach, f"Nach dem Auflegen kam noch: {namen}"
