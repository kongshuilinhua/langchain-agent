from core.config import Settings


def _settings(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_production_readiness_is_not_applied_in_development(monkeypatch):
    settings = _settings(monkeypatch, LINGSHU_DEPLOYMENT_MODE="development")

    assert settings.production_readiness_issues() == []


def test_production_readiness_blocks_development_defaults(monkeypatch):
    settings = _settings(monkeypatch, LINGSHU_DEPLOYMENT_MODE="production")

    issues = settings.production_readiness_issues()

    assert any("JWT_SECRET" in issue for issue in issues)
    assert any("API_KEY_ENCRYPTION_KEY" in issue for issue in issues)
    assert any("LINGSHU_VECTOR_BACKEND=memory" in issue for issue in issues)
    assert any("CELERY_ENABLED=true" in issue for issue in issues)


def test_production_readiness_accepts_hardened_config(monkeypatch):
    settings = _settings(
        monkeypatch,
        LINGSHU_DEPLOYMENT_MODE="production",
        JWT_SECRET="x" * 48,
        API_KEY_ENCRYPTION_KEY="y" * 48,
        DATABASE_URL="mysql+pymysql://lingshu_prod:strong-password@db:3306/lingshu_agent",
        REDIS_URL="redis://redis:6379/0",
        CELERY_ENABLED="true",
        LINGSHU_VECTOR_BACKEND="milvus",
        CORS_ORIGINS="https://agent.example.com",
        STORAGE_BACKEND="minio",
        STORAGE_ACCESS_KEY="lingshu-prod",
        STORAGE_SECRET_KEY="z" * 48,
    )

    assert settings.production_readiness_issues() == []
