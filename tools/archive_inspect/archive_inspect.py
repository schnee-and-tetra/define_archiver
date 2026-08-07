import datetime
import io
import json
import tarfile
import zipfile
from collections.abc import Generator
from typing import Any

import zstandard as zstd
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.constants import DIFY_FILE_IDENTITY
from dify_plugin.file.entities import FileType
from dify_plugin.file.file import File
from utils.archiver import UnsupportedArchiveFormatError
from utils.logger import get_plugin_logger
from utils.urls import (
    get_file_urls,
    is_local_url,
    is_url_accessible,
)


class ArchiverInspectTool(Tool):
    """Quickly scans the full file paths inside an archive without decompressing, returning a JSON array for analysis."""

    def _switch_urls(self, url, internal_url, files_url) -> str:
        if not is_url_accessible(url):
            if is_local_url(url):
                url = url.replace(files_url, internal_url)
            else:
                url = url.replace(internal_url, files_url)
        return url

    def invoke(self, tool_parameters: dict) -> Generator[ToolInvokeMessage, None, None]:
        logger = get_plugin_logger(__name__)
        logger.info("=================================")
        logger.info(" START archive_inspect invoke()")
        logger.info("=================================")
        if tool_parameters is None:
            tool_parameters = {}

        internal_url, files_url = get_file_urls()
        inspect_input_key = "archive_files"

        if inspect_input_key in tool_parameters and isinstance(
            tool_parameters[inspect_input_key], dict
        ):
            item = tool_parameters[inspect_input_key]
            if item.get("dify_model_identity") == DIFY_FILE_IDENTITY:
                tool_parameters[inspect_input_key] = File(
                    url=self._switch_urls(
                        tool_parameters[inspect_input_key]["url"],
                        internal_url,
                        files_url,
                    ),
                    mime_type=item.get("mime_type"),
                    type=FileType(item.get("type")),
                    filename=item.get("filename"),
                    extension=item.get("extension"),
                    size=item.get("size"),
                )

        elif inspect_input_key in tool_parameters and isinstance(
            tool_parameters[inspect_input_key], list
        ):
            tool_parameters[inspect_input_key] = [
                File(
                    url=self._switch_urls(file_info["url"], internal_url, files_url),
                    mime_type=file_info.get("mime_type"),
                    type=FileType(file_info.get("type")),
                    filename=file_info.get("filename"),
                    extension=file_info.get("extension"),
                    size=file_info.get("size"),
                )
                for file_info in tool_parameters[inspect_input_key]
                if isinstance(file_info, dict)
                and file_info.get("dify_model_identity") == DIFY_FILE_IDENTITY
            ]

        return self._invoke(tool_parameters)

        logger.info("=================================")
        logger.info(" END archive_inspect invoke()")
        logger.info("=================================")

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:

        # Extract and parse tool parameters from Dify payload
        files = tool_parameters.get("archive_files", [])
        results: list[dict[str, Any]] = []

        logger = get_plugin_logger(__name__)
        logger.info("=================================")
        logger.info(" START archive_inspect _invoke()")
        logger.info("=================================")
        logger.info(f"archive_files: {files}")

        for item in files:
            file_name = getattr(item, "filename", "unknown_file")
            mime_type = getattr(item, "mime_type", "unknown_mime")
            extension = getattr(item, "extension", "").lower().lstrip(".")
            blob_data = getattr(item, "blob", b"")

            # Check if blob data is empty
            if not blob_data:
                results.append(
                    {
                        "filename": file_name,
                        "mime_type": mime_type,
                        "status": "error",
                        "error": "Empty file blob data",
                        "contents": [],
                    }
                )
                continue
            try:
                # Automatically detect format from file extension
                contents = []
                if extension == "zip":
                    with zipfile.ZipFile(io.BytesIO(blob_data)) as zf:
                        for info in zf.infolist():
                            p = info.filename
                            content_type = "folder" if p.endswith("/") else "file"
                            dt = info.date_time
                            dt_str = datetime.datetime(
                                *dt, tzinfo=datetime.timezone.utc
                            ).strftime("%Y-%m-%d %H:%M:%S")

                            contents.append(
                                {
                                    "path": p,
                                    "type": content_type,
                                    "size_bytes": info.file_size,
                                    "last_modified": dt_str,
                                }
                            )

                elif extension in ("tar", "tgz", "tar.gz") or (
                    extension == "gz" and file_name.endswith(".tar.gz")
                ):
                    with tarfile.open(fileobj=io.BytesIO(blob_data), mode="r:*") as tf:
                        for member in tf.getmembers():
                            p = member.name
                            content_type = "folder" if member.isdir() else "file"
                            dt_str = datetime.datetime.fromtimestamp(
                                member.mtime, tz=datetime.timezone.utc
                            ).strftime("%Y-%m-%d %H:%M:%S")
                            contents.append(
                                {
                                    "path": p,
                                    "type": content_type,
                                    "size_bytes": member.size,
                                    "last_modified": dt_str,
                                }
                            )

                # Case: Single zstd compressed file (.zst)
                elif extension in (
                    "zstandard",
                    "zstd",
                    "zst",
                ) and not file_name.endswith(".tar.zst"):
                    # Single .zst doesn't have an internal file list.
                    # Just strip the .zst extension to represent the decompressed single file name.
                    original_name = file_name
                    for ext in (".zstandard", ".zstd", ".zst"):
                        if original_name.lower().endswith(ext):
                            original_name = original_name[: -len(ext)]
                            break

                    try:
                        dctx = zstd.ZstdDecompressor()
                        frame_params = dctx.get_frame_parameters(blob_data)
                        uncompressed_size = (
                            frame_params.uncompressed_size
                            if frame_params.uncompressed_size > 0
                            else getattr(item, "size", 0)
                        )
                    except zstd.ZstdError:
                        uncompressed_size = getattr(item, "size", 0)

                    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    contents.append(
                        {
                            "path": original_name,
                            "type": "file",
                            "size_bytes": uncompressed_size,
                            "last_modified": now_utc,
                        }
                    )

                # Case: Tar archive compressed with zstd (.tar.zst)
                elif extension == "tar.zst" or file_name.endswith(".tar.zst"):
                    dctx = zstd.ZstdDecompressor()
                    # Use a single with statement with parentheses to satisfy Ruff multiple-with-statements.
                    # closefd=False prevents tarfile from closing the raw_buffer prematurely.
                    with (
                        io.BytesIO(blob_data) as raw_buffer,
                        dctx.stream_reader(raw_buffer, closefd=False) as zstd_reader,
                        tarfile.open(fileobj=zstd_reader, mode="r|") as tf,
                    ):
                        for member in tf:
                            p = member.name
                            content_type = "folder" if member.isdir() else "file"
                            dt_str = datetime.datetime.fromtimestamp(
                                member.mtime, tz=datetime.timezone.utc
                            ).strftime("%Y-%m-%d %H:%M:%S")
                            contents.append(
                                {
                                    "path": p,
                                    "type": content_type,
                                    "size_bytes": member.size,
                                    "last_modified": dt_str,
                                }
                            )

                else:
                    raise UnsupportedArchiveFormatError(extension)

                # Append success result to the list
                results.append(
                    {
                        "filename": file_name,
                        "mime_type": mime_type,
                        "contents": contents,
                    }
                )

            except (
                zipfile.BadZipFile,
                tarfile.TarError,
                zstd.ZstdError,
                OSError,
            ) as e:
                # Append error result to the list and continue loop without crashing
                results.append(
                    {
                        "filename": file_name,
                        "mime_type": mime_type,
                        "status": "error",
                        "error": str(e),
                        "contents": [],
                    }
                )

        # Output the collected list[dict] data as a single JSON string at the end
        yield self.create_json_message(results)
        yield self.create_text_message(json.dumps(results, ensure_ascii=False))

        logger.info("=================================")
        logger.info(" END archive_inspect invoke()")
        logger.info("=================================")
