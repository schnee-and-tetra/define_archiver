import io
import json
import re
import tarfile
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime

import zstandard as zstd
from dify_plugin.file.file import File


@dataclass
class ArchiveFile:
    filename: str
    blob: bytes
    mime_type: str = "application/octet-stream"


class FileInconsistencyError(Exception):
    """An exception raised when there is an inconsistency in the file's data structure or content."""


class UnsupportedArchiveFormatError(ValueError):
    """Exception raised when the requested archive format is not supported by ArchiveUtility."""

    def __init__(self, format_name: str):
        self.format_name = format_name
        self.message = f"The archive format '{format_name}' is not supported."
        super().__init__(self.message)


class ArchiveUtility:
    """A utility class for archiving and compressing files and directories."""

    def __init__(self):
        """Initialize the instance with the current Unix timestamp."""
        self._plugin_version = "0.0.1"
        self._manifest_version = "1.0"
        self._manifest_creator = "Dify (Define Archiver Plugin)"
        self._current_time = int(time.time())

    def compress_single(
        self,
        content: bytes,
        archive_path: str,
        archive_format: str,
        compression: str,
    ) -> tuple[bytes, str]:
        """Compress a single specified file and create an archive.

        Args:
            content: The content bytes data of the file to be compressed.
            archive_path: The path where the archive file will be saved or updated.
            archive_format: The format of the archive (e.g., 'zip', 'tar').
            compression: The compression level to use (e.g., 'stored', 'fast', 'best').

        Returns:
            A tuple containing two elements:
                - bytes: The raw binary data of the generated archive buffer.
                - str: The MIME type of the generated archive file.

        Raises:
            ValueError: If an invalid compression level or append configuration is provided.
            OSError: If an error occurs while reading the file or writing to the buffer.
            UnsupportedArchiveFormatError: If the specified archive format is not supported.
        """

        mode, compressor = self._get_compression_settings(archive_format, compression)
        buffer = io.BytesIO()

        if archive_format == "zip":
            kwargs = {
                "allowZip64": True,
                "compression": mode,
            }
            if compressor is not None and mode != zipfile.ZIP_STORED:
                kwargs["compresslevel"] = compressor
            with zipfile.ZipFile(buffer, "w", **kwargs) as zf:
                safe_path = self._sanitize_path(archive_path)
                self._add_bytes_to_zip(zf, safe_path, content, self._current_time)
            mime_type = "application/zip"

        elif archive_format in ("tar.gz", "tar"):
            kwargs = {"fileobj": buffer, "mode": mode}
            if archive_format == "tar.gz" and compressor is not None:
                kwargs["compresslevel"] = compressor
            with tarfile.open(**kwargs) as tf:
                safe_path = self._sanitize_path(archive_path)
                self._add_bytes_to_tar(tf, safe_path, content, self._current_time)
            mime_type = (
                "application/gzip"
                if archive_format == "tar.gz"
                else "application/x-tar"
            )

        elif archive_format == "tar.zst":
            zstd_writer = compressor.stream_writer(buffer, closefd=False)
            try:
                zstd_writer.write(content)
            finally:
                zstd_writer.close()
            mime_type = "application/zstd"
        else:
            raise UnsupportedArchiveFormatError(archive_format)

        buffer.seek(0)
        return buffer.getvalue(), mime_type

    def compress_multiple(
        self,
        target_files: list[File],
        archive_paths: list[str],
        archive_format: str,
        compression: str,
        include_manifest: bool,
        workflow_run_id: str,
    ) -> tuple[bytes, str]:
        """Compress the specified files and create an archive.

        Args:
            target_files: A list of File objects to be compressed.
            archive_paths: A list of paths where the archive files will be saved.
            archive_format: The format of the archive (e.g., 'zip', 'tar').
            compression: The compression level to use (e.g., 'stored', 'fast', 'best').
            include_manifest: True to include a manifest file inside the archive.

        Returns:
            A tuple containing two elements:
                - bytes: The raw binary data of the generated archive buffer.
                - str: The MIME type of the generated archive file.

        Raises:
            ValueError: If an invalid compression level or append configuration is provided.
            FileInconsistencyError: The specified number of folders and files does not match.
            OSError: If an error occurs while reading the file or writing to the buffer.
            UnsupportedArchiveFormatError: If the specified archive format is not supported.
        """

        if isinstance(archive_paths, str):
            paths = [archive_paths]
        elif isinstance(archive_paths, list):
            paths = archive_paths
        else:
            paths = []
        files = target_files if isinstance(target_files, list) else [target_files]

        if len(files) != len(paths):
            raise FileInconsistencyError(
                f"Count mismatch: files({len(files)}) != paths({len(paths)})"
            )

        mode, compressor = self._get_compression_settings(archive_format, compression)
        buffer = io.BytesIO()

        manifest_data = {}
        if include_manifest:
            manifest_data = {
                "manifest_version": self._manifest_version,
                "created_by": self._manifest_creator,
                "plugin_version": self._plugin_version,
                "created_at": datetime.now(UTC).isoformat(),
                "workflow_run_id": workflow_run_id,
                "total_files": len(files),
                "format": archive_format,
                "compression_level": compression,
            }
            manifest_bytes = json.dumps(
                manifest_data, ensure_ascii=False, indent=2
            ).encode("utf-8")

        if archive_format == "zip":
            kwargs = {
                "allowZip64": True,
                "compression": mode,
            }
            if compressor is not None and mode != zipfile.ZIP_STORED:
                kwargs["compresslevel"] = compressor

            with zipfile.ZipFile(buffer, "w", **kwargs) as zf:
                if include_manifest:
                    self._add_bytes_to_zip(
                        zf, "manifest.json", manifest_bytes, self._current_time
                    )
                for file_obj, target_path in zip(files, paths):
                    safe_path = self._sanitize_path(
                        f"{target_path}/{file_obj.filename}"
                    )
                    self._add_bytes_to_zip(
                        zf, safe_path, file_obj.blob, self._current_time
                    )
            mime_type = "application/zip"

        elif archive_format in ("tar.gz", "tar"):
            kwargs = {"fileobj": buffer, "mode": mode}
            if archive_format == "tar.gz" and compressor is not None:
                kwargs["compresslevel"] = compressor
            with tarfile.open(**kwargs) as tf:
                if include_manifest:
                    self._add_bytes_to_tar(
                        tf, "manifest.json", manifest_bytes, self._current_time
                    )
                for file_obj, target_path in zip(files, paths):
                    safe_path = self._sanitize_path(
                        f"{target_path}/{file_obj.filename}"
                    )
                    self._add_bytes_to_tar(
                        tf, safe_path, file_obj.blob, self._current_time
                    )
            mime_type = (
                "application/gzip"
                if archive_format == "tar.gz"
                else "application/x-tar"
            )

        elif archive_format == "tar.zst":
            zstd_writer = compressor.stream_writer(buffer, closefd=False)
            try:
                with tarfile.open(fileobj=zstd_writer, mode=mode) as tf:
                    if include_manifest:
                        self._add_bytes_to_tar(
                            tf, "manifest.json", manifest_bytes, self._current_time
                        )
                    for file_obj, target_path in zip(files, paths):
                        safe_path = self._sanitize_path(
                            f"{target_path}/{file_obj.filename}"
                        )
                        self._add_bytes_to_tar(
                            tf, safe_path, file_obj.blob, self._current_time
                        )
            finally:
                zstd_writer.close()
            mime_type = "application/zstd"

        else:
            raise UnsupportedArchiveFormatError(archive_format)

        buffer.seek(0)
        return buffer.getvalue(), mime_type

    def _sanitize_path(self, path: str) -> str:
        """Sanitizes file paths to mitigate path traversal and directory breakages."""
        path = path.replace("\\", "/")
        path = re.sub(r"^\s*\/+", "", path)
        path = re.sub(r"\.\.\/", "", path)
        parts = [re.sub(r'[:*?"<>|]', "_", p) for p in path.split("/")]
        return "/".join(parts)

    def _get_compression_settings(self, fmt: str, level: str) -> tuple:
        """Maps user string inputs to native Python compression flags and integers."""
        if fmt == "zip":
            if level == "store":
                return zipfile.ZIP_STORED, None
            if level == "fast":
                return zipfile.ZIP_DEFLATED, 1
            elif level == "best":
                return zipfile.ZIP_DEFLATED, 9
            else:
                return zipfile.ZIP_DEFLATED, 6

        elif fmt == "tar.gz":
            if level == "store":
                return "w", None
            if level == "fast":
                return "w:gz", 1
            elif level == "best":
                return "w:gz", 9
            else:
                return "w:gz", 6

        elif fmt == "tar.zst":
            if level == "store" or level == "fast":
                zstd_level = 1
            elif level == "best":
                zstd_level = 22
            else:
                zstd_level = 3
            # streaming tar required for zstd pipe
            cctx = zstd.ZstdCompressor(level=zstd_level)
            return "w|", cctx

        else:
            return "w", None

    def _add_bytes_to_tar(
        self, tf: tarfile.TarFile, name: str, b: bytes, timestamp: int
    ) -> None:
        """Injects raw byte streams directly into a Tar archive stream memory structures."""
        tar_info = tarfile.TarInfo(name=name)
        tar_info.size = len(b)
        tar_info.mtime = timestamp
        tf.addfile(tarinfo=tar_info, fileobj=io.BytesIO(b))

    def _add_bytes_to_zip(
        self, zf: zipfile.ZipFile, name: str, b: bytes, timestamp: int
    ) -> None:
        """Injects raw byte streams into a ZIP archive with a specified timestamp metadata."""
        current_time_tuple = time.localtime(timestamp)[:6]
        zip_info = zipfile.ZipInfo(name, date_time=current_time_tuple)
        zip_info.external_attr = 0o644 << 16
        zf.writestr(zip_info, b)
