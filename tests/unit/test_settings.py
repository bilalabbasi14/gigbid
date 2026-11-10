from agent import settings


def test_config_loads_and_routes_models(monkeypatch):
    monkeypatch.setenv("MODEL_PROFILE", "open")
    settings.reload()
    cfg = settings.config()
    assert cfg.policy_version >= 1
    assert cfg.models.profile == "open"
    # every node in the routing table resolves to a provider-qualified model name
    for node in cfg.models.nodes:
        name = cfg.model_for(node)
        assert ":" in name, f"{node} -> {name} must be provider:model"
    assert cfg.model_for("writer") == cfg.models.profiles["open"].large
    assert cfg.model_for("scout", fallback=True) == cfg.models.profiles["open"].fallback_small


def test_open_profile_uses_only_open_models():
    settings.reload()
    cfg = settings.config()
    prof = cfg.models.profiles["open"]
    for name in (prof.small, prof.medium, prof.large, prof.fallback_small, prof.fallback_large):
        assert not name.startswith("openai:") and "gpt-4" not in name


def test_auto_send_is_hard_off():
    settings.reload()
    assert settings.config().autonomy["auto_send"] is False


def test_env_masks_secrets(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
    settings.reload()
    masked = settings.env().masked()
    assert masked["groq_api_key"] == "***"
