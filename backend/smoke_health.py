"""健康检查回归：python smoke_health.py；只使用独立内存 SQLite。"""
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.routers.health import get_provider_name, router, settings


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        self.sessions = sessionmaker(self.engine)
        app = FastAPI()
        app.include_router(router)

        def database():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.client.close)
        self.enterContext(patch.multiple(
            settings, LLM_PROVIDER="bailian", DASHSCOPE_API_KEY="", create=True,
        ))
        self.provider_factory = self.enterContext(patch(
            "app.services.providers.get_provider", side_effect=AssertionError("health must not initialize AI"),
        ))
        self.provider_constructor = self.enterContext(patch(
            "app.services.providers.BailianProvider", side_effect=AssertionError("health must not construct AI"),
        ))

    def test_provider_name_does_not_initialize_ai_without_credentials(self):
        self.assertEqual(get_provider_name(), "bailian")
        self.provider_factory.assert_not_called()
        self.provider_constructor.assert_not_called()

    def test_database_ready_returns_200_without_ai_credentials(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["provider"], "bailian")
        self.assertEqual(payload["version"], settings.APP_VERSION)
        self.provider_factory.assert_not_called()
        self.provider_constructor.assert_not_called()

    def test_database_error_still_returns_503(self):
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE users"))
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "database unavailable"})
        self.provider_factory.assert_not_called()
        self.provider_constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
