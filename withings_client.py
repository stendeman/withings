"""
Small Python client for the Withings API described by the bundled OpenAPI spec.

The module intentionally has no third-party dependencies. It exposes all
operations from the spec through dynamic methods such as ``measure_getmeas`` and
``measurev2_getactivity`` while keeping the hand-written parts easy to audit.

Disclaimer: This project is not affiliated with, endorsed by, or sponsored by
Withings. You are responsible for ensuring your use of this client complies
with the latest Withings developer terms and applicable laws.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import json
import os
from pathlib import Path
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
import webbrowser


class WithingsApiError(RuntimeError):
    """Raised when Withings returns an HTTP error or non-zero API status."""

    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    expires_at: int | None = None
    userid: int | str | None = None
    scope: str | None = None
    token_type: str = "Bearer"

    @classmethod
    def from_response(cls, response: Mapping[str, Any]) -> "TokenSet":
        body = response.get("body", response)
        return cls(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_in=body.get("expires_in"),
            expires_at=body.get("expires_at"),
            userid=body.get("userid"),
            scope=body.get("scope"),
            token_type=body.get("token_type", "Bearer"),
        )


class MeasureType(IntEnum):
    WEIGHT = 1
    HEIGHT = 4
    FAT_FREE_MASS = 5
    FAT_RATIO = 6
    FAT_MASS_WEIGHT = 8
    DIASTOLIC_BLOOD_PRESSURE = 9
    SYSTOLIC_BLOOD_PRESSURE = 10
    HEART_PULSE = 11
    TEMPERATURE = 12
    SPO2 = 54
    BODY_TEMPERATURE = 71
    SKIN_TEMPERATURE = 73
    MUSCLE_MASS = 76
    HYDRATION = 77
    BONE_MASS = 88
    PULSE_WAVE_VELOCITY = 91
    VO2_MAX = 123
    VASCULAR_AGE = 155
    NERVE_HEALTH_SCORE_FEET = 167
    EXTRACELLULAR_WATER = 168
    INTRACELLULAR_WATER = 169
    VISCERAL_FAT = 170
    BASAL_METABOLIC_RATE = 226
    METABOLIC_AGE = 227
    ELECTROCHEMICAL_SKIN_CONDUCTANCE = 229


ENDPOINTS: dict[str, dict[str, Any]] = {
    "oauth2_authorize": {"method": "GET", "url": "https://account.withings.com/oauth2_user/authorize2", "action": None, "required": ("response_type", "client_id", "state", "scope", "redirect_uri")},
    "oauth2_getaccesstoken": {"method": "POST", "url": "https://wbsapi.withings.net/v2/oauth2", "action": None, "required": ()},
    "oauth2_recoverauthorizationcode": {"method": "POST", "url": "https://wbsapi.withings.net/v2/oauth2", "action": "recoverauthorizationcode", "required": ("client_id", "nonce", "signature", "userid")},
    "oauth2_listusers": {"method": "POST", "url": "https://wbsapi.withings.net/v2/oauth2", "action": "listusers", "required": ("client_id", "nonce", "signature")},
    "oauth2_revoke": {"method": "POST", "url": "https://wbsapi.withings.net/v2/oauth2", "action": "revoke", "required": ("client_id", "nonce", "signature", "userid")},
    "oauth2_getdemoaccess": {"method": "POST", "url": "https://wbsapi.withings.net/v2/oauth2", "action": "getdemoaccess", "required": ("client_id", "nonce", "signature", "scope_oauth2")},
    "oauth2_createclient": {"method": "POST", "url": "https://wbsapi.withings.net/v2/oauth2", "action": "createclient", "required": ("client_id", "nonce", "signature", "name", "description", "intended_environment", "intended_integrations", "redirect_uris")},
    "measure_getmeas": {"method": "POST", "url": "https://wbsapi.withings.net/measure", "action": "getmeas", "required": ()},
    "notify_get": {"method": "POST", "url": "https://wbsapi.withings.net/notify", "action": "get", "required": ("callbackurl",)},
    "notify_list": {"method": "POST", "url": "https://wbsapi.withings.net/notify", "action": "list", "required": ()},
    "notify_revoke": {"method": "POST", "url": "https://wbsapi.withings.net/notify", "action": "revoke", "required": ("callbackurl",)},
    "notify_subscribe": {"method": "POST", "url": "https://wbsapi.withings.net/notify", "action": "subscribe", "required": ("callbackurl", "appli", "signature", "nonce", "client_id")},
    "notify_update": {"method": "POST", "url": "https://wbsapi.withings.net/notify", "action": "update", "required": ("callbackurl", "appli", "new_callbackurl", "new_appli", "comment")},
    "answersv2_get": {"method": "POST", "url": "https://wbsapi.withings.net/v2/answers", "action": "get", "required": ("signature", "client_id", "nonce", "userid", "startdate")},
    "devicev2_disablefeature": {"method": "POST", "url": "https://wbsapi.withings.net/v2/device", "action": "disablefeature", "required": ("client_id", "signature", "nonce", "feature_name", "userid", "model")},
    "devicev2_enablefeature": {"method": "POST", "url": "https://wbsapi.withings.net/v2/device", "action": "enablefeature", "required": ("client_id", "signature", "nonce", "feature_name", "userid", "model")},
    "devicev2_endpartnerprogram": {"method": "POST", "url": "https://wbsapi.withings.net/v2/device", "action": "endpartnerprogram", "required": ("client_id", "signature", "nonce", "mac_address", "status")},
    "dropshipmentv2_createorder": {"method": "POST", "url": "https://wbsapi.withings.net/v2/dropshipment", "action": "createorder", "required": ("client_id", "nonce", "signature", "order")},
    "dropshipmentv2_createuserorder": {"method": "POST", "url": "https://wbsapi.withings.net/v2/dropshipment", "action": "createuserorder", "required": ("client_id", "nonce", "signature", "mailingpref", "birthdate", "measures", "gender", "preflang", "unit_pref", "email", "timezone", "shortname", "external_id", "order")},
    "dropshipmentv2_delete": {"method": "POST", "url": "https://wbsapi.withings.net/v2/dropshipment", "action": "delete", "required": ("client_id", "signature", "nonce", "order_id")},
    "dropshipmentv2_getorderstatus": {"method": "POST", "url": "https://wbsapi.withings.net/v2/dropshipment", "action": "getorderstatus", "required": ("client_id", "signature", "nonce", "order_ids", "customer_ref_ids")},
    "dropshipmentv2_update": {"method": "POST", "url": "https://wbsapi.withings.net/v2/dropshipment", "action": "update", "required": ("client_id", "signature", "nonce", "order_id", "order")},
    "heartv2_get": {"method": "POST", "url": "https://wbsapi.withings.net/v2/heart", "action": "get", "required": ("signalid", "client_id", "signature", "nonce", "signal_token")},
    "heartv2_list": {"method": "POST", "url": "https://wbsapi.withings.net/v2/heart", "action": "list", "required": ()},
    "measurev2_confirmuser": {"method": "POST", "url": "https://wbsapi.withings.net/v2/measure", "action": "confirmuser", "required": ("grpid", "is_confirmed")},
    "measurev2_getactivity": {"method": "POST", "url": "https://wbsapi.withings.net/v2/measure", "action": "getactivity", "required": ()},
    "measurev2_getintradayactivity": {"method": "POST", "url": "https://wbsapi.withings.net/v2/measure", "action": "getintradayactivity", "required": ()},
    "measurev2_getworkouts": {"method": "POST", "url": "https://wbsapi.withings.net/v2/measure", "action": "getworkouts", "required": ()},
    "nudgev2_create": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudge", "action": "create", "required": ("signature", "client_id", "nonce", "iconids", "content", "model")},
    "nudgev2_delete": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudge", "action": "delete", "required": ("signature", "client_id", "nonce", "nudgeid")},
    "nudgev2_get": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudge", "action": "get", "required": ("signature", "client_id", "nonce", "nudgeid")},
    "nudgev2_list": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudge", "action": "list", "required": ("signature", "client_id", "nonce")},
    "nudgev2_update": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudge", "action": "update", "required": ("signature", "client_id", "nonce", "nudgeid")},
    "nudgecampaignv2_addusers": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudgecampaign", "action": "addusers", "required": ("signature", "client_id", "nonce", "nudgecampaignid", "userids")},
    "nudgecampaignv2_create": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudgecampaign", "action": "create", "required": ("signature", "client_id", "nonce", "nudgeid", "startdate", "enddate", "max_display_count")},
    "nudgecampaignv2_delete": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudgecampaign", "action": "delete", "required": ("signature", "client_id", "nonce", "nudgecampaignid")},
    "nudgecampaignv2_get": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudgecampaign", "action": "get", "required": ("signature", "client_id", "nonce", "nudgecampaignid")},
    "nudgecampaignv2_list": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudgecampaign", "action": "list", "required": ("signature", "client_id", "nonce")},
    "nudgecampaignv2_listusers": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudgecampaign", "action": "listusers", "required": ("signature", "client_id", "nonce", "nudgecampaignid")},
    "nudgecampaignv2_removeusers": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudgecampaign", "action": "removeusers", "required": ("signature", "client_id", "nonce", "nudgecampaignid", "userids")},
    "nudgecampaignv2_update": {"method": "POST", "url": "https://wbsapi.withings.net/v2/nudgecampaign", "action": "update", "required": ("signature", "client_id", "nonce", "nudgecampaignid")},
    "orderv2_getdetail": {"method": "POST", "url": "https://wbsapi.withings.net/v2/order", "action": "getdetail", "required": ("client_id", "nonce", "signature", "order_ids", "customer_ref_ids")},
    "rawdatav2_activate": {"method": "POST", "url": "https://wbsapi.withings.net/v2/rawdata", "action": "activate", "required": ("hash_deviceid", "rawdata_type")},
    "rawdatav2_deactivate": {"method": "POST", "url": "https://wbsapi.withings.net/v2/rawdata", "action": "deactivate", "required": ("hash_deviceid",)},
    "rawdatav2_get": {"method": "POST", "url": "https://wbsapi.withings.net/v2/rawdata", "action": "get", "required": ("hash_deviceid", "rawdata_type", "startdate", "enddate")},
    "signaturev2_getnonce": {"method": "POST", "url": "https://wbsapi.withings.net/v2/signature", "action": "getnonce", "required": ("client_id", "timestamp", "signature")},
    "sleepv2_get": {"method": "POST", "url": "https://wbsapi.withings.net/v2/sleep", "action": "get", "required": ("startdate", "enddate")},
    "sleepv2_getsummary": {"method": "POST", "url": "https://wbsapi.withings.net/v2/sleep", "action": "getsummary", "required": ()},
    "stethov2_get": {"method": "POST", "url": "https://wbsapi.withings.net/v2/stetho", "action": "get", "required": ("signalid",)},
    "stethov2_list": {"method": "POST", "url": "https://wbsapi.withings.net/v2/stetho", "action": "list", "required": ()},
    "surveyv2_activate": {"method": "POST", "url": "https://wbsapi.withings.net/v2/survey", "action": "activate", "required": ("signature", "client_id", "nonce", "surveyid", "userids")},
    "surveyv2_deactivate": {"method": "POST", "url": "https://wbsapi.withings.net/v2/survey", "action": "deactivate", "required": ("signature", "client_id", "nonce", "surveyid", "userids")},
    "surveyv2_get": {"method": "POST", "url": "https://wbsapi.withings.net/v2/survey", "action": "get", "required": ("signature", "client_id", "nonce", "surveyid")},
    "surveyv2_list": {"method": "POST", "url": "https://wbsapi.withings.net/v2/survey", "action": "list", "required": ("signature", "client_id", "nonce")},
    "surveyv2_listusers": {"method": "POST", "url": "https://wbsapi.withings.net/v2/survey", "action": "listusers", "required": ("signature", "client_id", "nonce", "surveyid")},
    "userv2_activate": {"method": "POST", "url": "https://wbsapi.withings.net/v2/user", "action": "activate", "required": ("client_id", "nonce", "signature", "mailingpref", "birthdate", "measures", "gender", "preflang", "unit_pref", "email", "timezone", "shortname", "external_id", "mac_addresses")},
    "userv2_addtorpm": {"method": "POST", "url": "https://wbsapi.withings.net/v2/user", "action": "addtorpm", "required": ("signature", "client_id", "nonce", "userid", "programid")},
    "userv2_get": {"method": "POST", "url": "https://wbsapi.withings.net/v2/user", "action": "get", "required": ("client_id", "nonce", "signature")},
    "userv2_getdevice": {"method": "POST", "url": "https://wbsapi.withings.net/v2/user", "action": "getdevice", "required": ()},
    "userv2_getgoals": {"method": "POST", "url": "https://wbsapi.withings.net/v2/user", "action": "getgoals", "required": ()},
    "userv2_link": {"method": "POST", "url": "https://wbsapi.withings.net/v2/user", "action": "link", "required": ("mac_addresses",)},
    "userv2_unlink": {"method": "POST", "url": "https://wbsapi.withings.net/v2/user", "action": "unlink", "required": ("mac_address",)},
}


class WithingsClient:
    def __init__(
        self,
        *,
        redirect_uri: str | None = None,
        token_store_path: str | Path | None = None,
        scopes: str | list[str] = "user.metrics",
        auto_authenticate: bool = True,
        strict_compliance: bool = False,
        app_identifier: str | None = None,
        app_contact: str | None = None,
        require_user_consent: bool = False,
        user_consent_granted: bool = True,
        min_request_interval_seconds: float = 0.0,
        max_post_body_bytes: int = 262144,
        timeout: int = 30,
    ) -> None:
        self.client_id = os.getenv("WITHINGS_CLIENT_ID")
        self.client_secret = os.getenv("WITHINGS_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("WITHINGS_REDIRECT_URI") or "http://127.0.0.1:8765/callback"
        self.scopes = scopes
        self.token_store_path = Path(
            token_store_path
            or os.getenv("WITHINGS_TOKEN_FILE")
            or (Path.home() / ".withings" / "tokens.json")
        )
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self._token_expires_at: int | None = None
        self.strict_compliance = strict_compliance
        self.app_identifier = app_identifier or os.getenv("WITHINGS_APP_IDENTIFIER")
        self.app_contact = app_contact or os.getenv("WITHINGS_APP_CONTACT")
        self.require_user_consent = require_user_consent
        self._user_consent_granted = user_consent_granted
        self.min_request_interval_seconds = max(0.0, min_request_interval_seconds)
        self.max_post_body_bytes = max(1024, int(max_post_body_bytes))
        self._last_request_ts: float = 0.0
        self.timeout = timeout

        if self.strict_compliance and (not self.app_identifier or not self.app_contact):
            raise ValueError(
                "strict_compliance=True requires app_identifier and app_contact "
                "(or WITHINGS_APP_IDENTIFIER and WITHINGS_APP_CONTACT)."
            )

        self._load_tokens()
        if auto_authenticate:
            self._ensure_authenticated()

    def set_user_consent(self, granted: bool) -> None:
        """Record whether end-user consent has been obtained in your application."""

        self._user_consent_granted = granted

    def authorization_url(
        self,
        *,
        scopes: str | list[str] = "user.metrics",
        state: str | None = None,
        mode: str | None = None,
        redirect_uri: str | None = None,
        client_id: str | None = None,
    ) -> str:
        state = state or secrets.token_urlsafe(24)
        params = {
            "response_type": "code",
            "client_id": client_id or self.client_id,
            "scope": ",".join(scopes) if isinstance(scopes, list) else scopes,
            "redirect_uri": redirect_uri or self.redirect_uri,
            "state": state,
            "mode": mode,
        }
        missing = [name for name in ("client_id", "redirect_uri") if not params.get(name)]
        if missing:
            raise ValueError(f"Missing required value(s): {', '.join(missing)}")
        return self.build_url(ENDPOINTS["oauth2_authorize"]["url"], params)

    def exchange_code(self, code: str, *, redirect_uri: str | None = None) -> TokenSet:
        self._require_client_credentials()
        response = self.oauth2_getaccesstoken(
            action="requesttoken",
            grant_type="authorization_code",
            client_id=self.client_id,
            client_secret=self.client_secret,
            code=code,
            redirect_uri=redirect_uri or self.redirect_uri,
            authenticated=False,
        )
        token_set = TokenSet.from_response(response)
        self._set_tokens(token_set)
        self._save_tokens()
        return token_set

    def refresh_access_token(self, refresh_token: str | None = None) -> TokenSet:
        self._require_client_credentials()
        response = self.oauth2_getaccesstoken(
            action="requesttoken",
            grant_type="refresh_token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=refresh_token or self.refresh_token,
            authenticated=False,
        )
        token_set = TokenSet.from_response(response)
        self._set_tokens(token_set)
        self._save_tokens()
        return token_set

    def authenticate(self, *, force: bool = False) -> TokenSet | None:
        if force:
            self.access_token = None
        self._ensure_authenticated(force_interactive=force)
        if not self.access_token:
            return None
        return TokenSet(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            expires_at=self._token_expires_at,
        )

    def get_measurements(
        self,
        *,
        meastypes: list[int | MeasureType] | str | None = None,
        startdate: int | None = None,
        enddate: int | None = None,
        lastupdate: int | None = None,
        category: int = 1,
        offset: int | None = None,
    ) -> dict[str, Any]:
        if isinstance(meastypes, list):
            meastypes = ",".join(str(int(item)) for item in meastypes)
        return self.measure_getmeas(
            meastypes=meastypes,
            startdate=startdate,
            enddate=enddate,
            lastupdate=lastupdate,
            category=category,
            offset=offset,
        )

    def get_weight_measurements(self, **kwargs: Any) -> dict[str, Any]:
        return self.get_measurements(meastypes=[MeasureType.WEIGHT], **kwargs)

    def latest_measure_value(self, measure_type: int | MeasureType, **kwargs: Any) -> float | None:
        response = self.get_measurements(meastypes=[int(measure_type)], **kwargs)
        groups = response.get("body", {}).get("measuregrps", [])
        if not groups:
            return None
        newest = max(groups, key=lambda group: group.get("date", 0))
        for measure in newest.get("measures", []):
            if measure.get("type") == int(measure_type):
                return decode_measure_value(measure)
        return None

    def __getattr__(self, name: str) -> Callable[..., dict[str, Any]]:
        if name not in ENDPOINTS:
            raise AttributeError(name)

        def operation(**params: Any) -> dict[str, Any]:
            authenticated = params.pop("authenticated", True)
            return self.call(name, authenticated=authenticated, **params)

        operation.__name__ = name
        operation.__doc__ = f"Call Withings operation {name}."
        return operation

    def call(self, operation_name: str, *, authenticated: bool = True, **params: Any) -> dict[str, Any]:
        operation = ENDPOINTS[operation_name]
        payload = dict(params)

        if "client_id" in operation["required"] and payload.get("client_id") is None:
            payload["client_id"] = self.client_id

        if operation["action"] and "action" not in payload:
            payload["action"] = operation["action"]

        missing = [name for name in operation["required"] if payload.get(name) is None]
        if missing:
            raise ValueError(f"Missing required parameter(s) for {operation_name}: {', '.join(missing)}")

        return self.request(
            operation["method"],
            operation["url"],
            data=payload,
            authenticated=authenticated,
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        data: Mapping[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        payload = clean_payload(data or {})

        if self.require_user_consent and authenticated and not self._user_consent_granted:
            raise ValueError(
                "User consent is required before authenticated API calls. "
                "Call set_user_consent(True) after your app obtains explicit consent."
            )

        if self.min_request_interval_seconds > 0:
            elapsed = time.time() - self._last_request_ts
            if elapsed < self.min_request_interval_seconds:
                time.sleep(self.min_request_interval_seconds - elapsed)

        for attempt in range(2):
            headers = {
                "Accept": "application/json",
                "User-Agent": self._build_user_agent(),
            }
            body: bytes | None = None

            if authenticated:
                self._ensure_authenticated()
                if not self.access_token:
                    raise ValueError("Unable to authenticate with Withings")
                headers["Authorization"] = f"Bearer {self.access_token}"

            if method.upper() == "GET":
                request_url = self.build_url(url, payload)
            else:
                request_url = url
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                body = urlencode(payload).encode("utf-8")
                if len(body) > self.max_post_body_bytes:
                    raise ValueError(
                        f"Request body too large ({len(body)} bytes). "
                        f"Limit is {self.max_post_body_bytes} bytes."
                    )

            request = Request(request_url, data=body, headers=headers, method=method.upper())
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                    self._last_request_ts = time.time()
            except HTTPError as exc:
                raw_error = exc.read().decode("utf-8", errors="replace")
                if authenticated and attempt == 0 and exc.code in (401, 403):
                    self._ensure_authenticated(force_interactive=True)
                    continue
                raise WithingsApiError(raw_error or str(exc), status=exc.code, body=raw_error) from exc
            except URLError as exc:
                raise WithingsApiError(str(exc)) from exc

            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {"raw": raw}

            if isinstance(parsed, dict) and parsed.get("status") not in (None, 0):
                if authenticated and attempt == 0 and parsed.get("status") in (401, 403):
                    self._ensure_authenticated(force_interactive=True)
                    continue
                raise WithingsApiError(
                    f"Withings API returned status {parsed.get('status')}",
                    status=parsed.get("status"),
                    body=parsed,
                )
            return parsed

        raise WithingsApiError("Unable to complete request after re-authentication")

    def _build_user_agent(self) -> str:
        base = "withings-client/0.1.0"
        identifier = self.app_identifier or "unspecified-app"
        contact = self.app_contact or "unspecified-contact"
        return f"{base} ({identifier}; contact={contact})"

    @staticmethod
    def build_url(url: str, params: Mapping[str, Any]) -> str:
        clean = clean_payload(params)
        if not clean:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{urlencode(clean)}"

    def _require_client_credentials(self) -> None:
        missing: list[str] = []
        if not self.client_id:
            missing.append("WITHINGS_CLIENT_ID")
        if not self.client_secret:
            missing.append("WITHINGS_CLIENT_SECRET")
        if missing:
            raise ValueError(f"Missing required environment variable(s): {', '.join(missing)}")

    def _set_tokens(self, token_set: TokenSet) -> None:
        self.access_token = token_set.access_token
        if token_set.refresh_token is not None:
            self.refresh_token = token_set.refresh_token
        if token_set.expires_at is not None:
            self._token_expires_at = int(token_set.expires_at)
        elif token_set.expires_in is not None:
            self._token_expires_at = int(time.time()) + int(token_set.expires_in)

    def _load_tokens(self) -> None:
        if not self.token_store_path.exists():
            return
        try:
            content = json.loads(self.token_store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        self.access_token = content.get("access_token")
        self.refresh_token = content.get("refresh_token")
        expires_at = content.get("expires_at")
        self._token_expires_at = int(expires_at) if expires_at is not None else None

    def _save_tokens(self) -> None:
        if not self.access_token:
            return
        self.token_store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self._token_expires_at,
        }
        self.token_store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _token_expired(self) -> bool:
        if self._token_expires_at is None:
            return False
        return time.time() >= self._token_expires_at - 30

    def _ensure_authenticated(self, *, force_interactive: bool = False) -> None:
        if self.access_token and not self._token_expired() and not force_interactive:
            return

        if self.refresh_token and not force_interactive:
            try:
                self.refresh_access_token()
                return
            except WithingsApiError:
                pass

        code = self._authorize_in_browser()
        self.exchange_code(code)

    def _authorize_in_browser(self, *, timeout_seconds: int = 180) -> str:
        self._require_client_credentials()

        redirect = urlparse(self.redirect_uri)
        host = redirect.hostname
        if redirect.scheme != "http" or host not in {"127.0.0.1", "localhost"}:
            raise ValueError(
                "Automated OAuth callback requires a localhost HTTP redirect URI, "
                "for example http://127.0.0.1:8765/callback"
            )
        port = redirect.port or 80
        callback_path = redirect.path or "/"

        state = secrets.token_urlsafe(24)
        auth_url = self.authorization_url(scopes=self.scopes, state=state)
        callback_data: dict[str, str | None] = {"code": None, "state": None, "error": None}
        callback_event = threading.Event()

        class CallbackHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != callback_path:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Not found")
                    return

                query = parse_qs(parsed.query)
                callback_data["code"] = query.get("code", [None])[0]
                callback_data["state"] = query.get("state", [None])[0]
                callback_data["error"] = query.get("error", [None])[0]

                html = (
                    "<html><body><h3>Authentication complete.</h3>"
                    "<p>This tab will close automatically.</p>"
                    "<script>"
                    "(function(){"
                    "try{window.opener=null;}catch(e){}"
                    "window.open('','_self');"
                    "window.close();"
                    "setTimeout(function(){window.close();},150);"
                    "setTimeout(function(){window.location.href='about:blank';},300);"
                    "})();"
                    "</script>"
                    "</body></html>"
                )
                encoded = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

                callback_event.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()

        with ThreadingHTTPServer((host, port), CallbackHandler) as server:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()

            webbrowser.open(auth_url, new=1, autoraise=True)

            if not callback_event.wait(timeout_seconds):
                server.shutdown()
                server_thread.join(timeout=5)
                raise TimeoutError("Timed out waiting for OAuth callback")

            server_thread.join(timeout=5)

        if callback_data["error"]:
            raise WithingsApiError(f"Authorization error: {callback_data['error']}")
        if callback_data["state"] != state:
            raise WithingsApiError("State mismatch in OAuth callback")
        if not callback_data["code"]:
            raise WithingsApiError("No authorization code found in callback")
        return str(callback_data["code"])


def clean_payload(data: Mapping[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, IntEnum):
            cleaned[key] = str(int(value))
        elif isinstance(value, bool):
            cleaned[key] = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            if any(isinstance(item, (dict, list, tuple)) for item in value):
                cleaned[key] = json.dumps(value, separators=(",", ":"))
            else:
                cleaned[key] = ",".join(str(int(item)) if isinstance(item, IntEnum) else str(item) for item in value)
        elif isinstance(value, dict):
            cleaned[key] = json.dumps(value, separators=(",", ":"))
        else:
            cleaned[key] = str(value)
    return cleaned


def decode_measure_value(measure: Mapping[str, Any]) -> float:
    """Convert Withings ``{"value": ..., "unit": ...}`` measures to real units."""

    return float(measure["value"]) * (10 ** int(measure.get("unit", 0)))


__all__ = [
    "ENDPOINTS",
    "MeasureType",
    "TokenSet",
    "WithingsApiError",
    "WithingsClient",
    "decode_measure_value",
]
