import base64
import binascii
import io
import json
import os
from collections.abc import Generator
from typing import Any

import zstandard as zstd
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.constants import DIFY_FILE_IDENTITY
from dify_plugin.file.file import FileType
from utils.archiver import ArchiveFile, ArchiveUtility, FileInconsistencyError
from utils.kvstore import StorageLockTimeoutError, storage_lock
from utils.logger import get_plugin_logger
from utils.urls import get_file_urls


def get_image_bytes_and_ext(data: bytes) -> tuple[bytes, str]:
    """
    Extracts the image binary and file extension from a Base64 byte array with minimal overhead.
    If the input is merely text data, it exits immediately (returning `None`) for maximum speed.
    """
    IMAGE_SIGNATURES = {
        "ivborw": "png",  # PNG
        "/9j/": "jpg",  # JPEG
        "r0lg": "gif",  # GIF
        "qk0": "bmp",  # BMP
        "uklg": "webp",  # WebP (RIFF)
    }

    if not isinstance(data, (bytes, bytearray)):
        return b"", ""

    try:
        b64_str = data.decode("ascii", errors="ignore")

        if b64_str.startswith("data:image"):
            comma_index = b64_str.find(",")
            if comma_index != -1:
                b64_str = b64_str[comma_index + 1 :]

        b64_str = "".join(b64_str.split())
        p6 = b64_str[:6].lower()
        ext = (
            IMAGE_SIGNATURES.get(p6)
            or IMAGE_SIGNATURES.get(p6[:4])
            or IMAGE_SIGNATURES.get(p6[:3], "")
        )
        if not ext:
            return b"", ""

        missing_padding = len(b64_str) % 4
        if missing_padding:
            b64_str += "=" * (4 - missing_padding)

        image_bytes = base64.b64decode(b64_str, validate=False)
        return image_bytes, ext

    except binascii.Error:
        return b"", ""


class IteratorFinalizeTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:

        # Extract and parse tool parameters from Dify payload
        collect_group_id = tool_parameters.get("collect_group_id", "").replace(
            "\x1f", "_"
        )
        folder = tool_parameters.get("content_folder", "").replace("\x1f", "_")
        prefix = tool_parameters.get("content_prefix", "").replace("\x1f", "_")
        zero_padding = tool_parameters.get("index_padding_width")
        extension = tool_parameters.get("content_extension", "")
        decode_base64 = (
            str(tool_parameters.get("decode_base64", "false")).lower() == "true"
        )
        archive_format = tool_parameters.get("format")
        compression = tool_parameters.get("compression")
        include_manifest = (
            str(tool_parameters.get("include_manifest", "false")).lower() == "true"
        )
        workflow_run_id = tool_parameters.get("workflow_run_id")

        if not collect_group_id:
            raise ValueError("collect_group_id is required")
        if zero_padding is None:
            raise ValueError("zero_padding is required")
        if not extension:
            raise ValueError("extension is required")
        if not workflow_run_id:
            raise ValueError("workflow_run_id is required")

        logger = get_plugin_logger(__name__ + f":{workflow_run_id}:{collect_group_id}")
        logger.info("=================================")
        logger.info(" START iterator_finalize_invoke()")
        logger.info("=================================")

        # Initialize KV store session parameters based on Dify environment user/session context
        storage = self.session.storage
        self._key_chunks = f"define_archiver_chunks:{workflow_run_id}:{collect_group_id}:define_archiver_chunk"
        self._key_lock = f"define_archiver_lock:{workflow_run_id}"

        utility = ArchiveUtility()
        # Acquire the distributed storage lock with a 180s TTL and 30s wait timeout to perform compilation safely
        try:
            with storage_lock(storage, self._key_lock, lock_ttl=180.0, timeout=30.0):
                # Fetch all raw file binaries and reconstruct file records
                filenumber = 1
                folders = [p.strip() for p in folder.split(",")]
                files: list[ArchiveFile] = []
                while True:
                    blob = b""
                    try:
                        blob = storage.get(
                            f"{self._key_chunks}.{filenumber}:{filenumber}"
                        )
                    except Exception:  # noqa: BLE001 (Dify storage throws a generic Exception if key does not exist)
                        break

                    entry_filename = (
                        f"{prefix}{filenumber:0{zero_padding}d}.{extension}"
                    )
                    logger.info(
                        f"storage.get - collect_group_id={collect_group_id}, "
                        f"folder={folder}, filename={entry_filename}, "
                        f"len(blob)={len(blob) if blob is not None else 'None'}"
                    )

                    # Stream decompress zstd data back to raw original bytes
                    logger.info("Before ZstdDecompressor decompressing")
                    decompressor = zstd.ZstdDecompressor()
                    buffer_in = io.BytesIO(blob)
                    buffer_out = io.BytesIO()
                    with decompressor.stream_reader(buffer_in) as reader:
                        buffer_out.write(reader.read())
                    decompressed_bytes = buffer_out.getvalue()

                    # Decodes Base64 text to restore images
                    if decode_base64:
                        logger.info("Before decode_base64")
                        logger.info(
                            f"{entry_filename} binary: {decompressed_bytes[:10]}"
                        )
                        confirmed_bytes, detected_ext = get_image_bytes_and_ext(
                            decompressed_bytes
                        )
                        logger.info(f"get_image_bytes_and_ext {detected_ext}")
                        if detected_ext:
                            base_name, _ = os.path.splitext(entry_filename)
                            entry_filename = f"{base_name}.{detected_ext}"
                        else:
                            confirmed_bytes = decompressed_bytes
                    else:
                        confirmed_bytes = decompressed_bytes

                    # Regroup files and directory structures mapped by their archive tags
                    logger.info("Before File object creating")
                    files.append(
                        ArchiveFile(
                            filename=entry_filename,
                            blob=confirmed_bytes,
                            mime_type="application/octet-stream",
                        )
                    )

                    filenumber += 1

                # Verify whether the specified number of folders and files matches.
                if len(folders) == 1:
                    folders = [folders[0]] * len(files)
                    logger.info(
                        "Since only one folder was specified, I created folders corresponding to the number of files."
                    )
                if len(folders) != len(files):
                    raise FileInconsistencyError(
                        "The specified number of folders and files does not match."
                    )
                if 0 == len(files):
                    raise FileInconsistencyError(
                        "No files were collected. Please verify the collect_group_id and ensure that Iterator Collect completed successfully."
                    )

                # Compress each grouped file list into the targeted archive format (ZIP/TAR) and yield chunk messages
                logger.info("Before blob_messages creating")
                blob, mime_type = utility.compress_multiple(
                    target_files=files,
                    archive_paths=folders,
                    archive_format=archive_format,
                    compression=compression,
                    include_manifest=include_manifest,
                    workflow_run_id=workflow_run_id,
                )

                archive_filename = f"{collect_group_id}.{archive_format}"
                upload_response = self.session.file.upload(
                    filename=archive_filename,
                    content=blob,
                    mimetype=mime_type,
                )

                # Convert to URL format for end users
                internal_url, files_url = get_file_urls()
                correct_url = upload_response.preview_url.replace(
                    internal_url, files_url
                )

                # Creating a dictionary-format file
                file_id = upload_response.id
                archive = {
                    "dify_model_identity": DIFY_FILE_IDENTITY,
                    "transfer_method": "local_file",
                    "transferMethod": "local_file",
                    "tool_file_id": file_id,
                    "toolFileId": file_id,
                    "upload_file_id": file_id,
                    "uploadFileId": file_id,
                    "id": file_id,
                    "url": correct_url,
                    "remote_url": correct_url,
                    "mime_type": mime_type,
                    "filename": archive_filename,
                    "name": archive_filename,
                    "extension": archive_format,
                    "size": upload_response.size,
                    "type": FileType.DOCUMENT,
                }

                logger.info("Before blob yield")

                # Return the result files and result status.
                result = {
                    "status": "completed",
                    "archives": archive,
                }
                yield self.create_variable_message(
                    "archives",
                    [archive],
                )
                yield self.create_text_message(json.dumps(result))
                yield self.create_json_message(result)

                for index in range(1, len(files) + 1):
                    key = f"{self._key_chunks}.{index}:{index}"
                    try:
                        storage.delete(key)
                    except Exception as e:  # noqa: BLE001 (Dify storage throws a generic Exception if key does not exist)
                        logger.error(
                            f"Could not delete file data. key: {key}, error: " + str(e)
                        )

        except StorageLockTimeoutError:
            logger.error(
                "Could not update data: The lock is currently held by another process."
            )
            raise

        except Exception:
            logger.exception("Archive finalization failed.")
            raise

        logger.info("=================================")
        logger.info(" END iterator_finalize invoke()")
        logger.info("=================================")
