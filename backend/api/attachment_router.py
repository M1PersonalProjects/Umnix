from pathlib import Path
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

from backend.auth.security import get_current_user
from database import db
from backend.web.activity import record_activity
from backend.web.attachment_storage import (
    delete_attachment,
    ensure_attachment_access,
    forget_attachment_from_chat_memory,
    list_chat_attachment_library,
    save_upload,
)


router = APIRouter(
    prefix="/api/v1/attachments",
    tags=["Attachments v1"],
)


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_attachments(
    files: List[UploadFile] = File(...),
    user=Depends(get_current_user),
):
    """
    Загрузка файлов в хранилище ИИ-тьютора (ограничение 10 файлов за раз).
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Выберите хотя бы один файл",
        )

    if len(files) > 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="За один раз можно загрузить не более 10 файлов",
        )

    uploaded = []

    for file in files:
        attachment = await save_upload(
            upload=file,
            owner_id=user["tg_id"],
        )
        uploaded.append(attachment.to_dict())
        await record_activity(
            int(user["tg_id"]),
            "file_upload",
            attachment.original_name,
            attachment_id=attachment.attachment_id,
        )

    return {"attachments": uploaded}


@router.get("")
async def list_my_attachments(
    limit: int = 50,
    user=Depends(get_current_user),
):
    """
    Получение списка загруженных пользователем файлов с ограничением по количеству.
    Лимит максимум 100, нужно для пагинации в будущем.
    """
    limit = min(max(limit, 1), 100)

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                attachment_id,
                original_name,
                mime_type,
                extension,
                size_bytes,
                processing_status,
                created_at
            FROM attachments
            WHERE owner_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user["tg_id"],
            limit,
        )

    return [
        {
            **dict(row),
            "download_url":
                f"/api/v1/attachments/{row['attachment_id']}/download",
            "preview_url":
                f"/api/v1/attachments/{row['attachment_id']}/preview",
        }
        for row in rows
    ]


@router.get("/library")
async def attachment_library(
    user=Depends(get_current_user),
):
    """Return chat attachments grouped by WebApp/Telegram chat session.

    This is the data source for the dedicated file-library page.  Task-owned
    files remain protected by the storage service and are not detached by
    merely browsing the library.
    """
    groups = await list_chat_attachment_library(int(user["tg_id"]))
    return {"groups": groups}


@router.delete("/{attachment_id}/memory")
async def forget_attachment_memory(
    attachment_id: int,
    user=Depends(get_current_user),
):
    """Forget a file from tutor/chat memory without breaking task history.

    The storage service removes chat-message links and active chat context. If
    the attachment is still referenced by an assignment/submission/draft it is
    retained physically; otherwise it may be deleted from storage as well.
    """
    result = await forget_attachment_from_chat_memory(
        attachment_id=attachment_id,
        owner_id=int(user["tg_id"]),
    )
    return result


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: int,
    user=Depends(get_current_user),
):
    """
    Загрузка файла из хранилища ИИ-тьютора.
    Для того, чтобы пользователь смог выгрузить ранее загруженный файл.
    """
    attachment = await ensure_attachment_access(
        attachment_id,
        user,
    )

    path: Path = attachment["absolute_path"]

    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Файл отсутствует в хранилище",
        )

    await record_activity(
        int(user["tg_id"]),
        "file_download",
        str(attachment["original_name"]),
        attachment_id=attachment_id,
    )
    return FileResponse(
        path=str(path),
        media_type=attachment["mime_type"],
        filename=attachment["original_name"],
    )


@router.get("/{attachment_id}/preview")
async def preview_attachment(
    attachment_id: int,
    user=Depends(get_current_user),
):
    """
    Предпросмотр файла из хранилища ИИ-тьютора.
    Для того, чтобы пользователь смог просмотреть ранее загруженный файл.
    """
    attachment = await ensure_attachment_access(
        attachment_id,
        user,
    )

    path: Path = attachment["absolute_path"]

    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Файл отсутствует в хранилище",
        )

    previewable = (
        attachment["mime_type"].startswith("image/")
        or attachment["mime_type"] == "application/pdf"
        or attachment["mime_type"].startswith("text/")
    )

    if not previewable:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Предпросмотр этого формата не поддерживается",
        )

    await record_activity(
        int(user["tg_id"]),
        "file_preview",
        str(attachment["original_name"]),
        attachment_id=attachment_id,
    )

    headers = {
        "Content-Disposition":
            f'inline; filename="{attachment["storage_name"]}"'
    }

    return FileResponse(
        path=str(path),
        media_type=attachment["mime_type"],
        headers=headers,
    )


@router.delete(
    "/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_attachment(
    attachment_id: int,
    user=Depends(get_current_user),
):
    """
    Удаление файла из хранилища ИИ-тьютора.
    """
    await delete_attachment(
        attachment_id=attachment_id,
        owner_id=user["tg_id"],
    )