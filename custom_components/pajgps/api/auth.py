"""
Low-level authentication logic for the PajGPS API.

Responsible for:
- Obtaining a login token via the PajGPS login endpoint
- Refreshing the token when it expires
- Building the standard authorization headers used by all API calls
"""
import logging
import time

from custom_components.pajgps.requests import make_request, ApiResponseError

_LOGGER = logging.getLogger(__name__)

API_URL = "https://connect.paj-gps.de/api/v1/"


class LoginResponse:
    """Parsed response from the PajGPS login endpoint."""

    token: str | None = None
    userID: str | None = None
    routeIcon: str | None = None

    def __init__(self, json: dict) -> None:
        self.token = json["success"]["token"]
        self.userID = json["success"]["userID"]
        self.routeIcon = json["success"]["routeIcon"]

    def __str__(self) -> str:
        return f"token: {self.token}, userID: {self.userID}, routeIcon: {self.routeIcon}"


async def get_login_token(email: str, password: str) -> str | None:
    """
    Obtain a login token from the PajGPS API.

    Sends a POST to /login with the supplied credentials and returns the
    bearer token string on success, or None on failure.

    Corresponding CURL command:
    curl -X 'POST' \\
      'https://connect.paj-gps.de/api/v1/login?email=EMAIL&password=PASSWORD' \\
      -H 'accept: application/json' \\
      -H 'X-CSRF-TOKEN: ' \\
      -d ''
    """
    url = API_URL + "login"
    headers = {
        "accept": "application/json",
        "X-CSRF-TOKEN": "",
    }
    params = {
        "email": email,
        "password": password,
    }
    try:
        json_response = await make_request("POST", url, headers, params=params)
        login_response = LoginResponse(json_response)
        return login_response.token
    except ApiResponseError as e:
        _LOGGER.error("Error while getting login token: %s", e)
        return None
    except TimeoutError:
        _LOGGER.error("Timeout while getting login token")
        return None


async def refresh_token(
    current_token: str | None,
    last_token_update: float,
    token_ttl: int,
    email: str,
    password: str,
    forced: bool = False,
) -> tuple[str | None, float]:
    """
    Refresh the bearer token if it has expired or is missing.

    Returns a tuple of (new_token, updated_last_token_update).
    If the token is still valid and *forced* is False, returns the current
    values unchanged.
    """
    token_expired = (time.time() - last_token_update) > token_ttl
    needs_refresh = forced or current_token is None or token_expired

    if not needs_refresh:
        _LOGGER.debug("Token refresh skipped (still valid)")
        return current_token, last_token_update

    _LOGGER.debug("Refreshing token")
    new_token: str | None = None
    try:
        new_token = await get_login_token(email, password)
    except TimeoutError:
        _LOGGER.error("Timeout while getting login token")

    if new_token:
        _LOGGER.debug("Token refreshed successfully")
        return new_token, time.time()

    _LOGGER.error("Failed to refresh token")
    return current_token, last_token_update


def get_standard_headers(token: str) -> dict:
    """
    Build the standard HTTP headers used by all authenticated PajGPS API requests.

    :param token: Bearer token obtained from :func:`get_login_token`.
    :return: Dictionary of HTTP headers.
    """
    return {
        "accept": "application/json",
        "Authorization": f"Bearer {token}",
        "X-CSRF-TOKEN": "",
    }

