from app.core.config import Settings


def test_legacy_routes_default_off_in_production() -> None:
    settings = Settings.model_construct(env="production")
    assert settings.mount_legacy_challenge_routes is False


def test_legacy_routes_default_on_in_development() -> None:
    settings = Settings.model_construct(env="development")
    assert settings.mount_legacy_challenge_routes is True


def test_legacy_routes_explicit_env_wins() -> None:
    on = Settings.model_construct(env="production", legacy_challenge_routes=True)
    assert on.mount_legacy_challenge_routes is True
    off = Settings.model_construct(env="development", legacy_challenge_routes=False)
    assert off.mount_legacy_challenge_routes is False
