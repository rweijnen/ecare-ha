"""eCare sensor entities."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
    async_add_entities([
        EcareDagboekSensor(coordinator, entry),
        EcareLastEventSensor(coordinator, entry),
    ])


class EcareDagboekSensor(CoordinatorEntity, SensorEntity):
    """Aantal dagboek-items."""

    _attr_icon = "mdi:notebook-outline"

    def __init__(self, coordinator: EcareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_dagboek_count"
        self._attr_name = "eCare Dagboek Items"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self) -> dict:
        events = self.coordinator.data or []
        if not events:
            return {}
        latest = events[0]
        return {
            "laatste_datum":  latest.get("Datum", {}).get("tekst", ""),
            "laatste_auteur": (latest.get("Medewerker") or {}).get("WeergaveNaam", ""),
            "laatste_type":   latest.get("GebeurtenisType", ""),
        }


class EcareLastEventSensor(CoordinatorEntity, SensorEntity):
    """Omschrijving van het meest recente dagboek-item."""

    _attr_icon = "mdi:text-box-outline"

    def __init__(self, coordinator: EcareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_last_event"
        self._attr_name = "eCare Laatste Gebeurtenis"

    @property
    def native_value(self) -> str | None:
        events = self.coordinator.data or []
        if not events:
            return None
        e = events[0]
        datum = e.get("Datum", {}).get("tekst", "")
        wie = (e.get("Medewerker") or {}).get("WeergaveNaam") or e.get("AlsDiscipline", "")
        onderwerp = e.get("Onderwerp") or e.get("GebeurtenisType", "")
        return f"{datum} — {wie}: {onderwerp}"[:255]
