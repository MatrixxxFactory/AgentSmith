"""Baut den Systemprompt aus Profil und aktiven Modulen.

Der Prompt ist bewusst knapp: Am Telefon zählt jede Millisekunde, und jedes
Token im Prompt verlängert die Antwortzeit.
"""

from __future__ import annotations

import datetime as dt

from .module import Modul
from .module.info import FAQ_IM_PROMPT_MAX
from .profil import Profil
from .zeit import (
    WOCHENTAG_ANZEIGE,
    feiertag,
    sonderzeit_fuer,
    status_text,
    wochenplan_text,
)


def _kalender_text(heute: dt.date) -> str:
    """Kalender nach Wochen, Wochentage ausgeschrieben.

    Sprachmodelle rechnen Wochentage oft falsch ("Mittwoch" -> Donnerstag). Mit einer
    fertigen Tabelle müssen sie nur ablesen; die Tools prüfen zusätzlich den Wochentag.
    """
    montag = heute - dt.timedelta(days=heute.weekday())
    zeilen = []
    for woche, titel in enumerate(
        ("Diese Woche", "Nächste Woche", "Übernächste Woche")
    ):
        tage = []
        for i in range(7):
            tag = montag + dt.timedelta(days=7 * woche + i)
            if tag < heute:
                continue
            zusatz = (
                " (heute)"
                if tag == heute
                else " (morgen)"
                if tag == heute + dt.timedelta(days=1)
                else ""
            )
            tage.append(f"{WOCHENTAG_ANZEIGE[tag.weekday()]} {tag.isoformat()}{zusatz}")
        zeilen.append(f"{titel}: {', '.join(tage)}")
    return "\n".join(zeilen)


