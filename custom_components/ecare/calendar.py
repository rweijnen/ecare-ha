"""eCare Calendar entities — planning bezoeken en dagboek zorgmomenten."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import EcareCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EcareCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        EcarePlanningCalendar(coordinator, entry),
        EcareZorgmomentenCalendar(coordinator, entry),
    ])


# ------------------------------------------------------------------
# Planning kalender (bezoeken: huidig + historie)
# ------------------------------------------------------------------

class EcarePlanningCalendar(CoordinatorEntity[EcareCoordinator], CalendarEntity):
    _attr_icon = "mdi:calendar-heart"

    def __init__(self, coordinator: EcareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_name = "eCare Planning"

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    @staticmethod
    def _bezoek_to_event(bezoek: dict) -> CalendarEvent | None:
        datum_iso = bezoek.get("datum_iso", "")
        tijd_tekst = bezoek.get("tijd", "")
        if not datum_iso or not tijd_tekst:
            return None
        try:
            start = dt_util.as_local(datetime.strptime(f"{datum_iso} {tijd_tekst}", "%Y-%m-%d %H:%M"))
        except ValueError:
            return None
        tijd_tot = bezoek.get("tijd_tot", "")
        if datum_iso and tijd_tot:
            try:
                end = dt_util.as_local(datetime.strptime(f"{datum_iso} {tijd_tot}", "%Y-%m-%d %H:%M"))
            except ValueError:
                end = start + timedelta(hours=1)
        else:
            end = start + timedelta(hours=1)
        wie = bezoek.get("wie", "") or "Zorgbezoek"
        locatie = bezoek.get("locatie") or None
        return CalendarEvent(
            start=start,
            end=end,
            summary=wie,
            description=locatie,
            location=locatie,
        )

    def _current_bezoeken(self) -> list[dict]:
        return (self.coordinator.data or {}).get("planning") or []

    def _history_bezoeken(self) -> list[dict]:
        history = (self.coordinator.data or {}).get("planning_history") or {}
        result = []
        for bezoeken in history.values():
            result.extend(bezoeken)
        return result

    @property
    def event(self) -> CalendarEvent | None:
        for bezoek in self._current_bezoeken():
            ev = self._bezoek_to_event(bezoek)
            if ev:
                return ev
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        events = []
        seen_keys: set[str] = set()

        # Huidige planning (toekomst)
        for bezoek in self._current_bezoeken():
            ev = self._bezoek_to_event(bezoek)
            if ev and ev.end > start_date and ev.start < end_date:
                key = f"{bezoek.get('datum_iso')}-{bezoek.get('tijd')}"
                seen_keys.add(key)
                events.append(ev)

        # Opgeslagen planning historie (verleden)
        for bezoek in self._history_bezoeken():
            key = f"{bezoek.get('datum_iso')}-{bezoek.get('tijd')}"
            if key in seen_keys:
                continue
            ev = self._bezoek_to_event(bezoek)
            if ev and ev.end > start_date and ev.start < end_date:
                seen_keys.add(key)
                events.append(ev)

        return events


# ------------------------------------------------------------------
# Zorgmomenten kalender (dagboek entries)
# ------------------------------------------------------------------

class EcareZorgmomentenCalendar(CoordinatorEntity[EcareCoordinator], CalendarEntity):
    _attr_icon = "mdi:notebook-heart"

    def __init__(self, coordinator: EcareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar_zorgmomenten"
        self._attr_name = "eCare Zorgmomenten"

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    @staticmethod
    def _zorgmoment_to_event(event: dict) -> CalendarEvent | None:
        datum_raw = event.get("Datum", {}).get("Datum", "")
        tijd_raw = event.get("Tijd", {}).get("Tekst", "")
        if not datum_raw or not tijd_raw:
            return None
        datum_iso = datum_raw[:10]
        try:
            start = dt_util.as_local(datetime.strptime(f"{datum_iso} {tijd_raw}", "%Y-%m-%d %H:%M"))
        except ValueError:
            return None
        end = start + timedelta(minutes=30)
        wie = (
            (event.get("Medewerker") or {}).get("WeergaveNaam")
            or event.get("AangemaaktDoorDisplayName")
            or ""
        )
        acties = event.get("Acties") or []
        onderwerp = (
            event.get("Onderwerp")
            or (acties[0].get("Probleemgebied") if acties else "")
            or ""
        )
        discipline = event.get("AlsDiscipline") or event.get("AangemaaktDoorDiscipline") or ""
        toelichting = re.sub(r"<[^>]+>", " ", event.get("Toelichting") or "").strip()
        acties_tekst = " | ".join(
            a.get("Zorgbeschrijving", "") for a in acties if a.get("Zorgbeschrijving")
        )
        beschrijving_delen = [d for d in [onderwerp, toelichting, acties_tekst] if d]
        beschrijving = "\n\n".join(beschrijving_delen)

        summary = f"{wie}: {onderwerp}" if onderwerp else wie
        if discipline and not onderwerp:
            summary = f"{wie} ({discipline})"
        summary = summary[:80]
        return CalendarEvent(
            start=start,
            end=end,
            summary=summary,
            description=beschrijving[:500] if beschrijving else f"Zorgmoment door {wie}",
        )

    def _zorgmomenten(self) -> list[dict]:
        events = (self.coordinator.data or {}).get("dagboek") or []
        return [e for e in events if e.get("GebeurtenisType") == "zorgmoment"]

    @property
    def event(self) -> CalendarEvent | None:
        for zm in self._zorgmomenten():
            ev = self._zorgmoment_to_event(zm)
            if ev:
                return ev
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        events = []
        for zm in self._zorgmomenten():
            ev = self._zorgmoment_to_event(zm)
            if ev and ev.end > start_date and ev.start < end_date:
                events.append(ev)
        return events
