"""Terminvergabe: freie Zeiten finden, buchen, eigene Termine finden und absagen."""

from __future__ import annotations

import datetime as dt

from livekit.agents import ToolError, function_tool

from ..profil import Leistung, Profil, Tageszeit
from ..speicher import Termin
from ..zeit import datum_sprechen, uhrzeit_sprechen, zeiten_am
from .basis import Modul
from .info import datum_parsen

MAX_VORSCHLAEGE = 4
SUCHTAGE_WENN_VOLL = 7

_TAGESZEITEN: dict[str, tuple[dt.time, dt.time]] = {
    "vormittag": (dt.time(0, 0), dt.time(12, 0)),
    "nachmittag": (dt.time(12, 0), dt.time(17, 0)),
    "abend": (dt.time(17, 0), dt.time(23, 59)),
}


_LEERE_NOTIZEN = {"", "-", "keine", "keine notiz", "nichts", "kein", "none", "n/a"}


def _notiz_bereinigen(notiz: str) -> str:
    """Modelle füllen optionale Felder gern mit "keine" – das soll nicht im Kalender landen."""
    notiz = notiz.strip()
    return "" if notiz.lower().rstrip(".") in _LEERE_NOTIZEN else notiz


def _verteilt(liste: list, anzahl: int) -> list:
    """Wählt gleichmäßig verteilte Einträge, damit nicht nur 9:00, 9:30, 10:00 angeboten wird."""
    if len(liste) <= anzahl:
        return liste
    schritt = (len(liste) - 1) / (anzahl - 1)
    return [liste[round(i * schritt)] for i in range(anzahl)]


