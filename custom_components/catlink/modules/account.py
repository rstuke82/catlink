"""Account module for CatLink."""

from asyncio import TimeoutError
import base64
import datetime
import hashlib
from json import JSONDecodeError
import time
from urllib.parse import urlsplit

from aiohttp import ClientConnectorError, ClientError, ClientResponseError
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

from homeassistant.const import CONF_DEVICES, CONF_PASSWORD, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import UpdateFailed

from ..const import (
    _LOGGER,
    CONF_API_BASE,
    CONF_LANGUAGE,
    CONF_PHONE,
    CONF_PHONE_IAC,
    CONF_SCAN_INTERVAL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_API_BASE,
    DOMAIN,
    RSA_PUBLIC_KEY,
    SCAN_INTERVAL,
    SIGN_KEY,
)
from ..helpers import Helper


class Account:
    """Account class for CatLink integration."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the account."""
        self._config = dict(config)
        self.hass = hass
        self.http = aiohttp_client.async_create_clientsession(hass, auto_cleanup=False)

    def get_config(self, key, default=None) -> str:
        """Return the config of the account."""
        val = self._config.get(key)
        if val is not None:
            return val
        domain_data = self.hass.data.get(DOMAIN) or {}
        global_config = domain_data.get("config") or {}
        return global_config.get(key, default)

    @property
    def phone(self) -> str:
        """Return the phone of the account."""
        return self._config.get(CONF_PHONE)

    @property
    def password(self) -> str:
        """Return the password of the account."""
        pwd = self._config.get(CONF_PASSWORD)
        if len(pwd) <= 16:
            pwd = self.encrypt_password(pwd)
        return pwd

    @property
    def uid(self):
        """Return the unique id of the account."""
        return f"{self._config.get(CONF_PHONE_IAC)}-{self.phone}"

    @property
    def token(self) -> str:
        """Return the token of the account."""
        return self._config.get(CONF_TOKEN) or ""

    @property
    def update_interval(self) -> datetime.timedelta:
        """Return the update interval of the account. Default is 1 minute."""
        interval = (
            self.get_config(CONF_UPDATE_INTERVAL)
            or self.get_config(CONF_SCAN_INTERVAL)
            or SCAN_INTERVAL
        )
        return Helper.calculate_update_interval(interval)

    def api_url(self, api="") -> str:
        """Return the full url of the api."""
        try:
            path = urlsplit(api)
            base = self.get_config(CONF_API_BASE) or DEFAULT_API_BASE
            origin = urlsplit(base)
        except ValueError:
            raise HomeAssistantError("Invalid CatLink API URL") from None
        if path.scheme or path.netloc or api.startswith("//") or "\\" in api:
            raise HomeAssistantError("CatLink requires a relative API path")
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username is not None
            or origin.query
            or origin.fragment
        ):
            raise HomeAssistantError("CatLink requires an HTTPS API base URL")
        return f"{base.rstrip('/')}/{api.lstrip('/')}"

    async def request(
        self, api, pms=None, method="GET", *, _retried=False, **kwargs
    ) -> dict:
        """Request the API without modifying caller-provided parameters."""
        method = method.upper()
        url = self.api_url(api)
        kws = {
            "timeout": 60,
            "headers": {
                "language": self.get_config(CONF_LANGUAGE, "en_US"),
                "User-Agent": "CATLINK/4.1.5 (iPhone; iOS 26.2.1; Scale/3.00)",
                "app_version": "4.1.5",
                "system_version": "26.2.1",
                "token": self.token,
            },
        }
        kws.update(kwargs)
        kws["allow_redirects"] = False
        params = dict(pms or {})
        params["noncestr"] = int(time.time() * 1000)
        if self.token:
            params[CONF_TOKEN] = self.token
        params["sign"] = self.params_sign(params)
        if method in ("GET", "POST_GET"):
            kws["params"] = params
        else:
            kws["data"] = params
        endpoint = urlsplit(url).path
        wire_method = "POST" if method == "POST_GET" else method
        try:
            req = await self.http.request(wire_method, url, **kws)
            if 300 <= req.status < 400 or 500 <= req.status < 600:
                req.release()
                raise UpdateFailed(f"{wire_method} {endpoint}: HTTP {req.status}")
            result = await req.json()
        except (ClientConnectorError, TimeoutError) as exc:  # noqa: UP041
            _LOGGER.error(
                "Request api failed: %s %s (%s)", wire_method, endpoint, type(exc).__name__
            )
            return {}
        except ClientResponseError as exc:
            # aiohttp's exception text includes the full URL and query parameters.
            raise UpdateFailed(
                f"{wire_method} {endpoint}: HTTP {exc.status} ({type(exc).__name__})"
            ) from None
        except (ClientError, JSONDecodeError, UnicodeDecodeError) as exc:
            raise UpdateFailed(f"{wire_method} {endpoint}: {type(exc).__name__}") from None

        if result is None:
            result = {}
        if not isinstance(result, dict):
            raise UpdateFailed(f"{wire_method} {endpoint}: expected a JSON object")
        return_code = result.get("returnCode")
        _LOGGER.debug(
            "API response %s %s (return code: %s)",
            wire_method,
            endpoint,
            return_code if type(return_code) is int else None,
        )

        # Handle token expiration (1002: Illegal token)
        if return_code == 1002 and not _retried and api != "login/password":
            _LOGGER.info("Token expired (1002), attempting re-login")
            if await self.async_login():
                return await self.request(api, pms, method, _retried=True, **kwargs)

        return result

    async def async_login(self) -> bool:
        """Login the account."""
        pms = {
            "platform": "ANDROID",
            "internationalCode": self._config.get(CONF_PHONE_IAC),
            "mobile": str(self.phone),
            "password": self.password,
        }
        self._config.update(
            {
                CONF_TOKEN: None,
            }
        )
        rsp = await self.request("login/password", pms, "POST")
        tok = rsp.get("data", {}).get("token")
        if not tok:
            _LOGGER.error("CatLink login failed")
            return False
        self._config.update(
            {
                CONF_TOKEN: tok,
            }
        )
        return True

    async def async_check_auth(self) -> None:
        """Load and remove the legacy disk cache, or log in if needed."""
        store = Store(self.hass, 1, f"{DOMAIN}/auth-{self.uid}.json")
        legacy = await store.async_load()
        if legacy is not None:
            if not self.token and legacy.get(CONF_TOKEN):
                self._config[CONF_TOKEN] = legacy[CONF_TOKEN]
            await store.async_remove()
        if not self.token:
            await self.async_login()

    async def get_devices(self) -> list:
        """Get the devices of the account."""
        if not self.token:
            if not await self.async_login():
                return []
        api = "token/device/union/list/sorted"
        rsp = await self.request(api, {"type": "NONE"})
        eno = rsp.get("returnCode", 0)
        if eno == 1002:  # Illegal token
            if await self.async_login():
                rsp = await self.request(api, {"type": "NONE"})
        dls = rsp.get("data", {}).get(CONF_DEVICES) or []
        if not dls:
            return_code = rsp.get("returnCode")
            _LOGGER.warning(
                "CatLink device list returned no devices (return code: %s)",
                return_code if type(return_code) is int else None,
            )
        return dls

    async def get_cats(self, timezone_id: str | None = None) -> list:
        """Get the cats of the account."""
        if not self.token:
            if not await self.async_login():
                return []
        api = "token/pet/health/v3/cats"
        params: dict[str, str] = {}
        if timezone_id:
            params["timezoneId"] = timezone_id
        rsp = await self.request(api, params)
        eno = rsp.get("returnCode", 0)
        if eno == 1002:  # Illegal token
            if await self.async_login():
                rsp = await self.request(api, params)
        cats = rsp.get("data", {}).get("cats") or []
        if not cats:
            return_code = rsp.get("returnCode")
            _LOGGER.warning(
                "CatLink cat list returned no cats (return code: %s)",
                return_code if type(return_code) is int else None,
            )
        return cats

    async def get_cat_summary_simple(
        self,
        pet_id: str,
        date: str,
        timezone_id: str | None,
        sport: int = 1,
    ) -> dict:
        """Get a cat summary for a given date."""
        if not self.token:
            if not await self.async_login():
                return {}
        api = "token/pet/health/v3/summarySimple"
        params = {
            "petId": pet_id,
            "date": date,
            "sport": sport,
        }
        if timezone_id:
            params["timezoneId"] = timezone_id
        rsp = await self.request(api, params)
        eno = rsp.get("returnCode", 0)
        if eno == 1002:  # Illegal token
            if await self.async_login():
                rsp = await self.request(api, params)
        return rsp.get("data") or {}

    @staticmethod
    def params_sign(pms: dict) -> str:
        """Sign the params."""
        lst = list(pms.items())
        lst.sort()
        pms = [f"{k}={v}" for k, v in lst]
        pms.append(f"key={SIGN_KEY}")
        pms = "&".join(pms)
        return hashlib.md5(pms.encode()).hexdigest().upper()

    @staticmethod
    def encrypt_password(pwd) -> str:
        """Encrypt the password."""
        pwd = f"{pwd}"
        md5 = hashlib.md5(pwd.encode()).hexdigest().lower()
        sha = hashlib.sha1(md5.encode()).hexdigest().upper()
        pub = serialization.load_der_public_key(
            base64.b64decode(RSA_PUBLIC_KEY), default_backend()
        )
        pad = padding.PKCS1v15()
        return base64.b64encode(pub.encrypt(sha.encode(), pad)).decode()
