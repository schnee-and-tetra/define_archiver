import os
from urllib.parse import urlparse

import httpx


class DifyEnvironmentConfigError(ValueError):
    """Exception raised for missing or misconfigured Dify environment variables.

    Attributes:
        message (str): Explanatory message for the error.
    """

    def __init__(self) -> None:
        self.message = (
            "Dify environment variable configuration error:\n"
            "Both 'INTERNAL_FILES_URL' and 'FILES_URL' must be specified.\n"
            "Please check your Dify .env file configuration."
        )
        super().__init__(self.message)


def get_file_urls() -> tuple[str, str]:
    """Retrieve and validate Dify file storage URLs from environment variables.

    Returns:
        tuple[str, str]: A tuple containing (INTERNAL_FILES_URL, FILES_URL).

    Raises:
        DifyEnvironmentConfigError: If either environment variable is missing.
    """
    internal_url = os.getenv("INTERNAL_FILES_URL")
    files_url = os.getenv("FILES_URL")
    if not internal_url or not files_url:
        raise DifyEnvironmentConfigError()

    return internal_url, files_url


def is_url_accessible(url: str) -> bool:
    """Check if a URL is accessible (returns 200 OK) using httpx"""
    try:
        response = httpx.head(url, timeout=0.5, follow_redirects=True)
        return response.status_code in [200, 101] or (300 <= response.status_code < 400)
    except (httpx.HTTPError, httpx.NetworkError):
        return False


def is_local_url(url: str) -> bool:
    """Determine whether the given URL points to a local environment.

    Args:
        url (str): The URL string to parse and check.

    Returns:
        bool: True if the hostname matches localhost, loopback addresses,
            or Docker internal hosts; False otherwise.
    """
    parsed_raw = urlparse(url)
    hostname = parsed_raw.hostname

    return bool(
        hostname == "localhost"
        or (hostname and hostname.startswith("127."))
        or (hostname and "::1" in hostname)
        or hostname == "host.docker.internal"
    )
