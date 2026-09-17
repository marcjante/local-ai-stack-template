from backend.app.config import DEFAULT_DATABASE_URL, DEFAULT_VIDEO_DIR, get_settings


def test_standard_provider_environment_variables_are_supported(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("HCPALAU_DATABASE_URL", raising=False)
    monkeypatch.delenv("HCPALAU_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("HCPALAU_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("HCPALAU_VIDEO_DIR", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/hcpalau")
    monkeypatch.setenv("ADMIN_TOKEN", "production-admin-token")
    monkeypatch.setenv("CORS_ORIGINS", "https://club.example")
    monkeypatch.setenv("VIDEO_DIR", str(tmp_path))

    settings = get_settings()

    assert settings.database_url == "postgresql://example/hcpalau"
    assert settings.admin_token == "production-admin-token"
    assert settings.cors_origins == ("https://club.example",)
    assert settings.video_dir == tmp_path


def test_prefixed_variables_take_precedence(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://standard/db")
    monkeypatch.setenv("HCPALAU_DATABASE_URL", "postgresql://prefixed/db")
    monkeypatch.setenv("ADMIN_TOKEN", "standard-token")
    monkeypatch.setenv("HCPALAU_ADMIN_TOKEN", "prefixed-token")

    settings = get_settings()

    assert settings.database_url == "postgresql://prefixed/db"
    assert settings.admin_token == "prefixed-token"


def test_local_defaults_remain_available(monkeypatch) -> None:
    for name in (
        "DATABASE_URL",
        "HCPALAU_DATABASE_URL",
        "ADMIN_TOKEN",
        "HCPALAU_ADMIN_TOKEN",
        "CORS_ORIGINS",
        "HCPALAU_CORS_ORIGINS",
        "VIDEO_DIR",
        "HCPALAU_VIDEO_DIR",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.admin_token == "dev-admin-token"
    assert settings.video_dir == DEFAULT_VIDEO_DIR
