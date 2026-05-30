import importlib
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture()
def client(monkeypatch):
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url or not database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL test database required. Set TEST_DATABASE_URL. The fixture resets the public schema.")

    _terminate_postgres_database_connections(database_url)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("SET lock_timeout = '10s'"))
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL test database is not available: {exc}")
    finally:
        engine.dispose()

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LINGSHU_MOCK_LLM", "true")
    monkeypatch.setenv("LINGSHU_VECTOR_BACKEND", "memory")
    for key in [
        "OPENAI_API_KEY",
        "DASHSCOPE_API_KEY",
        "DEEPSEEK_API_KEY",
        "EMBEDDING_API_KEY",
        "RERANK_API_KEY",
    ]:
        monkeypatch.setenv(key, "")
    import core.config

    core.config.get_settings.cache_clear()
    import core.db.session as db_session
    import core.integrations.vector_store as vector_module
    import core.services.knowledge as knowledge_service
    import core.runtime.workflow as workflow_runtime
    import api.main as main

    importlib.reload(db_session)
    importlib.reload(vector_module)
    importlib.reload(knowledge_service)
    importlib.reload(workflow_runtime)
    importlib.reload(main)
    db_session.init_db()
    with TestClient(main.app) as test_client:
        try:
            yield test_client
        finally:
            db_session.engine.dispose()


def _terminate_postgres_database_connections(database_url: str) -> None:
    url = make_url(database_url)
    database = url.database
    if not database:
        return
    admin_url = url.set(database="postgres")
    admin_engine = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database AND pid <> pg_backend_pid()"
                ),
                {"database": database},
            )
    finally:
        admin_engine.dispose()


@pytest.fixture()
def owner_token(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "owner@example.com", "name": "Owner", "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.fixture()
def auth_headers(owner_token):
    return {"Authorization": f"Bearer {owner_token}"}
