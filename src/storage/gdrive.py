"""Google Drive storage integration."""

import json
import re
from datetime import datetime
from io import BytesIO
from typing import Optional

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from config.settings import settings
from src.models import Job

logger = structlog.get_logger()


class GoogleDriveStorage:
    """Handle file storage on Google Drive."""

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    def __init__(
        self,
        credentials_json: Optional[str] = None,
        folder_id: Optional[str] = None,
    ):
        """
        Initialize Google Drive storage.

        Args:
            credentials_json: Service account credentials JSON string
            folder_id: Root folder ID for JobHunter files
        """
        self.credentials_json = credentials_json or settings.google_drive_credentials
        self.folder_id = folder_id or settings.google_drive_folder_id
        self.service = self._build_service()

    def _build_service(self):
        """Build Google Drive API service."""
        if not self.credentials_json:
            logger.warning("Google Drive credentials not configured")
            return None

        try:
            creds_dict = json.loads(self.credentials_json)
            credentials = service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=self.SCOPES,
            )
            return build("drive", "v3", credentials=credentials)
        except Exception as e:
            logger.error(f"Failed to build Drive service: {e}")
            return None

    def _get_or_create_folder(self, name: str, parent_id: str = None) -> str:
        """
        Get or create a folder.

        Args:
            name: Folder name
            parent_id: Parent folder ID

        Returns:
            Folder ID
        """
        parent_id = parent_id or self.folder_id

        # Check if folder exists
        query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        results = self.service.files().list(q=query, spaces="drive").execute()
        files = results.get("files", [])

        if files:
            return files[0]["id"]

        # Create folder
        file_metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            file_metadata["parents"] = [parent_id]

        folder = self.service.files().create(body=file_metadata, fields="id").execute()
        return folder.get("id")

    def _get_monthly_folder(self, base_folder: str) -> str:
        """
        Get or create monthly folder (e.g., 2025-11).

        Args:
            base_folder: Base folder name (CVs, Cover_Letters)

        Returns:
            Monthly folder ID
        """
        # Get/create base folder
        base_folder_id = self._get_or_create_folder(base_folder, self.folder_id)

        # Get/create monthly folder
        month_folder = datetime.now().strftime("%Y-%m")
        return self._get_or_create_folder(month_folder, base_folder_id)

    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename."""
        # Remove characters invalid for filenames
        return re.sub(r'[<>:"/\\|?*]', "_", filename)

    def upload_file(
        self,
        content: bytes,
        filename: str,
        mime_type: str,
        folder_id: str,
    ) -> str:
        """
        Upload a file to Google Drive.

        Args:
            content: File content as bytes
            filename: Filename
            mime_type: MIME type
            folder_id: Destination folder ID

        Returns:
            Shareable URL for the file
        """
        if not self.service:
            logger.error("Google Drive service not available")
            return ""

        filename = self._sanitize_filename(filename)

        file_metadata = {
            "name": filename,
            "parents": [folder_id],
        }

        media = MediaIoBaseUpload(
            BytesIO(content),
            mimetype=mime_type,
            resumable=True,
        )

        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
        ).execute()

        # Make file viewable by anyone with link
        self.service.permissions().create(
            fileId=file["id"],
            body={"type": "anyone", "role": "reader"},
        ).execute()

        logger.info(f"Uploaded file: {filename}")
        return file.get("webViewLink", "")

    def upload_cv(self, cv_content: dict, job: Job) -> str:
        """
        Upload a tailored CV.

        Args:
            cv_content: CV content dict
            job: Job the CV is for

        Returns:
            Shareable URL
        """
        from src.generation.cv_tailor import CVTailor

        # Generate DOCX
        tailor = CVTailor()
        docx_bytes = tailor.generate_docx(cv_content, job)

        # Get monthly folder
        folder_id = self._get_monthly_folder("CVs")

        # Generate filename
        filename = f"{job.company}_{job.title}_CV.docx"

        return self.upload_file(
            docx_bytes,
            filename,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            folder_id,
        )

    def upload_cover_letter(self, cover_letter: str, job: Job) -> str:
        """
        Upload a cover letter.

        Args:
            cover_letter: Cover letter text
            job: Job the letter is for

        Returns:
            Shareable URL
        """
        from src.generation.cover_letter import CoverLetterGenerator

        # Generate DOCX
        generator = CoverLetterGenerator()
        docx_bytes = generator.generate_docx(cover_letter, job)

        # Get monthly folder
        folder_id = self._get_monthly_folder("Cover_Letters")

        # Generate filename
        filename = f"{job.company}_{job.title}_CL.docx"

        return self.upload_file(
            docx_bytes,
            filename,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            folder_id,
        )

    def upload_interview_prep(self, prep_content: str, job: Job) -> str:
        """
        Upload interview preparation notes.

        Args:
            prep_content: Prep notes as text
            job: Job the prep is for

        Returns:
            Shareable URL
        """
        # Get/create Interview_Prep folder
        prep_folder_id = self._get_or_create_folder("Interview_Prep", self.folder_id)

        # Get/create company folder
        company_folder_id = self._get_or_create_folder(job.company, prep_folder_id)

        # Upload as text file
        filename = f"{job.title}_prep.md"

        return self.upload_file(
            prep_content.encode("utf-8"),
            filename,
            "text/markdown",
            company_folder_id,
        )
