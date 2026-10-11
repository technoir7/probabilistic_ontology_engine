"""Liveness and scheduler status."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request


logger = logging.getLogger(__name__)
router = APIRouter()



@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    return {"status": "ok"}


@router.get("/runtime")
async def runtime_status(request: Request) -> dict[str, Any]:
    tasks = getattr(request.app.state, "scheduler_tasks", [])
    return {
        "scheduler_enabled": getattr(request.app.state, "scheduler_enabled", False),
        "schedulers": [
            {
                "name": task.get_name(),
                "running": not task.done(),
                "done": task.done(),
                "cancelled": task.cancelled(),
            }
            for task in tasks
        ],
    }
