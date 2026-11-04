"""Public registration checks using an isolated, in-memory database."""

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db import Base, get_db
from models import User
from routers.auth import router
from schemas import UserCreate


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)

        def test_db():
            with self.sessions() as session:
                yield session

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = test_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def register(self, **fields):
        return self.client.post("/auth/register", json={
            "email": "learner@example.com",
            "password": "local-test-password",
            **fields,
        })

    def test_admin_and_unknown_roles_are_rejected_without_creating_users(self):
        for index, role in enumerate(("admin", "Admin", "superuser", "", None)):
            with self.subTest(role=role):
                response = self.register(role=role, email=f"rejected{index}@example.com")
                self.assertEqual(response.status_code, 422, response.text)
        with self.sessions() as session:
            self.assertEqual(session.scalars(select(User)).all(), [])

    def test_existing_public_roles_are_preserved(self):
        for role in ("student", "teacher"):
            with self.subTest(role=role):
                response = self.register(role=role, email=f"{role}@example.com")
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(response.json()["role"], role)
                with self.sessions() as session:
                    user = session.scalar(select(User).where(User.email == f"{role}@example.com"))
                    self.assertEqual(user.role, role)

    def test_role_is_still_required(self):
        response = self.register()
        self.assertEqual(response.status_code, 422, response.text)

    def test_duplicate_registration_still_returns_conflict(self):
        self.assertEqual(self.register(role="student").status_code, 201)
        self.assertEqual(self.register(role="student").status_code, 409)

    def test_admin_creation_schema_still_accepts_admin(self):
        # The protected /admin/users route keeps its separate, existing schema.
        user = UserCreate(email="admin@example.com", password="test-password", role="admin")
        self.assertEqual(user.role, "admin")


if __name__ == "__main__":
    unittest.main()
