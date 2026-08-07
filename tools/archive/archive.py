import json
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.constants import DIFY_FILE_IDENTITY
from dify_plugin.file.file import FileType
from utils.archiver import ArchiveUtility, FileInconsistencyError
from utils.logger import get_plugin_logger
from utils.urls import get_file_urls


class ArchiverTool(Tool):
    """A Dify workflow tool that archives mass files into a single structured package.

    This tool handles dynamic file aggregation, path sanitization to prevent traversal,
    and supports modern compression algorithms like Zstandard alongside ZIP and TAR.GZ.
    """

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:

        # Extract and parse tool parameters from Dify payload
        archive_name = tool_parameters.get("archive_name", "archive")
        files = tool_parameters["files"]
        folder = tool_parameters.get("archive_path")
        archive_format = tool_parameters.get("format", "zip")
        compression = tool_parameters.get("compression", "normal")
        include_manifest = (
            str(tool_parameters.get("include_manifest", "false")).lower() == "true"
        )
        workflow_run_id = tool_parameters.get("workflow_run_id")
        logger = get_plugin_logger(__name__ + f":{workflow_run_id}")
        logger.info("=================================")
        logger.info(" START archive _invoke()")
        logger.info("=================================")

        # Verify whether the specified number of folders and files matches.
        folders = [p.strip() for p in folder.split(",")]
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

        utility = ArchiveUtility()
        blob, mime_type = utility.compress_multiple(
            target_files=files,
            archive_paths=folders,
            archive_format=archive_format,
            compression=compression,
            include_manifest=include_manifest,
            workflow_run_id=workflow_run_id,
        )
        filename = f"{archive_name}.{archive_format}"
        upload_response = self.session.file.upload(
            filename=filename,
            content=blob,
            mimetype=mime_type,
        )

        # Convert to URL format for end users
        internal_url, files_url = get_file_urls()
        correct_url = upload_response.preview_url.replace(internal_url, files_url)

        # Creating a dictionary-format file
        file_id = upload_response.id
        file_data = {
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
            "filename": filename,
            "name": filename,
            "extension": archive_format,
            "size": upload_response.size,
            "type": FileType.DOCUMENT,
        }
        logger.info(f"file_data: {file_data}")

        result = {
            "status": "completed",
            "archives": filename,
        }
        yield self.create_variable_message(
            "archives",
            [file_data],
        )
        yield self.create_text_message(json.dumps(result))
        yield self.create_json_message(result)

        logger.info("=================================")
        logger.info(" END archive invoke()")
        logger.info("=================================")
