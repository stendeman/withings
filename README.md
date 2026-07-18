# Withings Python Client

Lightweight Python client for the Withings API, generated from the Withings OpenAPI specification with a small handwritten layer for usability.

The module has no third-party dependencies and includes built-in OAuth2 automation.

## Legal Disclaimer

This project is an independent community client.
It is not affiliated with, endorsed by, sponsored by, or approved by Withings.

Your use of the Withings API remains subject to the latest Withings developer terms,
privacy requirements, and any applicable laws and regulations.

## Features

- Automatic OAuth2 authorization flow in the browser
- Automatic localhost callback handling and code exchange
- Automatic token loading, refresh, and persistence
- Dynamic access to all OpenAPI operations
- Convenience helpers for measurements

## Installation

Install from GitHub:

```bash
pip install git+https://github.com/<your-org-or-username>/withings.git
```

After publishing to PyPI, install with:

```bash
pip install withings-client
```

Then import:

```python
from withings_client import MeasureType, WithingsClient
```

Set your app credentials as environment variables:

```powershell
$env:WITHINGS_CLIENT_ID="YOUR_CLIENT_ID"
$env:WITHINGS_CLIENT_SECRET="YOUR_CLIENT_SECRET"
```

Optional environment variables:

```powershell
# Default: http://127.0.0.1:8765/callback
$env:WITHINGS_REDIRECT_URI="http://localhost:8000/callback"

# Default: ~/.withings/tokens.json
$env:WITHINGS_TOKEN_FILE="C:\\path\\to\\tokens.json"

# Optional compliance identity values
$env:WITHINGS_APP_IDENTIFIER="my-company-health-app"
$env:WITHINGS_APP_CONTACT="privacy@my-company.example"
```

Create the client:

```python
from withings_client import WithingsClient

client = WithingsClient()
```

Optional strict compliance mode:

```python
client = WithingsClient(
    strict_compliance=True,
    app_identifier="my-company-health-app",
    app_contact="privacy@my-company.example",
    require_user_consent=True,
    user_consent_granted=False,
    min_request_interval_seconds=0.2,
)

# Call this only after obtaining explicit user consent in your app UX.
client.set_user_consent(True)
```

If no valid token is available, the client automatically:

1. Opens the Withings authorization page in your browser.
2. Starts a local callback server.
3. Captures the authorization code.
4. Exchanges the code for tokens.
5. Saves tokens locally for future runs.

## Example: Fetch Measurements

```python
from withings_client import MeasureType, WithingsClient

client = WithingsClient()

data = client.get_measurements(
    meastypes=[
        MeasureType.WEIGHT,
        MeasureType.FAT_RATIO,
        MeasureType.MUSCLE_MASS,
        MeasureType.BONE_MASS,
        MeasureType.VISCERAL_FAT,
    ],
    category=1,
)

latest_weight = client.latest_measure_value(MeasureType.WEIGHT)
print(latest_weight)
```

## Authentication API

Force a fresh interactive login:

```python
tokens = client.authenticate(force=True)
print(tokens.access_token)
```

Manually refresh (usually not needed, refresh is automatic):

```python
tokens = client.refresh_access_token()
print(tokens.access_token)
```

## Dynamic API Operations

All operations from the OpenAPI spec are available as dynamic methods.
The operation `action` parameter is injected automatically when defined by the endpoint.

```python
client.measure_getmeas(meastypes="1,6,76")
client.measurev2_getactivity(startdateymd="2026-07-01", enddateymd="2026-07-17")
client.userv2_getdevice()
client.notify_list(appli=1)
```

If an endpoint should be called without Bearer authentication, pass `authenticated=False`:

```python
client.oauth2_getaccesstoken(
    action="requesttoken",
    grant_type="refresh_token",
    client_id=client.client_id,
    client_secret=client.client_secret,
    refresh_token="REFRESH_TOKEN",
    authenticated=False,
)
```

## Token Storage

By default, tokens are stored at:

- Windows: `C:\\Users\\<username>\\.withings\\tokens.json`
- Generic path form: `~/.withings/tokens.json`

Override this with `WITHINGS_TOKEN_FILE`.

## Publishing and Security Notes

- Do not commit real client credentials, access tokens, or refresh tokens.
- Keep credentials in environment variables.
- Keep token files outside your repository.
- Rotate credentials if they were ever exposed.

## Compliance Checklist (16 points)

The following checklist maps common API-agreement requirements to this module.

1. Use valid developer credentials only. (Code-enforced)
2. Use approved callback URL(s) that match your dashboard settings. (Code + platform-enforced)
3. Identify your application/provider in API traffic. (Code-enforced when strict mode is enabled)
4. Keep API credentials and user tokens out of source control. (Documented)
5. Obtain explicit end-user consent before reading user data. (Code-enforced when require_user_consent=True)
6. Respect applicable privacy law and publish a privacy policy in your app. (App responsibility)
7. Avoid background spam or abusive request patterns. (Code-enforced via optional request interval)
8. Avoid oversized request payloads. (Code-enforced via max_post_body_bytes)
9. Use only the official API endpoints and OAuth flow. (Code-enforced by endpoint map)
10. Validate OAuth state and handle authorization errors. (Code-enforced)
11. Protect local token storage and rotate exposed secrets. (Documented)
12. Do not imply Withings endorsement or affiliation. (Documented in disclaimer)
13. Use data only for user-approved functionality. (App responsibility)
14. Comply with notification consent rules in your app UX. (App responsibility)
15. Follow trademark/branding and legal restrictions from Withings terms. (App/release responsibility)
16. Re-check terms regularly because requirements can change. (Operational responsibility)

## Publishing to PyPI

1. Update the version in `pyproject.toml`.
2. Build distributions:

```bash
python -m pip install --upgrade build
python -m build
```

3. Publish to TestPyPI (recommended first):

```bash
python -m pip install --upgrade twine
python -m twine upload --repository testpypi dist/*
```

4. Publish to PyPI:

```bash
python -m twine upload dist/*
```

## Notes

The Withings OpenAPI specification contains limited response schemas.
This client focuses on request validation for required parameters and returns API responses as regular dictionaries.