def systemprompt(
    profil: Profil, module: list[Modul], jetzt: dt.datetime, anrufer_nummer: str = ""
) -> str:
    f = profil.firma
    a = profil.assistent
    teile: list[str] = []

    teile.append(
        f"Du bist {a.name}, die telefonische Assistenz von {f.name} ({f.branche}). "
        f"Du nimmst Anrufe entgegen. Tonfall: {a.tonfall}. "
        "Du sprichst ausschließlich Deutsch, außer der Anrufer spricht erkennbar eine andere Sprache. "
        "Wenn jemand fragt, sagst du ehrlich, dass du eine KI-Assistenz bist."
    )

    teile.append(
        "# Sprechregeln\n"
        "- Nur gesprochener Fließtext: keine Listen, kein Markdown, keine Emojis.\n"
        "- Kurz: ein bis zwei Sätze pro Antwort, eine Frage auf einmal.\n"
        '- Uhrzeiten sprechen wie "halb zehn" oder "14 Uhr", Telefonnummern ziffernweise in Gruppen.\n'
        "- Wiederhole Namen und diktierte Nummern einmal zur Kontrolle, bevor du sie speicherst; "
        "liefert ein Tool eine Zusammenfassung zum Vorlesen, ist das diese Kontrolle – frag nicht doppelt.\n"
        "- Frag nie nach etwas, das der Anrufer schon gesagt hat; nutze es.\n"
        "- Verabschiedet sich der Anrufer schon, stelle keine Rückfrage mehr: bestätige kurz, "
        "was du erledigt hast, und verabschiede dich.\n"
        "- Nenne nie interne Kennungen, Toolnamen oder technische Details.\n"
        "- Kündige nie nur an (nachschauen, verbinden, notieren): Rufe das passende Tool "
        "sofort im selben Zug auf, ohne auf eine Antwort zu warten."
    )

    betrieb = [f"# Betrieb\n{f.name}, {f.branche}."]
    if f.beschreibung:
        betrieb.append(f.beschreibung)
    for bezeichnung, wert in (
        ("Adresse", f.adresse),
        ("Telefon", f.telefon),
        ("E-Mail", f.email),
        ("Webseite", f.webseite),
    ):
        if wert:
            betrieb.append(f"{bezeichnung}: {wert}")
    teile.append("\n".join(betrieb))

    teile.append(
        f"# Zeit\nJetzt: {WOCHENTAG_ANZEIGE[jetzt.weekday()]}, {jetzt:%Y-%m-%d %H:%M}. "
        f"{status_text(profil, jetzt)}\nKalender (Datum immer hier ablesen, nie selbst rechnen):\n"
        f"{_kalender_text(jetzt.date())}\n"
        "Reguläre Öffnungszeiten (genau so nennen, nie zusammenfassen oder vereinfachen):\n"
        f"{wochenplan_text(profil)}"
    )
    kommende = [
        s
        for s in profil.sonderzeiten
        if s.ende >= jetzt.date() and s.von <= jetzt.date() + dt.timedelta(days=60)
    ]
    if kommende:
        teile.append(
            "Abweichende Zeiten: "
            + "; ".join(
                f"{s.von.isoformat()}"
                + (f" bis {s.bis.isoformat()}" if s.bis else "")
                + f": {', '.join(s.zeiten) or 'geschlossen'}"
                + (f" ({s.hinweis})" if s.hinweis else "")
                for s in kommende
            )
        )
    feiertage = [
        (tag, name)
        for i in range(61)
        if (tag := jetzt.date() + dt.timedelta(days=i))
        and profil.feiertage_geschlossen
        and sonderzeit_fuer(profil, tag) is None
        and (name := feiertag(profil, tag))
    ]
    if feiertage:
        teile.append(
            "Feiertage (geschlossen): "
            + "; ".join(
                f"{WOCHENTAG_ANZEIGE[tag.weekday()]} {tag.isoformat()} {name}"
                for tag, name in feiertage
            )
        )

    if profil.leistungen:
        teile.append(
            "# Leistungen\n"
            + "\n".join(
                f"- {eintrag.name}"
                + (f", {eintrag.preis}" if eintrag.preis else "")
                + f", ca. {eintrag.dauer_min} Minuten"
                + (f". {eintrag.beschreibung}" if eintrag.beschreibung else "")
                for eintrag in profil.leistungen
            )
            + "\nNenne Preise nur so, wie sie hier stehen. Keine Rabatte oder Zusagen darüber hinaus."
        )

    if profil.faq and len(profil.faq) <= FAQ_IM_PROMPT_MAX:
        teile.append(
            "# Häufige Fragen\n"
            + "\n".join(f"F: {q.frage}\nA: {q.antwort}" for q in profil.faq)
        )

    if profil.notfall:
        teile.append(f"# Notfälle\n{profil.notfall.strip()}")

    regeln = [
        "Erfinde nichts. Was hier nicht steht, weißt du nicht; biete dann einen Rückruf an, falls möglich.",
        "Keine medizinische, rechtliche oder steuerliche Beratung.",
        "Bleib beim Anliegen des Betriebs; lehne themenfremde Bitten freundlich ab.",
        *profil.regeln,
    ]
    teile.append("# Regeln\n" + "\n".join(f"- {r}" for r in regeln))

    modul_texte = [t for m in module if (t := m.anweisungen())]
    if modul_texte:
        teile.append("# Abläufe\n" + "\n".join(modul_texte))

    anrufer = (
        f"Der Anruf kommt von {anrufer_nummer}. Sagt der Anrufer, dass diese Nummer passt, "
        "lies sie nicht vor und frag nicht erneut nach; lass das Feld telefon dann leer."
        if anrufer_nummer
        else "Die Nummer des Anrufers ist unbekannt; frag bei Bedarf danach."
    )
    teile.append(
        f"# Gespräch\n{anrufer} Wenn alles erledigt ist und sich der Anrufer verabschiedet, "
        "verabschiede dich kurz und beende den Anruf mit `end_call`."
    )

    return "\n\n".join(teile)
