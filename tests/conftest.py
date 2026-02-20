"""Pytest configuration and fixtures for all tests."""
import pytest


@pytest.fixture(scope="session")
def aws_credentials(monkeypatch):
    """Mock AWS credentials for moto."""
    import os

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
