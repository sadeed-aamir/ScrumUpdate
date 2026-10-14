##############################################################################
# Copyright 2026 UWorx Services.
# Licensed under the Apache License, Version 2.0.
# See LICENSE for the full license text.
##############################################################################

from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kss.api.health import health_router

app = FastAPI()
app.include_router(health_router)
client = TestClient(app)


@patch("kss.api.health.multi_tenant_manager")
@patch("kss.api.health.celery_app")
@patch("kss.api.health.DatabaseManager")
def test_health_check_healthy(mock_db_cls, mock_celery, mock_tenant_mgr):
    # Mock Database
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    # Mock Celery inspect
    mock_inspect = MagicMock()
    mock_inspect.active.return_value = {"worker1@host": []}
    mock_inspect.reserved.return_value = {}
    mock_celery.control.inspect.return_value = mock_inspect

    # Mock Multi-tenant
    mock_tenant_mgr.list_tenants.return_value = ["tenant1"]

    response = client.get("/api/system/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["checks"]["database"] == "healthy"
    assert data["checks"]["redis"] == "healthy"
    assert "healthy" in data["checks"]["celery_workers"]


@patch("kss.api.health.multi_tenant_manager")
@patch("kss.api.health.celery_app")
@patch("kss.api.health.DatabaseManager")
def test_health_check_degraded(mock_db_cls, mock_celery, mock_tenant_mgr):
    # Mock Database
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    # Mock Celery inspect returning no active workers
    mock_inspect = MagicMock()
    mock_inspect.active.return_value = {}
    mock_inspect.reserved.return_value = {}
    mock_celery.control.inspect.return_value = mock_inspect

    # Mock Multi-tenant
    mock_tenant_mgr.list_tenants.return_value = ["tenant1"]

    response = client.get("/api/system/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["checks"]["celery_workers"] == "no workers available"


@patch("kss.api.health.multi_tenant_manager")
@patch("kss.api.health.celery_app")
@patch("kss.api.health.DatabaseManager")
def test_health_check_unhealthy(mock_db_cls, mock_celery, mock_tenant_mgr):
    # Mock Database throwing exception
    mock_db_cls.side_effect = Exception("DB Connection Refused")

    # Mock Celery inspect
    mock_inspect = MagicMock()
    mock_inspect.active.return_value = {"worker1@host": []}
    mock_inspect.reserved.return_value = {}
    mock_celery.control.inspect.return_value = mock_inspect

    # Mock Multi-tenant
    mock_tenant_mgr.list_tenants.return_value = ["tenant1"]

    response = client.get("/api/system/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    assert "unhealthy: DB Connection Refused" in data["checks"]["database"]
