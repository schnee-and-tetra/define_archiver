import hashlib
import json
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from utils.archiver import ArchiveUtility
from utils.kvstore import StorageLockTimeoutError
from utils.logger import get_plugin_logger


class FileInconsistencyError(Exception):
    """An exception raised when there is an inconsistency in the file's data structure or content."""


class IteratorCollectTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:

        # Extract and parse tool parameters from Dify payload
        collect_group_id = tool_parameters.get("collect_group_id", "").replace(
            "\x1f", "_"
        )
        iterator_index = tool_parameters.get("iterator_index")
        content = tool_parameters["content"]
        workflow_run_id = tool_parameters.get("workflow_run_id")

        if not collect_group_id:
            raise ValueError("collect_group_id is required")
        if iterator_index is None:
            raise ValueError("iterator_index is required")
        if not workflow_run_id:
            raise ValueError("workflow_run_id is required")

        iterator_index = int(iterator_index)

        logger = get_plugin_logger(__name__ + f":{workflow_run_id}:{collect_group_id}")
        logger.info("=================================")
        logger.info(" START iterator_collect _invoke()")
        logger.info("=================================")
        # Set variables for achive file
        utility = ArchiveUtility()
        file_number = iterator_index + 1
        filename = f"define_archiver_chunk.{file_number}"

        # Initialize KV store session parameters based on Dify environment user/session context
        storage = self.session.storage
        self._key_chunks = f"define_archiver_chunks:{workflow_run_id}:{collect_group_id}:{filename}:{file_number}"

        def _get_chunkdata():
            return storage.get(self._key_chunks)

        def _set_chunkdata(value):
            storage.set(self._key_chunks, value)

        try:
            _get_chunkdata()
        except Exception:  # noqa: BLE001 (Dify storage throws a generic Exception if key does not exist)
            logger.info("collect_group_id: {collect_group_id}")
        else:
            logger.error(
                "Duplicate Collect Group ID detected. Each Collect Group ID must be unique within a workflow run."
            )
            raise ValueError(
                "Duplicate Collect Group ID detected. Each Collect Group ID must be unique within a workflow run."
            )

        try:
            # Generate a unique hash key based on workflow, collect group and content bytes
            # to isolate identical chunks across different collect groups
            logger.info(f"iterator progress: index={iterator_index}")
            content_bytes = content.encode("utf-8")
            content_size = len(content_bytes)
            hash_source = (
                f"{workflow_run_id}:{collect_group_id}:{filename}:{content_size}".encode()
                + content_bytes
            )
            hash_value = f"iterator_collect_data:{hashlib.blake2b(hash_source, digest_size=32).hexdigest()}"

            # Temporarily compress single text chunk into zstd format to minimize KV store memory size
            logger.info(f"compress_single start: size={content_size}, format=zst")
            blob, _ = utility.compress_single(
                content=content_bytes,
                archive_path="",
                archive_format="tar.zst",
                compression="normal",
            )

            # Store compressed binary object chunk in KVS
            logger.info(f"bynary append: hash_value={hash_value}, size={len(blob)}")
            _set_chunkdata(blob)

            # Return the result files and result status.
            result = {
                "status": "collected",
                "file": filename,
            }
            yield self.create_text_message(json.dumps(result))
            yield self.create_json_message(result)

        except StorageLockTimeoutError:
            # Log critical lock failures and re-throw exception to gracefully notify parent node
            logger.error(
                "Could not collect data: The lock is currently held by another process."
            )
            raise

        except Exception:
            # Catch, log with complete stack trace traceback, and re-throw any generic runtime errors
            logger.exception("An unexpected error occurred while data collecting.")
            raise

        logger.info("=================================")
        logger.info(" END iterator_collect invoke()")
        logger.info("=================================")
