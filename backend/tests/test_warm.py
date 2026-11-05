from lecturelens import embed
from lecturelens.api import main


def test_models_are_loaded_before_the_first_search(models_env):
    embed.text_embedder.cache_clear()
    embed.clip_embedder.cache_clear()
    main.warm_models()
    assert embed.text_embedder.cache_info().currsize == 1
    assert embed.clip_embedder.cache_info().currsize == 1


def test_no_models_is_fine(monkeypatch, tmp_path):
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))
    main.get_settings.cache_clear()
    embed.text_embedder.cache_clear()
    try:
        main.warm_models()
        assert embed.text_embedder.cache_info().currsize == 0
    finally:
        main.get_settings.cache_clear()


def test_https_deploy_refuses_the_default_secret(monkeypatch):
    import pytest

    from lecturelens.api.main import create_app
    from lecturelens.config import get_settings

    monkeypatch.setenv("COOKIE_SECURE", "true")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            create_app()
        monkeypatch.setenv("SECRET_KEY", "x" * 64)
        get_settings.cache_clear()
        create_app()
    finally:
        get_settings.cache_clear()


def test_signed_links_cant_claim_a_far_future_expiry():
    import time

    from lecturelens import signing

    exp, sig = signing.sign("media:a.mp4", 60)
    assert signing.verify("media:a.mp4", exp, sig)
    far = int(time.time()) + 10 * 365 * 86400
    assert not signing.verify("media:a.mp4", far, signing._mac("media:a.mp4", far))
