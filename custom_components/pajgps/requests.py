"""
Low-level HTTP request library for PajGPS API communication.
This module handles all HTTP requests with automatic retry logic and proper error handling.
"""
import asyncio
import logging
import aiohttp


_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://connect.paj-gps.de"
REQUEST_TIMEOUT = 5  # seconds, multiplied by attempt number for each retry
REQUEST_ATTEMPTS = 3  # maximum number of retry attempts


class ApiResponseError(Exception):
    """Exception raised when API returns an error response."""
    def __init__(self, error_json: dict):
        self.error_json = error_json
        super().__init__(f"API Error: {error_json}")


async def check_pajgps_availability(timeout: int = 15) -> bool:
    """
    Check if the PajGPS API is reachable by sending a HEAD request.

    Args:
        timeout: Timeout in seconds for the HEAD request

    Returns:
        True if API is reachable (status 200), False otherwise
    """
    try:
        timeout_config = aiohttp.ClientTimeout(total=timeout)
        session = aiohttp.ClientSession(timeout=timeout_config)

        try:
            async with session.head(API_BASE_URL) as response:
                if response.status != 200:
                    _LOGGER.warning("API URL is not reachable (status %s)", response.status)
                    return False
                return True
        finally:
            await session.close()

    except (asyncio.TimeoutError, TimeoutError):
        _LOGGER.warning("Timeout while checking API URL")
        return False
    except Exception as e:
        _LOGGER.error("Error while checking API availability: %s", e)
        return False


async def make_request(
    method: str,
    url: str,
    headers: dict,
    payload: dict = None,
    params: dict = None,
    timeout: int = 5,
    max_attempts: int = 3
):
    """
    Make an HTTP request with automatic retry on timeout.

    Args:
        method: HTTP method (GET, POST, PUT, etc.)
        url: Target URL for the request
        headers: HTTP headers dictionary
        payload: JSON payload for POST/PUT requests (optional)
        params: URL query parameters (optional)
        timeout: Base timeout in seconds (multiplied by attempt number for each retry)
        max_attempts: Maximum number of retry attempts

    Returns:
        Parsed JSON response

    Raises:
        asyncio.TimeoutError: If all retry attempts timeout
        ValueError: If response has unexpected content type
        Exception: For other HTTP or network errors
    """
    method = method.upper()
    last_error = None

    for attempt in range(max_attempts):
        try:
            # Create session with timeout that increases with each attempt
            timeout_config = aiohttp.ClientTimeout(total=timeout * (attempt + 1))
            session = aiohttp.ClientSession(timeout=timeout_config)

            try:
                # Make the request based on method
                if method == "GET":
                    response = await session.get(url, headers=headers, params=params)
                elif method == "POST":
                    response = await session.post(url, headers=headers, json=payload, params=params)
                elif method == "PUT":
                    response = await session.put(url, headers=headers, json=payload, params=params)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                # Process the response
                result = await _process_response(response, url)
                await session.close()
                return result

            finally:
                await session.close()

        except (asyncio.TimeoutError, TimeoutError) as e:
            last_error = e
            if attempt < max_attempts - 1:
                # Retry on timeout
                continue
            else:
                # All attempts exhausted
                _LOGGER.warning(
                    "Timeout on %s request to %s after %s attempts",
                    method, url, max_attempts
                )
                raise

        except Exception as e:
            # For non-timeout errors, don't retry
            raise

    # This should never be reached, but just in case
    if last_error:
        raise last_error
    return None


async def _process_response(response, url: str):
    """
    Process HTTP response and extract JSON data.

    Args:
        response: aiohttp response object
        url: Request URL (for logging)

    Returns:
        Parsed JSON response

    Raises:
        ValueError: If response has unexpected content type
        Exception: For API errors or invalid responses
    """
    content_type = response.headers.get('Content-Type', '')

    # Handle successful response
    if response.status == 200:
        if 'application/json' in content_type:
            return await response.json()
        else:
            _LOGGER.warning(
                "Unexpected content type in successful response: %s (status %s) from %s",
                content_type, response.status, url
            )
            text = await response.text()
            raise ValueError(f"Expected JSON but got {content_type}: {text[:200]}")

    # Handle error responses
    if 'application/json' in content_type:
        try:
            error_json = await response.json()
            if error_json.get("error"):
                # Raise specific API error
                raise ApiResponseError(error_json)
        except ApiResponseError:
            # Re-raise ApiResponseError as-is
            raise
        except Exception as e:
            _LOGGER.error(
                "Failed to parse error response as JSON from %s: %s (status %s, content-type: %s)",
                url, e, response.status, content_type
            )
            raise
    else:
        # Non-JSON error response (e.g., HTML error page)
        text = await response.text()
        _LOGGER.warning(
            "Received non-JSON error response from %s: status %s, content-type: %s, body preview: %s",
            url, response.status, content_type, text[:200]
        )
        raise ValueError(
            f"HTTP {response.status} with {content_type} "
            f"(expected application/json) from {url}"
        )

