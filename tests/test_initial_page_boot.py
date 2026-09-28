from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_initial_page_uses_boot_cloak_until_javascript_selects_the_view():
    source = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert '<html lang="ko" class="app-booting">' in source
    assert "html.app-booting .library-main-content" in source
    assert "document.documentElement.classList.remove('app-booting')" in source


def test_collection_fallback_uses_an_existing_translation_key():
    source = (ROOT / "templates" / "components" / "tab_media_library.html").read_text(encoding="utf-8")
    assert 'data-i18n="category.collection">컬렉션</span>' in source
    assert 'data-i18n="sidebar.collection"' not in source


def test_library_boot_waits_for_i18n_and_always_reveals_the_page():
    source = (ROOT / "static" / "js" / "tab_media_library.js").read_text(encoding="utf-8")
    assert "document.addEventListener('i18nReady', finish, { once: true })" in source
    assert "document.documentElement.classList.remove('app-booting')" in source
