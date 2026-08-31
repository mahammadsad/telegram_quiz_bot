from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_primary_surfaces_use_citizen_affairs_browser_fallbacks() -> None:
    css_files = (
        "index.css",
        "dashboard.css",
        "settings.css",
        "practice.css",
        "mock.css",
        "syllabus.css",
    )
    for filename in css_files:
        source = (ROOT / filename).read_text(encoding="utf-8").lower()
        assert "#b42318" in source, filename
        assert "--tg-theme" in source, filename

    assert "#0a5aa6" in (ROOT / "index.css").read_text(encoding="utf-8").lower()
    assert "#0a5aa6" in (ROOT / "legal.css").read_text(encoding="utf-8").lower()


def test_installable_pages_publish_the_parent_brand_theme_color() -> None:
    for filename in (
        "index.html",
        "dashboard.html",
        "settings.html",
        "practice.html",
        "mock.html",
        "syllabus.html",
        "admin.html",
    ):
        source = (ROOT / filename).read_text(encoding="utf-8").lower()
        assert '<meta name="theme-color" content="#b42318" />' in source, filename

    manifest = (ROOT / "manifest.webmanifest").read_text(encoding="utf-8").lower()
    icon = (ROOT / "pwa-icon.svg").read_text(encoding="utf-8").lower()
    assert '"theme_color": "#b42318"' in manifest
    assert '"background_color": "#f7f7f6"' in manifest
    assert "#b42318" in icon


def test_brand_release_invalidates_the_previous_pwa_shell_cache() -> None:
    source = (ROOT / "service-worker.js").read_text(encoding="utf-8")
    assert "quiz-miniapp-shell-v8.7.2-ui3" in source
    assert "quiz-answer-free-v8.7.2-ui3" in source


def test_quiz_intro_keeps_parent_site_cta_before_start() -> None:
    source = (ROOT / "index.html").read_text(encoding="utf-8")
    intro_start = source.index('id="screen-intro"')
    quiz_start = source.index('id="screen-quiz"')
    intro = source[intro_start:quiz_start]

    assert "https://citizenaffairs.in/bn/" in intro
    assert "utm_source=telegram" in intro
    assert "Citizen Affairs বাংলা" in intro
