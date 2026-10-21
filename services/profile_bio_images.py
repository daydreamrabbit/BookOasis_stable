"""Account-owned introduction images; never serve draft images to visitors."""
import fcntl
import hashlib
import io
import os
from pathlib import Path
import re
import time
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError
from services.settings_service import SettingsService

MAX_BIO_IMAGE_BYTES = 5 * 1024 * 1024
MAX_BIO_IMAGE_PIXELS = 20_000_000


def image_path(owner_id, key):
    if not re.fullmatch(r'[a-f0-9]{64}', key):
        raise ValueError('이미지 식별자가 올바르지 않습니다.')
    # Keep private uploads outside the generic /covers file-serving tree.
    root = Path(os.environ.get('PROFILE_BIO_IMAGE_DIR') or Path.cwd() / 'db' / 'profile_bio_images')
    return root / str(int(owner_id)) / (key + '.webp')


def image_url(owner_id, key):
    return f'/api/account/profile/bio-images/{int(owner_id)}/{key}'


def saved_bio(owner_id):
    import json
    try:
        return json.loads(SettingsService.get_user_value(owner_id, 'PROFILE_APPEARANCE', '{}')).get('bio', '')
    except (ValueError, TypeError, AttributeError):
        return ''


def is_referenced(owner_id, key):
    return bool(re.search(r'!\[[^\]\n]*\]\(' + re.escape(image_url(owner_id, key)) + r'\)', saved_bio(owner_id)))


def save_image(owner_id, stream):
    raw = stream.read(MAX_BIO_IMAGE_BYTES + 1)
    if not raw or len(raw) > MAX_BIO_IMAGE_BYTES:
        raise ValueError('소개 이미지는 파일당 5MB 이하로 선택해 주세요.')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ('PNG', 'JPEG', 'WEBP', 'GIF', 'AVIF'):
                raise ValueError('지원하지 않는 이미지 형식입니다.')
            if source.width * source.height > MAX_BIO_IMAGE_PIXELS:
                raise ValueError('소개 이미지 해상도가 너무 큽니다. 2천만 화소 이하로 사용해 주세요.')
            normalized = ImageOps.exif_transpose(source).convert('RGBA')
            normalized.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            normalized.save(output, 'WEBP', quality=88, method=6)
            data = output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('지원하지 않거나 손상된 이미지입니다.') from exc
    key = hashlib.sha256(data).hexdigest()
    target = image_path(owner_id, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    # File lock works across app workers; only discard uncommitted drafts older than a day.
    with (target.parent / '.upload.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        bio = saved_bio(owner_id)
        for old in target.parent.glob('*.webp'):
            if re.fullmatch(r'[a-f0-9]{64}', old.stem) and old.stat().st_mtime < time.time() - 86400 and image_url(owner_id, old.stem) not in bio:
                old.unlink()
        if not target.exists():
            files = list(target.parent.glob('*.webp'))
            if len(files) >= 64 or sum(path.stat().st_size for path in files) + len(data) > 64 * 1024 * 1024:
                raise ValueError('소개 이미지 저장 공간이 가득 찼습니다. 사용하지 않는 초안 이미지는 하루 뒤 정리됩니다.')
            temporary = target.parent / ('.' + uuid.uuid4().hex + '.tmp')
            try:
                temporary.write_bytes(data)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
    return image_url(owner_id, key)
