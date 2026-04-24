import hashlib
import mimetypes
import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.utils import timezone


class ResumeStorageError(Exception):
    pass


class ResumeStorageConfigurationError(ResumeStorageError):
    pass


def store_uploaded_resume(
    resume_file,
    *,
    job_description,
    target_role,
    experience_level,
    resume_text,
):
    if not cloudant_storage_is_configured():
        return {
            "provider": "cloudant",
            "status": "disabled",
        }

    client, api_exception_class = get_cloudant_client()
    database_name = settings.CLOUDANT_DATABASE

    ensure_database_exists(
        client=client,
        database_name=database_name,
        api_exception_class=api_exception_class,
    )

    original_filename = get_original_filename(resume_file.name)
    attachment_name = build_attachment_name(original_filename)
    content_type = detect_content_type(resume_file, original_filename)
    file_bytes = read_uploaded_file(resume_file)
    document_id = f"resume:{uuid4().hex}"

    document = {
        "type": "uploaded_resume",
        "uploaded_at": timezone.now().isoformat(),
        "original_filename": original_filename,
        "attachment_name": attachment_name,
        "content_type": content_type,
        "file_size_bytes": len(file_bytes),
        "sha256": hashlib.sha256(file_bytes).hexdigest(),
        "target_role": target_role,
        "experience_level": experience_level,
        "job_description_length": len(job_description),
        "resume_word_count": len((resume_text or "").split()),
    }

    try:
        created_document = client.put_document(
            db=database_name,
            doc_id=document_id,
            document=document,
        ).get_result()
        current_revision = created_document["rev"]
        client.put_attachment(
            db=database_name,
            doc_id=document_id,
            attachment_name=attachment_name,
            attachment=BytesIO(file_bytes),
            content_type=content_type,
            rev=current_revision,
        ).get_result()
    except api_exception_class as exc:
        raise ResumeStorageError(clean_cloudant_error(exc)) from exc
    except Exception as exc:
        raise ResumeStorageError(f"Cloudant storage failed: {exc}") from exc

    return {
        "provider": "cloudant",
        "status": "stored",
        "database": database_name,
        "documentId": document_id,
        "attachmentName": attachment_name,
    }


def cloudant_storage_is_configured():
    url = settings.CLOUDANT_URL
    apikey = settings.CLOUDANT_APIKEY

    if not url and not apikey:
        return False

    if not url or not apikey:
        raise ResumeStorageConfigurationError(
            "Cloudant resume storage is partially configured. Set both CLOUDANT_URL and CLOUDANT_APIKEY."
        )

    return True


@lru_cache(maxsize=1)
def get_cloudant_client():
    try:
        from ibm_cloud_sdk_core import ApiException
        from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
        from ibmcloudant.cloudant_v1 import CloudantV1
    except ImportError as exc:
        raise ResumeStorageConfigurationError(
            "Cloudant resume storage needs the `ibmcloudant` package. Run `pip install -r requirements.txt`."
        ) from exc

    authenticator = IAMAuthenticator(settings.CLOUDANT_APIKEY)
    client = CloudantV1(authenticator=authenticator)
    client.set_service_url(settings.CLOUDANT_URL)
    return client, ApiException


def ensure_database_exists(client, database_name, api_exception_class):
    try:
        client.put_database(db=database_name).get_result()
    except api_exception_class as exc:
        if getattr(exc, "code", None) == 412:
            return
        raise ResumeStorageError(clean_cloudant_error(exc)) from exc


def read_uploaded_file(resume_file):
    resume_file.seek(0)
    content = resume_file.read()
    resume_file.seek(0)

    if not content:
        raise ResumeStorageError("The uploaded resume file was empty.")

    return content


def get_original_filename(filename):
    cleaned_name = Path(filename or "resume").name.strip()
    return cleaned_name or "resume"


def build_attachment_name(filename):
    extension = Path(filename).suffix.lower()

    if not re.fullmatch(r"\.[a-z0-9]{1,8}", extension):
        extension = ".bin"

    return f"resume{extension}"


def detect_content_type(resume_file, filename):
    content_type = getattr(resume_file, "content_type", "") or ""

    if content_type:
        return content_type

    guessed_type, _ = mimetypes.guess_type(filename)
    return guessed_type or "application/octet-stream"


def clean_cloudant_error(exc):
    message = str(exc)
    code = getattr(exc, "code", None)

    if code == 401:
        return "Cloudant rejected the credentials. Check CLOUDANT_URL and CLOUDANT_APIKEY."

    if code == 403:
        return "Cloudant denied access to the configured database. Check the API key permissions."

    if code == 404:
        return "Cloudant could not reach the configured service or database path. Check CLOUDANT_URL."

    return f"Cloudant storage failed: {message}"
