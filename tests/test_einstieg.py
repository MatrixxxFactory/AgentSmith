"""Einstieg (src/agent.py): Anrufer erkennen, ohne je unbegrenzt zu warten."""

from types import SimpleNamespace

import pytest
from livekit import api

import agent


def _ctx(raum: str, antworten: list[list]):
    """Nachgebautes JobContext: list_participants liefert nacheinander die Antworten."""
    aufrufe = []

    async def list_participants(anfrage):
        aufrufe.append(anfrage.room)
        teilnehmer = antworten.pop(0) if antworten else []
        return SimpleNamespace(participants=teilnehmer)

    ctx = SimpleNamespace(
        job=SimpleNamespace(room=SimpleNamespace(name=raum)),
        api=SimpleNamespace(room=SimpleNamespace(list_participants=list_participants)),
    )
    return ctx, aufrufe


def _teilnehmer(kind, **attribute):
    return SimpleNamespace(kind=kind, attributes=attribute)


SIP = api.ParticipantInfo.Kind.SIP
STANDARD = api.ParticipantInfo.Kind.STANDARD


async def test_telefonanruf_liefert_sip_attribute():
    ctx, aufrufe = _ctx(
        "anruf-_+4915111_abc",
        [
            [
                _teilnehmer(
                    SIP,
                    **{
                        "sip.phoneNumber": "+4915111",
                        "sip.trunkPhoneNumber": "+4930555",
                    },
                )
            ]
        ],
    )
    attribute = await agent._sip_attribute(ctx)
    assert attribute["sip.trunkPhoneNumber"] == "+4930555"
    assert aufrufe == ["anruf-_+4915111_abc"]


async def test_wartet_kurz_auf_spaeten_anrufer():
    ctx, aufrufe = _ctx("anruf-x", [[], [_teilnehmer(STANDARD)], [_teilnehmer(SIP)]])
    assert await agent._sip_attribute(ctx) == {}  # SIP-Teilnehmer ohne Attribute
    assert len(aufrufe) == 3


async def test_browser_und_simulation_warten_nicht():
    ctx, aufrufe = _ctx("console-123", [])
    assert await agent._sip_attribute(ctx) == {}
    assert aufrufe == []  # keine Abfrage, kein Warten


async def test_nie_unbegrenzt_warten(monkeypatch):
    monkeypatch.setattr(agent, "SIP_WARTEZEIT_S", 0.3)
    ctx, _ = _ctx("anruf-x", [])
    assert await agent._sip_attribute(ctx) == {}


@pytest.mark.parametrize("fehler", [RuntimeError("API weg")])
async def test_api_fehler_fuehrt_zum_standardprofil(monkeypatch, fehler):
    monkeypatch.setattr(agent, "SIP_WARTEZEIT_S", 0.3)

    async def kaputt(_):
        raise fehler

    ctx = SimpleNamespace(
        job=SimpleNamespace(room=SimpleNamespace(name="anruf-x")),
        api=SimpleNamespace(room=SimpleNamespace(list_participants=kaputt)),
    )
    assert await agent._sip_attribute(ctx) == {}
