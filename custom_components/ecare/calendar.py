"""eCare Calendar entity — toont zorgbezoeken in de HA kalender."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EcareCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EcareCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EcarePlanningCalendar(coordinator, entry)])


class EcarePlanningCalendar(CoordinatorEntity, CalendarEntity):
    _attr_icon = "mdi:calendar-heart"

    def __init__(self, coordinator: EcareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_name = "eCare Planning"

    def _bezoeken(self) -> list[dict]:
        return (self.coordinator.data or {}).get("planning") or []

    @staticmethod
    def _to_event(bezoek: dict) -> CalendarEvent | None:
        datum_iso = bezoek.get("datum_iso", "")
        tijd_tekst = bezoek.get("tijd", "")
        if not datum_iso or not tijd_tekst:
            return None
        try:
            start = datetime.strptime(f"{datum_iso} {tijd_tekst}", "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        end = start + timedelta(hours=1)
        wie = bezoek.get("wie", "")
        locatie = bezoek.get("locatie", "")
        summary = wie or "Zorgbezoek"
        return CalendarEvent(
            start=start,
            end=end,
            summary=summary,
            description=locatie or None,
            location=locatie or None,
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Eerstvolgende bezoek (voor het kalender-badge icoontje)."""
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
            if ev and ev.start < end_date and ev.end > start_date:
                events.append(ev)
        return events
