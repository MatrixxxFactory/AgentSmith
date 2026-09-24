"""Rückrufbitten und Nachrichten für den Betrieb aufnehmen."""

from __future__ import annotations

from livekit.agents import ToolError, function_tool

from ..profil import Profil
from ..speicher import Nachricht
from .basis import Modul


class RueckrufModul(Modul):
    name = "rueckruf"

    @classmethod
    def ist_aktiv(cls, profil: Profil) -> bool:
        return profil.module.rueckruf.aktiv

    def anweisungen(self) -> str:
        return (
            "Rückruf: Wenn du etwas nicht selbst klären kannst, biete an, eine Nachricht "
            "aufzunehmen. Frag nach Name und Anliegen; frag, ob die Nummer, von der angerufen "
            "wird, für den Rückruf passt. Dann `rueckruf_notieren`. Versprich keinen genauen "
            "Rückrufzeitpunkt."
        )

    @function_tool
    async def rueckruf_notieren(
        self, name: str, anliegen: str, telefon: str = "", dringend: bool = False
    ) -> str:
        """Legt eine Rückrufbitte bzw. Nachricht für das Team des Betriebs ab.

        Args:
            name: Name des Anrufers
            anliegen: Worum es geht, in ein bis zwei Sätzen, mit allen genannten Details
            telefon: Rückrufnummer. Leer lassen, wenn die Nummer des Anrufers passt.
            dringend: True, wenn es eilt (z. B. Notfall, Schaden, Fristablauf)
        """
        nummer = telefon.strip() or self.k.anrufer_nummer
        if not nummer:
            raise ToolError("Es fehlt eine Rückrufnummer. Frag danach.")
        if not name.strip() or not anliegen.strip():
            raise ToolError("Name und Anliegen werden benötigt.")
        nachricht = await self.k.postfach.ablegen(
            Nachricht(
                art="rueckruf",
                name=name.strip(),
                telefon=nummer,
                anliegen=anliegen.strip(),
                dringend=dringend,
            )
        )
        await self.k.benachrichtiger.senden("rueckruf", nachricht.als_dict())
        return "Rückrufbitte ist notiert und wurde an das Team weitergegeben."
