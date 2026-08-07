from typing import Any

from dify_plugin import ToolProvider


class DefineArchiverProvider(ToolProvider):
    """
    Define Archiver Tool Provider
    """

    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """
        No external credentials required.
        """
        return