class TermineModul(Modul):
    name = "termine"

    @classmethod
    def ist_aktiv(cls, profil: Profil) -> bool:
        return profil.module.termine.aktiv

    def anweisungen(self) -> str:
        return (
            "Terminvergabe: Kläre zuerst die Leistung und den Wunschtag. Rufe dann "
            "`freie_termine_suchen` auf und biete höchstens drei Zeiten an. Bevor du "
            "`termin_buchen` aufrufst, brauchst du den Namen und eine Rückrufnummer, und du "
            "wiederholst Leistung, Tag und Uhrzeit und lässt sie bestätigen. Buche nie "
            "ohne ausdrückliches Ja. Für Absagen oder Verschiebungen nutze "
            "`termine_des_anrufers_finden`, dann `termin_absagen` und bei Bedarf neu buchen."
        )

    # --- Logik ------------------------------------------------------------

    def _leistung(self, name: str) -> Leistung:
        leistung = self.k.profil.leistung_finden(name)
        if leistung is None:
            if not self.k.profil.leistungen:
                return Leistung(
                    name=name or "Termin",
                    dauer_min=self.k.profil.module.termine.raster_min,
                )
            angebot = ", ".join(x.name for x in self.k.profil.leistungen)
            raise ToolError(
                f"Leistung '{name}' gibt es nicht. Angeboten werden: {angebot}."
            )
        return leistung

    async def freie_zeiten(
        self, leistung: Leistung, datum: dt.date, tageszeit: str = "egal"
    ) -> list[dt.datetime]:
        einst = self.k.profil.module.termine
        jetzt = self.k.uhr()
        fruehestens = jetzt + dt.timedelta(hours=einst.vorlauf_stunden)
        dauer = dt.timedelta(minutes=leistung.dauer_min)
        raster = dt.timedelta(minutes=einst.raster_min)
        fenster = _TAGESZEITEN.get(tageszeit)

        spannen = zeiten_am(self.k.profil, datum)
        if not spannen:
            return []
        tz = jetzt.tzinfo
        tag_beginn = dt.datetime.combine(datum, dt.time(0, 0), tzinfo=tz)
        belegt = await self.k.kalender.termine_zwischen(
            tag_beginn, tag_beginn + dt.timedelta(days=1)
        )

        frei: list[dt.datetime] = []
        for von, bis in spannen:
            beginn = dt.datetime.combine(datum, von, tzinfo=tz)
            ende_spanne = dt.datetime.combine(datum, bis, tzinfo=tz)
            while beginn + dauer <= ende_spanne:
                ende = beginn + dauer
                im_fenster = fenster is None or fenster[0] <= beginn.time() < fenster[1]
                if beginn >= fruehestens and im_fenster:
                    ueberlappend = [
                        t for t in belegt if t.beginn < ende and t.ende > beginn
                    ]
                    blockiert = any(t.exklusiv for t in ueberlappend)
                    if not blockiert and len(ueberlappend) < einst.parallel:
                        frei.append(beginn)
                beginn += raster
        return frei

    def _datum_pruefen(self, tag: dt.date) -> None:
        heute = self.k.uhr().date()
        if tag < heute:
            raise ToolError("Das Datum liegt in der Vergangenheit.")
        max_tage = self.k.profil.module.termine.max_tage_voraus
        if tag > heute + dt.timedelta(days=max_tage):
            raise ToolError(f"Termine gibt es nur bis zu {max_tage} Tage im Voraus.")

    # --- Tools ------------------------------------------------------------

    @function_tool
    async def freie_termine_suchen(
        self, leistung: str, datum: str, tageszeit: Tageszeit = "egal"
    ) -> str:
        """Sucht freie Termine für eine Leistung an einem Wunschtag. Ist der Tag voll, werden die nächsten Tage durchsucht.

        Args:
            leistung: Name der gewünschten Leistung, wie im Angebot aufgeführt
            datum: Wunschtag im Format JJJJ-MM-TT
            tageszeit: Bevorzugte Tageszeit, falls genannt
        """
        gewuenscht = datum_parsen(datum)
        self._datum_pruefen(gewuenscht)
        gewaehlt = self._leistung(leistung)
        heute = self.k.uhr().date()

        for offset in range(SUCHTAGE_WENN_VOLL + 1):
            tag = gewuenscht + dt.timedelta(days=offset)
            if tag > heute + dt.timedelta(
                days=self.k.profil.module.termine.max_tage_voraus
            ):
                break
            frei = await self.freie_zeiten(gewaehlt, tag, tageszeit)
            if frei:
                zeiten = ", ".join(
                    uhrzeit_sprechen(z.time()) for z in _verteilt(frei, MAX_VORSCHLAEGE)
                )
                praefix = (
                    ""
                    if offset == 0
                    else "Am Wunschtag ist nichts frei. Nächster freier Tag: "
                )
                return (
                    f"{praefix}{datum_sprechen(tag, heute)} ({tag.isoformat()}) "
                    f"für {gewaehlt.name}: {zeiten}."
                )
        return (
            f"In den {SUCHTAGE_WENN_VOLL + 1} Tagen ab {datum_sprechen(gewuenscht, heute)} "
            "ist nichts frei. Biete einen Rückruf an."
        )

    @function_tool
    async def termin_buchen(
        self,
        leistung: str,
        datum: str,
        uhrzeit: str,
        name: str,
        telefon: str = "",
        notiz: str = "",
    ) -> str:
        """Bucht einen Termin verbindlich. Nur aufrufen, nachdem der Anrufer die Details ausdrücklich bestätigt hat.

        Args:
            leistung: Name der Leistung
            datum: Datum im Format JJJJ-MM-TT
            uhrzeit: Beginn im Format HH:MM
            name: Vor- und Nachname des Kunden
            telefon: Rückrufnummer des Kunden. Leer lassen, wenn die Nummer des Anrufers passt.
            notiz: Optionale Zusatzinfo, z. B. Anliegen oder Wünsche. Leer lassen, wenn es keine gibt.
        """
        tag = datum_parsen(datum)
        self._datum_pruefen(tag)
        gewaehlt = self._leistung(leistung)
        try:
            beginn_zeit = dt.time.fromisoformat(uhrzeit.strip())
        except ValueError as e:
            raise ToolError(f"Ungültige Uhrzeit '{uhrzeit}', erwartet HH:MM.") from e
        if not name.strip():
            raise ToolError("Für die Buchung fehlt noch der Name.")
        telefon = telefon.strip() or self.k.anrufer_nummer
        if not telefon:
            raise ToolError("Für die Buchung fehlt noch eine Telefonnummer.")

        beginn = dt.datetime.combine(tag, beginn_zeit, tzinfo=self.k.uhr().tzinfo)
        if beginn not in await self.freie_zeiten(gewaehlt, tag):
            raise ToolError(
                "Diese Zeit ist nicht (mehr) frei. Suche mit `freie_termine_suchen` neue Zeiten."
            )

        termin = await self.k.kalender.buchen(
            Termin(
                leistung=gewaehlt.name,
                beginn=beginn,
                ende=beginn + dt.timedelta(minutes=gewaehlt.dauer_min),
                name=name.strip(),
                telefon=telefon,
                notiz=_notiz_bereinigen(notiz),
            )
        )
        await self.k.benachrichtiger.senden("termin_gebucht", termin.als_dict())
        return (
            f"Gebucht: {gewaehlt.name} am {datum_sprechen(tag)} um {uhrzeit_sprechen(beginn_zeit)} "
            f"für {termin.name}."
        )

    @function_tool
    async def termine_des_anrufers_finden(self, telefon: str = "") -> str:
        """Findet die kommenden Termine eines Kunden anhand seiner Telefonnummer.

        Args:
            telefon: Telefonnummer, unter der gebucht wurde. Leer lassen, um die Nummer des Anrufers zu verwenden.
        """
        nummer = telefon.strip() or self.k.anrufer_nummer
        if not nummer:
            raise ToolError("Frag nach der Telefonnummer, unter der gebucht wurde.")
        termine = await self.k.kalender.termine_von(nummer, self.k.uhr())
        if not termine:
            return "Unter dieser Nummer sind keine kommenden Termine gebucht."
        heute = self.k.uhr().date()
        return "\n".join(
            f"[id {t.id}] {t.leistung} {datum_sprechen(t.beginn.date(), heute)} um "
            f"{uhrzeit_sprechen(t.beginn.time())}, auf {t.name}"
            for t in termine
        )

    @function_tool
    async def termin_absagen(self, termin_id: str) -> str:
        """Sagt einen Termin ab. Nur nach ausdrücklicher Bestätigung durch den Anrufer.

        Args:
            termin_id: Die id aus `termine_des_anrufers_finden` (nicht vorlesen)
        """
        termin = await self.k.kalender.absagen(termin_id.strip())
        if termin is None:
            raise ToolError("Termin nicht gefunden oder bereits abgesagt.")
        await self.k.benachrichtiger.senden("termin_abgesagt", termin.als_dict())
        return (
            f"Abgesagt: {termin.leistung} am {datum_sprechen(termin.beginn.date())} "
            f"um {uhrzeit_sprechen(termin.beginn.time())}."
        )
