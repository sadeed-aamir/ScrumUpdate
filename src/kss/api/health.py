##############################################################################
# Copyright 2026 UWorx Services.
# Licensed under the Apache License, Version 2.0.
# See LICENSE for the full license text.
##############################################################################

"""
Health check endpoints.
Provides system health monitoring and statistics.
"""

import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Response, status
from database import DatabaseManager
from tasks import app as celery_app
from multi_tenant_manager import multi_tenant_manager
from models import SystemHealthResponse, SystemStatsResponse

logger = logging.getLogger(__name__)
health_router = APIRouter(prefix="/api/system", tags=["system"])


@health_router.get("/ping")
async def ping():
    """Lightweight liveness probe used by the Docker HEALTHCHECK.

    Returns immediately without touching DB/Redis/Celery — the deeper
    `/health` check opens connections and broadcasts to workers, which
    takes longer than the healthcheck probe budget.
    """
    return {"status": "ok"}


@health_router.get("/health", response_model=SystemHealthResponse)
async def get_system_health(response: Response):
    """
    Get comprehensive system health information.

    Checks the status of:
    - Database connectivity
    - Redis connectivity
    - Celery worker availability
    - Queue statistics
    """
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now(),
            "checks": {},
            "queue_stats": {},
        }

        # Check database
        try:
            db_manager = DatabaseManager()
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    health_status["checks"]["database"] = "healthy"
        except Exception as e:
            health_status["checks"]["database"] = f"unhealthy: {str(e)}"
            health_status["status"] = "unhealthy"

        # Check Redis
        try:
            celery_app.backend.get("health_check")
            health_status["checks"]["redis"] = "healthy"
        except Exception as e:
            health_status["checks"]["redis"] = f"unhealthy: {str(e)}"
            health_status["status"] = "unhealthy"

        # Check Celery workers
        try:
            inspect = celery_app.control.inspect()
            active_workers = inspect.active()
            if active_workers:
                health_status["checks"][
                    "celery_workers"
                ] = f"healthy ({len(active_workers)} workers)"
            else:
                health_status["checks"]["celery_workers"] = "no workers available"
                health_status["status"] = "degraded"
        except Exception as e:
            health_status["checks"]["celery_workers"] = f"unhealthy: {str(e)}"
            health_status["status"] = "unhealthy"

        # Check multi-tenant system
        try:
            # Check if system schema exists and functions are available
            tenant_count = len(multi_tenant_manager.list_tenants())
            health_status["checks"][
                "multi_tenant_system"
            ] = f"healthy ({tenant_count} tenants)"
        except Exception as e:
            health_status["checks"]["multi_tenant_system"] = f"unhealthy: {str(e)}"
            health_status["status"] = "unhealthy"

        # Get queue statistics
        try:
            inspect = celery_app.control.inspect()
            reserved_tasks = inspect.reserved()
            active_tasks = inspect.active()

            health_status["queue_stats"] = {
                "reserved_tasks": sum(
                    len(tasks) for tasks in (reserved_tasks or {}).values()
                ),
                "active_tasks": sum(
                    len(tasks) for tasks in (active_tasks or {}).values()
                ),
                "workers": list((active_workers or {}).keys()),
            }
        except:
            health_status["queue_stats"] = {"error": "Unable to fetch queue statistics"}

        if health_status["status"] != "healthy":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return SystemHealthResponse(**health_status)

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get system health: {str(e)}"
        )
        
@health_router.get("/stats")
async def get_system_stats():
    """
    Get system statistics and metrics.

    Returns job counts by status, recent activity, and performance metrics.
    """
    try:
        db_manager = DatabaseManager()

        with db_manager.get_connection() as conn:
            with conn.cursor() as cur:
                # Job counts by status
                cur.execute(
                    """
                    SELECT status, COUNT(*) as count
                    FROM kss.sync_jobs
                    GROUP BY status;
                """
                )
                status_counts = {row[0]: row[1] for row in cur.fetchall()}

                # Job counts by type
                cur.execute(
                    """
                    SELECT job_type, COUNT(*) as count
                    FROM kss.sync_jobs
                    GROUP BY job_type;
                """
                )
                type_counts = {row[0]: row[1] for row in cur.fetchall()}

                # Recent activity (last 24 hours)
                cur.execute(
                    """
                    SELECT COUNT(*) as count
                    FROM kss.sync_jobs
                    WHERE created_at >= %s;
                """,
                    (datetime.now() - timedelta(hours=24),),
                )
                recent_jobs = cur.fetchone()[0]

                # Average execution time for completed jobs
                cur.execute(
                    """
                    SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_duration
                    FROM kss.sync_jobs
                    WHERE status = 'success' AND started_at IS NOT NULL AND completed_at IS NOT NULL;
                """
                )
                avg_duration = cur.fetchone()[0]

                return {
                    "job_counts_by_status": status_counts,
                    "job_counts_by_type": type_counts,
                    "recent_jobs_24h": recent_jobs,
                    "average_execution_time_seconds": (
                        float(avg_duration) if avg_duration else None
                    ),
                    "timestamp": datetime.now().isoformat(),
                }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get system stats: {str(e)}"
        )