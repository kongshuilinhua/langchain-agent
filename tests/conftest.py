import importlib
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


@pytest.fixture()
def client(monkeypatch):
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Test database required. Set TEST_DATABASE_URL.")

    _terminate_database_connections(database_url)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            dialect_name = engine.dialect.name
            if dialect_name == "postgresql":
                connection.execute(text("SET lock_timeout = '10s'"))
                connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
            elif dialect_name == "mysql":
                connection.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
                db_inspector = inspect(engine)
                for table in db_inspector.get_table_names():
                    connection.execute(text(f"DROP TABLE IF EXISTS `{table}`"))
                connection.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    except Exception as exc:
        pytest.skip(f"Test database is not available: {exc}")
    finally:
        engine.dispose()

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LINGSHU_MOCK_LLM", "true")
    monkeypatch.setenv("LINGSHU_VECTOR_BACKEND", "memory")
    # 上传体积限额测试假设 8MB；运行时默认已调大到 30MB，固定测试环境为 8MB 让限额机制校验成立。
    monkeypatch.setenv("UPLOAD_MAX_BYTES", str(8 * 1024 * 1024))
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

    import api.routes.knowledge as knowledge_route
    import api.routes.chat as chat_route
    importlib.reload(db_session)
    importlib.reload(vector_module)
    importlib.reload(knowledge_service)
    importlib.reload(workflow_runtime)
    importlib.reload(knowledge_route)
    importlib.reload(chat_route)
    importlib.reload(main)
    db_session.init_db()
    with TestClient(main.app) as test_client:
        try:
            yield test_client
        finally:
            db_session.engine.dispose()


def _terminate_database_connections(database_url: str) -> None:
    """Terminate active connections to the test database (PostgreSQL only)."""
    url = make_url(database_url)
    if url.get_dialect().name != "postgresql":
        return  # Only applicable to PostgreSQL
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
