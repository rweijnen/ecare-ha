"""eCare sensor entities."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EcareCoordinator, _strip_html
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
        EcarePlanningNextSensor(coordinator, entry),
        EcareClientSensor(coordinator, entry),
        EcareGewichtSensor(coordinator, entry),
        EcareBloedrukSensor(coordinator, entry),
        EcareHartslagSensor(coordinator, entry),
        EcareTemperatuurSensor(coordinator, entry),
        EcareGlucoseSensor(coordinator, entry),
        EcarePijnSensor(coordinator, entry),
    ])


class _EcareBase(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: EcareCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    def _data(self) -> dict:
        return self.coordinator.data or {}


# ------------------------------------------------------------------
# Dagboek
# ------------------------------------------------------------------

class EcareDagboekSensor(_EcareBase):
    _attr_icon = "mdi:notebook-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "dagboek_count")
        self._attr_name = "eCare Dagboek Items"

    @property
    def native_value(self) -> int:
        return len(self._data().get("dagboek") or [])

    @property
    def extra_state_attributes(self) -> dict:
        events = self._data().get("dagboek") or []
        if not events:
            return {}
        latest = events[0]
        recente = []
        for e in events[:10]:
            acties = e.get("Acties") or []
            wie = (
                (e.get("Medewerker") or {}).get("WeergaveNaam")
                or e.get("AangemaaktDoorDisplayName")
                or ""
            )
            tekst = (
                e.get("Toelichting")
                or " | ".join(a.get("Zorgbeschrijving", "") for a in acties if a.get("Zorgbeschrijving"))
                or ""
            )
            recente.append({
                "datum":      e.get("Datum", {}).get("tekst", ""),
                "tijd":       e.get("Tijd", {}).get("Tekst", ""),
                "type":       e.get("GebeurtenisType", ""),
                "wie":        wie,
                "initiaal":   e.get("Initials", wie[0].upper() if wie else "?"),
                "kleur":      e.get("Color", "#7f8c8d"),
                "discipline": e.get("AlsDiscipline") or e.get("AangemaaktDoorDiscipline") or "",
                "onderwerp":  e.get("Onderwerp") or (acties[0].get("Probleemgebied") if acties else "") or "",
                "tekst":      _strip_html(tekst),
            })
        return {
            "laatste_datum":   latest.get("Datum", {}).get("tekst", ""),
            "laatste_auteur":  (latest.get("Medewerker") or {}).get("WeergaveNaam", ""),
            "laatste_type":    latest.get("GebeurtenisType", ""),
            "recente_items":   recente,
        }


class EcareLastEventSensor(_EcareBase):
    _attr_icon = "mdi:text-box-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_event")
        self._attr_name = "eCare Laatste Gebeurtenis"

    @property
    def native_value(self) -> str | None:
        events = self._data().get("dagboek") or []
        if not events:
            return None
        e = events[0]
        datum = e.get("Datum", {}).get("tekst", "")
        wie = (e.get("Medewerker") or {}).get("WeergaveNaam") or ""
        onderwerp = e.get("Onderwerp") or e.get("GebeurtenisType", "")
        return f"{datum} — {wie}: {onderwerp}"[:255]


# ------------------------------------------------------------------
# Planning
# ------------------------------------------------------------------

class EcarePlanningNextSensor(_EcareBase):
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "planning_next")
        self._attr_name = "eCare Eerstvolgende Bezoek"

    @property
    def native_value(self) -> str | None:
        bezoeken = self._data().get("planning") or []
        if not bezoeken:
            return None
        b = bezoeken[0]
        return f"{b['dag']} {b['tijd']} — {b['wie']}"[:255]

    @property
    def extra_state_attributes(self) -> dict:
        bezoeken = self._data().get("planning") or []
        return {"bezoeken": bezoeken}


# ------------------------------------------------------------------
# Cliënt
# ------------------------------------------------------------------

class EcareClientSensor(_EcareBase):
    _attr_icon = "mdi:account"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "client")
        self._attr_name = "eCare Cliënt"

    @property
    def native_value(self) -> str | None:
        return (self._data().get("client") or {}).get("naam") or None

    @property
    def entity_picture(self) -> str | None:
        return (self._data().get("client") or {}).get("avatar") or None

    @property
    def extra_state_attributes(self) -> dict:
        client = self._data().get("client") or {}
        attrs = {"geboortedatum": client.get("geboortedatum", "")}
        for key in ("avatar", "telefoon", "email", "adres"):
            val = client.get(key, "")
            if val:
                attrs[key] = val
        return attrs


# ------------------------------------------------------------------
# Metingen
# ------------------------------------------------------------------

class EcareGewichtSensor(_EcareBase):
    _attr_icon = "mdi:scale-bathroom"
    _attr_native_unit_of_measurement = "kg"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "gewicht")
        self._attr_name = "eCare Gewicht"

    @property
    def native_value(self) -> float | None:
        m = (self._data().get("metingen") or {}).get("gewicht")
        return m.get("Weight") if m else None

    @property
    def extra_state_attributes(self) -> dict:
        m = (self._data().get("metingen") or {}).get("gewicht")
        if not m:
            return {}
        return {
            "datum":   m.get("Date", {}).get("tekst", "") if isinstance(m.get("Date"), dict) else str(m.get("Date", "")),
            "gekleed": m.get("Dressed"),
        }


class EcareBloedrukSensor(_EcareBase):
    _attr_icon = "mdi:heart-pulse"
    _attr_native_unit_of_measurement = "mmHg"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "bloeddruk")
        self._attr_name = "eCare Bloeddruk"

    @property
    def native_value(self) -> str | None:
        m = (self._data().get("metingen") or {}).get("bht")
        if not m:
            return None
        s, d = m.get("Systolic"), m.get("Diastolic")
        if s and d:
            return f"{s}/{d}"
        return None

    @property
    def extra_state_attributes(self) -> dict:
        m = (self._data().get("metingen") or {}).get("bht")
        if not m:
            return {}
        return {
            "systolisch":  m.get("Systolic"),
            "diastolisch": m.get("Diastolic"),
            "datum":       m.get("Date", {}).get("tekst", "") if isinstance(m.get("Date"), dict) else str(m.get("Date", "")),
        }


class EcareHartslagSensor(_EcareBase):
    _attr_icon = "mdi:heart"
    _attr_native_unit_of_measurement = "bpm"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "hartslag")
        self._attr_name = "eCare Hartslag"

    @property
    def native_value(self) -> int | None:
        m = (self._data().get("metingen") or {}).get("bht")
        return m.get("Frequency") if m else None

    @property
    def extra_state_attributes(self) -> dict:
        m = (self._data().get("metingen") or {}).get("bht")
        if not m:
            return {}
        return {
            "regelmaat": m.get("Regularity"),
            "datum":     m.get("Date", {}).get("tekst", "") if isinstance(m.get("Date"), dict) else str(m.get("Date", "")),
        }


class EcareTemperatuurSensor(_EcareBase):
    _attr_icon = "mdi:thermometer"
    _attr_native_unit_of_measurement = "°C"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "temperatuur")
        self._attr_name = "eCare Temperatuur"

    @property
    def native_value(self) -> float | None:
        m = (self._data().get("metingen") or {}).get("bht")
        return m.get("Temperature") if m else None


class EcareGlucoseSensor(_EcareBase):
    _attr_icon = "mdi:diabetes"
    _attr_native_unit_of_measurement = "mmol/L"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "glucose")
        self._attr_name = "eCare Glucose"

    @property
    def native_value(self) -> float | None:
        m = (self._data().get("metingen") or {}).get("glucose")
        return m.get("GlucoseLevel") if m else None

    @property
    def extra_state_attributes(self) -> dict:
        m = (self._data().get("metingen") or {}).get("glucose")
        if not m:
            return {}
        return {
            "moment": m.get("MomentName"),
            "datum":  m.get("Date", {}).get("tekst", "") if isinstance(m.get("Date"), dict) else str(m.get("Date", "")),
        }


class EcarePijnSensor(_EcareBase):
    _attr_icon = "mdi:emoticon-sad-outline"
    _attr_native_unit_of_measurement = "/ 10"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "pijn")
        self._attr_name = "eCare Pijnscore"

    @property
    def native_value(self) -> int | None:
        m = (self._data().get("metingen") or {}).get("pijn")
        return m.get("Score") if m else None
