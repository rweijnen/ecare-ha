"""eCare Dossier Monitor integratie voor Home Assistant."""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthError, EcareAuthClient
from .const import (
    CONF_COOKIES,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    STATE_FILE_KEY,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up eCare vanuit een config entry."""
    coordinator = EcareCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload eCare config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


class EcareCoordinator(DataUpdateCoordinator):
    """Coördinator die de eCare dagboek API pollt en events vuurt."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )
        self._entry = entry
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._known_ids: set[str] = set()
        self._cookies: dict = dict(entry.data.get(CONF_COOKIES, {}))
        self._access_token: str = ""

    async def _async_update_data(self) -> list[dict]:
        """Haal dagboek op, vuur events voor nieuwe items."""
        # Laad bekende IDs uit persistent storage
        if not self._known_ids:
            stored = await self._store.async_load() or {}
            self._known_ids = set(stored.get(STATE_FILE_KEY, []))

        try:
            async with EcareAuthClient() as client:
                # Token vernieuwen via silent renewal (geen SMS nodig)
                try:
                    self._access_token = await client.get_fresh_token(self._cookies)
                    # Sla vernieuwde cookies op
                    new_cookies = client._export_cookies()
                    if new_cookies:
                        self._cookies.update(new_cookies)
                        self.hass.config_entries.async_update_entry(
                            self._entry,
                            data={**self._entry.data, CONF_COOKIES: self._cookies},
                        )
                except AuthError as e:
                    _LOGGER.warning("Silent renewal mislukt (%s), opnieuw inloggen nodig", e)
                    # Probeer opnieuw in te loggen met opgeslagen credentials
                    login_result = await client.start_login(
                        self._entry.data[CONF_EMAIL],
                        self._entry.data[CONF_PASSWORD],
                    )
                    if login_result["status"] != "ok":
                        raise UpdateFailed(
                            "Sessie verlopen en opnieuw inloggen vereist SMS. "
                            "Ga naar Instellingen → Integraties → eCare → Opnieuw configureren."
                        ) from e
                    self._access_token = login_result["access_token"]
                    self._cookies = login_result["cookies"]

                events = await client.get_dagboek(self._access_token)

        except AuthError as e:
            raise UpdateFailed(f"eCare API fout: {e}") from e

        # Detecteer nieuwe items
        new_events = [e for e in events if str(e["Id"]) not in self._known_ids]

        for event in new_events:
            _LOGGER.info(
                "Nieuw dagboek-item: %s — %s",
                event.get("Datum", {}).get("tekst", ""),
                event.get("Onderwerp") or event.get("GebeurtenisType", ""),
            )
            self.hass.bus.async_fire(
                f"{DOMAIN}_new_item",
                {
                    "id":        str(event["Id"]),
                    "type":      event.get("GebeurtenisType", ""),
                    "datum":     event.get("Datum", {}).get("tekst", ""),
                    "tijd":      event.get("Tijd", {}).get("Tekst", ""),
                    "wie":       (event.get("Medewerker") or {}).get("WeergaveNaam", ""),
                    "discipline":event.get("AlsDiscipline", ""),
                    "onderwerp": event.get("Onderwerp") or "",
                    "tekst":     _strip_html(event.get("Toelichting") or "")[:500],
                },
            )

        if new_events:
            self._known_ids.update(str(e["Id"]) for e in new_events)
            await self._store.async_save({STATE_FILE_KEY: list(self._known_ids)})

        # Initialiseer state bij eerste run
        if events and not self._known_ids:
            self._known_ids = {str(e["Id"]) for e in events}
            await self._store.async_save({STATE_FILE_KEY: list(self._known_ids)})

        return events


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).strip()
