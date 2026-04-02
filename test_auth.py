"""
Lokale test voor de eCare auth flow — geen Home Assistant nodig.
Gebruik: python test_auth.py

Vereist: pip install aiohttp
"""
import asyncio
import json
import logging
import os
import sys

# Logging op DEBUG zodat we alles zien
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Minder ruis van aiohttp zelf
logging.getLogger("aiohttp").setLevel(logging.WARNING)

# Laad custom_components.ecare als package zonder homeassistant
import importlib
import types

# Maak lege parent packages aan
for pkg in ("custom_components", "custom_components.ecare"):
    if pkg not in sys.modules:
        sys.modules[pkg] = types.ModuleType(pkg)

# Laad const.py en api.py als onderdeel van het package
_base = os.path.join(os.path.dirname(__file__), "custom_components", "ecare")
import importlib.util

for _name in ("const", "api"):
    _fullname = f"custom_components.ecare.{_name}"
    _spec = importlib.util.spec_from_file_location(
        _fullname,
        os.path.join(_base, f"{_name}.py"),
        submodule_search_locations=[],
    )
    _mod = importlib.util.module_from_spec(_spec)
    _mod.__package__ = "custom_components.ecare"
    sys.modules[_fullname] = _mod
    _spec.loader.exec_module(_mod)

from custom_components.ecare.api import AuthError, EcareAuthClient

CACHE_FILE = os.path.join(os.path.dirname(__file__), ".auth_cache.json")


def load_cache() -> dict | None:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return None


def save_cache(cookies: dict) -> None:
    with open(CACHE_FILE, "w") as f:
        json.dump({"cookies": cookies}, f)
    print(f"Sessie opgeslagen in {CACHE_FILE}")


async def get_token() -> str:
    """Geeft een geldig access token terug — gebruikt cache indien mogelijk."""
    cache = load_cache()
    if cache:
        print("Opgeslagen sessie gevonden — probeer silent renewal...")
        try:
            async with EcareAuthClient() as client:
                token = await client.get_fresh_token(cache["cookies"])
                save_cache(client._export_cookies())
                print("Silent renewal geslaagd.")
                return token
        except AuthError as e:
            print(f"Silent renewal mislukt ({e}) — volledig inloggen vereist.")

    # Volledige login
    email = input("E-mailadres: ").strip()
    password = input("Wachtwoord: ").strip()

    print("\n--- Stap 1: inloggen ---")
    async with EcareAuthClient() as client:
        result = await client.start_login(email, password)

    if result["status"] == "ok":
        print("Direct ingelogd (geen SMS vereist)")
        save_cache(result["cookies"])
        return result["access_token"]

    if result["status"] == "need_sms":
        print(f"SMS verstuurd — pagina: {result['sms_url']}")
        sms_code = input("\nVoer de SMS code in: ").strip()

        print("\n--- Stap 2: SMS code indienen ---")
        async with EcareAuthClient() as client2:
            result2 = await client2.complete_sms(
                result["sms_url"], sms_code, result["cookies"]
            )

        save_cache(result2["cookies"])
        return result2["access_token"]

    raise RuntimeError(f"Onverwacht login resultaat: {result}")


async def main():
    access_token = await get_token()
    print(f"\nAccess token: {access_token[:40]}...")

    async with EcareAuthClient() as client:
        planning     = await client.get_planning(access_token)
        client_info  = await client.get_mijngegevens(access_token)
        metingen     = await client.get_metingen(access_token)

    print(f"\nCliënt: {client_info['naam']} (geboren {client_info['geboortedatum']})")

    print(f"\n{len(planning)} komende bezoeken:")
    for b in planning:
        print(f"  {b['dag']} {b['datum']} {b['tijd']} — {b['wie']} ({b['locatie']})")

    print("\nMetingen (laatste waarden):")
    for k, v in metingen.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
