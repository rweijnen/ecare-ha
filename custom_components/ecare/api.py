"""eCare HTTP client — OIDC login flow + API calls.

Bekende IDP flow (pvj-idp.ecare.nl / IdentityServer4):

  Stap 1 — Login:
    GET  /connect/authorize?...              → redirect naar /Account/Login
    POST /Account/Login                      → 302
      a) Als Identity.TwoFactorRememberMe cookie geldig:
           → /connect/authorize/callback → silent-refresh.html#access_token=...
      b) Anders:
           → /Account/TwoFactorAuthenticate?username=...&returnUrl=...

  Stap 2 — SMS (alleen bij b):
    GET  /Account/TwoFactorAuthenticate      → form met velden:
           ReturnUrl, UserName, Code (text), __RequestVerificationToken
    POST /Account/TwoFactorAuthenticate      → 302
           → /connect/authorize/callback
           → callback.html#access_token=...  (+ set Identity.TwoFactorRememberMe cookie)

  Token renewal (geen SMS):
    GET  /connect/authorize?prompt=none      → redirect keten
           → silent-refresh.html#access_token=...
"""
from __future__ import annotations

import logging
import re
import secrets
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

_LOGGER = logging.getLogger(__name__)

import aiohttp

from .const import CLIENT_ID, IDP_BASE, PORTAL_BASE, REDIRECT_URI, SCOPE

TWO_FACTOR_PATH = "/Account/TwoFactorAuthenticate"
LOGIN_PATH = "/Account/Login"
AUTHORIZE_PATH = "/connect/authorize"
CALLBACK_PATH = "/connect/authorize/callback"


class AuthError(Exception):
    pass


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields: dict[str, str] = {}
        self.action: str = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and "action" in attrs:
            self.action = attrs["action"]
        if tag == "input" and "name" in attrs:
            self.fields[attrs["name"]] = attrs.get("value", "")


def _parse_form(html: str, base_url: str = "") -> tuple[str, dict[str, str]]:
    parser = _FormParser()
    parser.feed(html)
    action = parser.action or base_url
    if action and not action.startswith("http"):
        action = urljoin(base_url, action)
    return action, parser.fields


def _token_from_fragment(url: str) -> str | None:
    """Extract access_token from URL fragment (#access_token=...)."""
    fragment = urlparse(url).fragment
    if not fragment:
        return None
    params = parse_qs(fragment)
    tokens = params.get("access_token", [])
    return tokens[0] if tokens else None


def _error_from_fragment(url: str) -> str | None:
    fragment = urlparse(url).fragment
    params = parse_qs(fragment)
    errors = params.get("error", [])
    return errors[0] if errors else None


def _abs(url: str, base: str) -> str:
    return url if url.startswith("http") else urljoin(base, url)


