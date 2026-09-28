import re
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "components" / "media_viewer.html"


def test_media_viewer_dom_ids_are_unique():
    source = TEMPLATE.read_text(encoding="utf-8")
    ids = re.findall(r'\bid=["\']([^"\']+)["\']', source)
    duplicates = sorted({element_id for element_id in ids if ids.count(element_id) > 1})
    assert duplicates == []


def test_legacy_padding_overlay_is_removed():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="viewer-padding-overlay-panel"' not in source


def test_hotspot_zone_geometry_is_owned_by_css():
    source = TEMPLATE.read_text(encoding="utf-8")
    for zone in ("left-zone", "center-zone", "right-zone"):
        tag = re.search(rf'<div class="[^"]*{zone}[^"]*"[^>]*>', source)
        assert tag is not None
        assert "style=" not in tag.group(0)


def test_legacy_comic_fit_and_split_controls_are_not_rendered():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="overlay-comic-fit-group"' not in source
    assert 'id="btn-comic-split-spread"' not in source
    assert '>표지 단독<' in source


def test_ridi_viewer_chrome_has_unified_modes_and_persistent_seekbar():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert 'class="viewer-header ridi-viewer-toolbar ridi-viewer-toolbar-top"' in source
    assert 'class="overlay-footer ridi-viewer-toolbar ridi-viewer-toolbar-bottom"' in source
    for mode in ("one", "one-two", "two-one", "scroll"):
        assert f'data-viewer-display-mode="{mode}"' in source
    assert 'data-viewer-display-mode="two-three"' not in source
    assert 'data-action="toggle-viewer-controls"' in source


def test_tts_button_is_in_top_toolbar_immediately_before_toc():
    source = TEMPLATE.read_text(encoding="utf-8")
    listen = '<button type="button" id="btn-viewer-listen"'
    settings = 'id="btn-viewer-tts-settings"'
    toc = '<button type="button" data-role="viewer-action" data-action="open-toc"'
    assert source.count('id="btn-viewer-listen"') == 1
    assert source.index('class="ridi-viewer-tools"') < source.index(listen) < source.index(settings) < source.index(toc)


def test_ridi_view_settings_exposes_values_fonts_themes_and_spread_controls():
    source = TEMPLATE.read_text(encoding="utf-8")
    for element_id in (
        "ridi-viewer-font-select",
        "ridi-font-size-value",
        "ridi-line-height-value",
        "ridi-paragraph-spacing-value",
        "ridi-spread-settings",
        "ridi-center-gap-button",
        "ridi-spread-shift-button",
    ):
        assert f'id="{element_id}"' in source
    for theme in ("epaper", "white", "sepia", "light", "mint", "gray", "blue", "navy", "dark", "black"):
        assert f'data-value="{theme}"' in source
