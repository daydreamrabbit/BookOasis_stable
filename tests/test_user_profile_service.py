import io

import pytest
from PIL import Image

from services.user_profile_service import (
    DEFAULT_PROFILE_AVATAR,
    MAX_DISPLAY_NAME_LENGTH,
    PROFILE_AVATAR_SIZE,
    get_custom_avatar_mimetype,
    get_custom_avatar_path,
    normalize_avatar_key,
    normalize_display_name,
    save_custom_avatar_image,
)


def test_profile_display_name_is_trimmed_and_collapses_whitespace():
    assert normalize_display_name('  Rabbit   Oasis  ') == 'Rabbit Oasis'


def test_profile_display_name_falls_back_and_is_bounded():
    assert normalize_display_name('   ', 'reader') == 'reader'
    assert len(normalize_display_name('가' * 100)) == MAX_DISPLAY_NAME_LENGTH


def test_profile_avatar_accepts_only_known_presets():
    assert normalize_avatar_key('MOON') == 'moon'
    assert normalize_avatar_key('../../etc/passwd') == DEFAULT_PROFILE_AVATAR


def test_custom_profile_avatar_is_cropped_and_saved_as_webp(tmp_path):
    source = io.BytesIO()
    Image.new('RGB', (900, 450), '#4f46e5').save(source, format='PNG')
    source.seek(0)

    result = save_custom_avatar_image(7, source, base_dir=tmp_path)

    assert result == get_custom_avatar_path(7, base_dir=tmp_path)
    assert result.name == 'user_7.webp'
    with Image.open(result) as saved:
        assert saved.format == 'WEBP'
        assert saved.size == (PROFILE_AVATAR_SIZE, PROFILE_AVATAR_SIZE)


def test_custom_profile_avatar_rejects_non_image(tmp_path):
    with pytest.raises(ValueError, match='지원하지 않거나 손상된 이미지'):
        save_custom_avatar_image(3, io.BytesIO(b'not-an-image'), base_dir=tmp_path)


def test_animated_gif_avatar_keeps_animation(tmp_path):
    source = io.BytesIO()
    frames = [Image.new('RGBA', (40, 24), color) for color in ('#ef4444', '#22c55e', '#3b82f6')]
    frames[0].save(
        source,
        format='GIF',
        save_all=True,
        append_images=frames[1:],
        duration=[80, 100, 120],
        loop=0,
    )
    source.seek(0)

    result = save_custom_avatar_image(9, source, base_dir=tmp_path)

    assert result.name == 'user_9.gif'
    assert get_custom_avatar_path(9, base_dir=tmp_path) == result
    assert get_custom_avatar_mimetype(9, base_dir=tmp_path) == 'image/gif'
    with Image.open(result) as saved:
        assert saved.format == 'GIF'
        assert saved.is_animated
        assert saved.n_frames == 3
        assert saved.size == (PROFILE_AVATAR_SIZE, PROFILE_AVATAR_SIZE)