class EcareAuthClient:
    """Afhandeling van OIDC login + token renewal voor Puur van Jou."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        return self

    async def __aexit__(self, *_):
        if self._session:
            await self._session.close()
            self._session = None

    def _s(self) -> aiohttp.ClientSession:
        if not self._session:
            raise RuntimeError("Gebruik als async context manager")
        return self._session

    # ------------------------------------------------------------------
    # Stap 1: Login (email + wachtwoord)
    # ------------------------------------------------------------------

    async def start_login(self, email: str, password: str) -> dict:
        """
        Start de login flow.

        Geeft één van de volgende terug:
          {"status": "ok",       "access_token": str, "cookies": dict}
          {"status": "need_sms", "sms_url": str,      "cookies": dict}

        Gooit AuthError bij verkeerde credentials of onverwachte response.
        """
        s = self._s()

        # 1. GET authorize → volgt door naar de loginpagina
        auth_url = self._authorize_url()
        async with s.get(auth_url, allow_redirects=True) as r:
            login_html = await r.text()
            login_url = str(r.url)

        if LOGIN_PATH not in login_url:
            raise AuthError(f"Verwachtte login pagina, kreeg: {login_url}")

        _LOGGER.debug("Login pagina geladen: %s", login_url)

        # 2. Login form invullen + indienen
        action, fields = _parse_form(login_html, login_url)
        fields["username"] = email
        fields["password"] = password
        fields.setdefault("button", "login")

        _LOGGER.debug("POST login form naar: %s (velden: %s)", action, list(fields.keys()))

        async with s.post(action, data=fields, allow_redirects=False) as r:
            location = r.headers.get("Location", "")
            _LOGGER.debug("Login POST antwoord: status=%s location=%s", r.status, location)

        if not location:
            # Terug op login pagina → foutmelding ophalen
            async with s.post(action, data=fields, allow_redirects=True) as r2:
                html = await r2.text()
            msg = self._extract_error(html) or "Inloggen mislukt — controleer je e-mail en wachtwoord."
            _LOGGER.warning("Login mislukt: %s", msg)
            raise AuthError(msg)

        location = _abs(location, IDP_BASE)
        _LOGGER.debug("Redirect na login naar: %s", location)

        # 3a. Direct token (TwoFactorRememberMe cookie was geldig)
        if CALLBACK_PATH in location:
            _LOGGER.debug("Direct token pad — geen SMS vereist")
            token = await self._follow_to_token(location)
            return {"status": "ok", "access_token": token, "cookies": self._export_cookies()}

        # 3b. SMS vereist
        if TWO_FACTOR_PATH in location:
            _LOGGER.debug("SMS vereist — redirect naar: %s", location)
            return {"status": "need_sms", "sms_url": location, "cookies": self._export_cookies()}

        raise AuthError(f"Onverwachte redirect na login: {location}")

    # ------------------------------------------------------------------
    # Stap 2: SMS code invoeren
    # ------------------------------------------------------------------

    async def complete_sms(self, sms_url: str, sms_code: str, cookies: dict) -> dict:
        """
        Dien de SMS code in.

        sms_url:   de /Account/TwoFactorAuthenticate URL (inclusief query params)
        sms_code:  de 6-cijferige code uit de SMS
        cookies:   de cookies die door start_login zijn teruggegeven

        Geeft {"access_token": str, "cookies": dict} terug.
        Cookies bevatten nu ook Identity.TwoFactorRememberMe zodat toekomstige
        logins geen SMS meer vereisen.
        """
        s = self._s()
        self._load_cookies(cookies)

        # 1. GET de SMS pagina voor verse CSRF token
        async with s.get(sms_url, allow_redirects=True) as r:
            sms_html = await r.text()
            sms_url_actual = str(r.url)

        action, fields = _parse_form(sms_html, sms_url_actual)

        # Vul de SMS code in (veldnaam = "Code")
        fields["Code"] = sms_code

        # 2. POST de SMS form
        async with s.post(action, data=fields, allow_redirects=False) as r:
            location = r.headers.get("Location", "")

        if not location:
            async with s.post(action, data=fields, allow_redirects=True) as r2:
                html = await r2.text()
            raise AuthError(self._extract_error(html) or "SMS code onjuist of verlopen.")

        location = _abs(location, IDP_BASE)

        # 3. Volg de redirect keten naar het token
        token = await self._follow_to_token(location)
        return {"access_token": token, "cookies": self._export_cookies()}

    # ------------------------------------------------------------------
    # Token renewal (geen SMS nodig zolang IDP sessie geldig is)
    # ------------------------------------------------------------------

    async def get_fresh_token(self, cookies: dict) -> str:
        """
        Haal een vers access token op via prompt=none (silent renewal).
        Werkt zolang de IDP sessiecookies geldig zijn — geen SMS nodig.
        Gooit AuthError als de sessie verlopen is.
        """
        self._load_cookies(cookies)
        auth_url = self._authorize_url(prompt="none")
        token = await self._follow_to_token(auth_url)
        self._export_cookies(cookies)
        return token

    # ------------------------------------------------------------------
    # API aanroepen
    # ------------------------------------------------------------------

    async def get_dagboek(self, access_token: str) -> list[dict]:
        """Haal dagboek-items op van de eCare API."""
        s = self._s()
        api_base = await self._get_api_base()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        }
        async with s.post(f"{api_base}/api/dagboek/GetDagboek", headers=headers, data=b"null") as r:
            if r.status == 401:
                raise AuthError("Access token verlopen of ongeldig")
            r.raise_for_status()
            data = await r.json()
            return data.get("Gebeurtenissen", [])

    async def _get_api_base(self) -> str:
        s = self._s()
        async with s.get(f"{PORTAL_BASE}/Home/GetConfiguration", headers={"X-Requested-With": "XMLHttpRequest"}) as r:
            if r.status == 200:
                config = await r.json()
                return config.get("ApiUrl", "https://wijkzorg-puurvanjou-api-p.ecare.nl")
        return "https://wijkzorg-puurvanjou-api-p.ecare.nl"

    # ------------------------------------------------------------------
    # Hulpfuncties
    # ------------------------------------------------------------------

    def _authorize_url(self, prompt: str = "") -> str:
        params = {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "id_token token",
            "scope": SCOPE,
            "state": secrets.token_hex(16),
            "nonce": secrets.token_hex(16),
        }
        if prompt:
            params["prompt"] = prompt
        return f"{IDP_BASE}{AUTHORIZE_PATH}?{urlencode(params)}"

    async def _follow_to_token(self, start_url: str) -> str:
        """
        Volg de redirect keten vanaf start_url totdat we REDIRECT_URI
        in de Location header zien. Haal het access_token uit het fragment.
        """
        s = self._s()
        url = start_url
        for _ in range(10):
            async with s.get(url, allow_redirects=False) as r:
                location = r.headers.get("Location", "")

            if not location:
                raise AuthError(f"Redirect keten gestopt zonder token op: {url}")

            location = _abs(location, IDP_BASE)

            if REDIRECT_URI in location:
                token = _token_from_fragment(location)
                if token:
                    return token
                error = _error_from_fragment(location)
                raise AuthError(f"IDP weigerde token: {error or 'onbekende fout'}")

            url = location

        raise AuthError("Te veel redirects in de token flow")

    def _export_cookies(self, target: dict | None = None) -> dict:
        """Exporteer IDP cookies naar een dict (voor opslag in HA)."""
        s = self._s()
        idp_host = IDP_BASE.replace("https://", "")
        result: dict[str, str] = {}
        for cookie in s.cookie_jar:
            domain = cookie.get("domain", "")
            if idp_host in domain or domain.lstrip(".") == idp_host:
                result[cookie.key] = cookie.value
        if target is not None:
            target.update(result)
        return result

    def _load_cookies(self, cookies: dict) -> None:
        """Laad opgeslagen cookies terug in de sessie."""
        s = self._s()
        idp_url = aiohttp.client.URL(IDP_BASE)
        for name, value in cookies.items():
            s.cookie_jar.update_cookies({name: value}, response_url=idp_url)

    @staticmethod
    def _extract_error(html: str) -> str | None:
        m = re.search(
            r'class="[^"]*(?:text-danger|validation-summary-errors|alert-danger)[^"]*"[^>]*>(.*?)</(?:span|div|li)',
            html, re.DOTALL,
        )
        if m:
            return re.sub(r"<[^>]+>", "", m.group(1)).strip() or None
        return None
