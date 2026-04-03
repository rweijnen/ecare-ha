"""eCare Calendar entity — toont zorgbezoeken in de HA kalender."""
from __future__ import annotations

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
    async_add_entities([EcarePlanningCalendar(coordinator, entry)])


class EcarePlanningCalendar(CoordinatorEntity[EcareCoordinator], CalendarEntity):
    _attr_icon = "mdi:calendar-heart"

    def __init__(self, coordinator: EcareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_name = "eCare Planning"

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    def _bezoeken(self) -> list[dict]:
        return (self.coordinator.data or {}).get("planning") or []

    @staticmethod
    def _to_event(bezoek: dict) -> CalendarEvent | None:
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

    @property
    def event(self) -> CalendarEvent | None:
        for bezoek in self._bezoeken():
            ev = self._to_event(bezoek)
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
        for bezoek in self._bezoeken():
            ev = self._to_event(bezoek)
            if ev and ev.end > start_date and ev.start < end_date:
                events.append(ev)
        return events
