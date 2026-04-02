"""Config flow voor eCare integratie — ondersteunt SMS 2FA."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import AuthError, EcareAuthClient
from .const import (
    CONF_COOKIES,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_SMS_SCHEMA = vol.Schema(
    {
        vol.Required("sms_code"): str,
    }
)


class EcareConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Multi-stap config flow: e-mail/wachtwoord → SMS code."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str = ""
        self._password: str = ""
        self._sms_url: str = ""
        self._sms_form_fields: dict = {}
        self._cookies: dict = {}
        self._client: EcareAuthClient | None = None

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Stap 1: e-mail en wachtwoord invoeren."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]

            try:
                async with EcareAuthClient() as client:
                    self._client = client
                    result = await client.start_login(self._email, self._password)

                if result["status"] == "ok":
                    # Geen 2FA nodig (onwaarschijnlijk maar mogelijk)
                    return self._create_entry(result["access_token"], result["cookies"])

                if result["status"] == "need_sms":
                    self._sms_url = result["sms_url"]
                    self._cookies = result["cookies"]
                    return await self.async_step_sms()

            except AuthError as e:
                errors["base"] = "auth_error"
                # Sla de foutmelding op voor display
                self._last_error = str(e)
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={
                "error_detail": getattr(self, "_last_error", "")
            },
        )

    async def async_step_sms(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Stap 2: SMS verificatiecode invoeren."""
        errors: dict[str, str] = {}

        if user_input is not None:
            sms_code = user_input["sms_code"].strip()

            try:
                async with EcareAuthClient() as client:
                    result = await client.complete_sms(
                        self._sms_url, sms_code, self._cookies
                    )

                return self._create_entry(result["access_token"], result["cookies"])

            except AuthError as e:
                errors["base"] = "sms_error"
                self._last_error = str(e)
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="sms",
            data_schema=STEP_SMS_SCHEMA,
            errors=errors,
            description_placeholders={
                "error_detail": getattr(self, "_last_error", "")
            },
        )

    def _create_entry(self, access_token: str, cookies: dict) -> FlowResult:
        """Maak de config entry aan na succesvolle login."""
        return self.async_create_entry(
            title=self._email,
            data={
                CONF_EMAIL: self._email,
                CONF_PASSWORD: self._password,
                CONF_COOKIES: cookies,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EcareOptionsFlow(config_entry)


class EcareOptionsFlow(config_entries.OptionsFlow):
    """Options flow voor poll interval."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=60,
                            step=1,
                            unit_of_measurement="minuten",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
