"""JD 和简历共用的本地分块上传。目录及允许格式均由服务端指定。"""

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from backend.config import get_settings


async def store_upload(file: UploadFile, directory: str, allowed: set[str], format_error: str) -> tuple[dict, Path]:
    """分块接收文件，控制实际字节数，使用随机文件名而非用户路径。"""
    settings = get_settings()
    name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    extension = Path(name).suffix.lower()
    if not name or "\x00" in name or len(name) > 255 or extension not in allowed:
        raise HTTPException(422, format_error)
    key = f"{directory}/{uuid4().hex}{extension}"
    root = Path(settings.upload_dir).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(500, "上传目录配置无效")
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    size, digest = 0, hashlib.sha256()
    output = path.open("xb")
    try:
        with output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.upload_max_size_bytes:
                    raise HTTPException(413, "文件超过上传大小上限")
                digest.update(chunk)
                await asyncio.to_thread(output.write, chunk)
        if size == 0:
            raise HTTPException(422, "不能上传空文件")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"kind": "file", "storage_key": key, "original_filename": name,
            "file_format": extension[1:], "file_size_bytes": size, "file_sha256": digest.hexdigest()}, path
