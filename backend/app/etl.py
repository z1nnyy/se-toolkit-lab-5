"""ETL pipeline: fetch data from the autochecker API and load it into the database.

The autochecker dashboard API provides two endpoints:
- GET /api/items — lab/task catalog
- GET /api/logs  — anonymized check results (supports ?since= and ?limit= params)

Both require HTTP Basic Auth (email + password from settings).
"""

from datetime import datetime

import httpx
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.interaction import InteractionLog
from app.models.item import ItemRecord
from app.models.learner import Learner
from app.settings import settings


# ---------------------------------------------------------------------------
# Extract — fetch data from the autochecker API
# ---------------------------------------------------------------------------


def _auth() -> httpx.BasicAuth:
    """Build HTTP Basic Auth credentials for the autochecker API."""
    return httpx.BasicAuth(settings.autochecker_email, settings.autochecker_password)


def _parse_submitted_at(value: str) -> datetime:
    """Parse an API timestamp into a naive datetime for database storage."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None)
    return parsed


async def fetch_items() -> list[dict]:
    """Fetch the lab/task catalog from the autochecker API.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{settings.autochecker_api_url}/api/items",
            auth=_auth(),
        )
        response.raise_for_status()
        return response.json()


async def fetch_logs(since: datetime | None = None) -> list[dict]:
    """Fetch check results from the autochecker API.
    """
    logs: list[dict] = []
    next_since = since

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            params: dict[str, int | str] = {"limit": 500}
            if next_since is not None:
                params["since"] = next_since.isoformat()

            response = await client.get(
                f"{settings.autochecker_api_url}/api/logs",
                params=params,
                auth=_auth(),
            )
            response.raise_for_status()

            payload = response.json()
            batch = payload["logs"]
            logs.extend(batch)

            if not payload["has_more"] or not batch:
                return logs

            next_since = _parse_submitted_at(batch[-1]["submitted_at"])


# ---------------------------------------------------------------------------
# Load — insert fetched data into the local database
# ---------------------------------------------------------------------------


async def load_items(items: list[dict], session: AsyncSession) -> int:
    """Load items (labs and tasks) into the database.
    """
    created = 0
    labs_by_short_id: dict[str, ItemRecord] = {}

    for item in items:
        if item["type"] != "lab":
            continue

        existing_lab = (
            await session.exec(
                select(ItemRecord).where(
                    ItemRecord.type == "lab",
                    ItemRecord.title == item["title"],
                )
            )
        ).first()
        if existing_lab is None:
            existing_lab = ItemRecord(type="lab", title=item["title"])
            session.add(existing_lab)
            await session.flush()
            created += 1

        labs_by_short_id[item["lab"]] = existing_lab

    for item in items:
        if item["type"] != "task":
            continue

        parent_lab = labs_by_short_id.get(item["lab"])
        if parent_lab is None:
            continue

        existing_task = (
            await session.exec(
                select(ItemRecord).where(
                    ItemRecord.type == "task",
                    ItemRecord.title == item["title"],
                    ItemRecord.parent_id == parent_lab.id,
                )
            )
        ).first()
        if existing_task is not None:
            continue

        session.add(
            ItemRecord(
                type="task",
                title=item["title"],
                parent_id=parent_lab.id,
            )
        )
        created += 1

    await session.commit()
    return created


async def load_logs(
    logs: list[dict], items_catalog: list[dict], session: AsyncSession
) -> int:
    """Load interaction logs into the database.

    Args:
        logs: Raw log dicts from the API (each has lab, task, student_id, etc.)
        items_catalog: Raw item dicts from fetch_items() — needed to map
            short IDs (e.g. "lab-01", "setup") to item titles stored in the DB.
        session: Database session.

    """
    titles_by_short_ids = {
        (item["lab"], item.get("task")): item["title"] for item in items_catalog
    }
    learner_cache: dict[str, Learner] = {}
    created = 0

    for log in logs:
        learner = learner_cache.get(log["student_id"])
        if learner is None:
            learner = (
                await session.exec(
                    select(Learner).where(
                        Learner.external_id == log["student_id"]
                    )
                )
            ).first()
            if learner is None:
                learner = Learner(
                    external_id=log["student_id"],
                    student_group=log.get("group", ""),
                )
                session.add(learner)
                await session.flush()
            learner_cache[log["student_id"]] = learner

        item_title = titles_by_short_ids.get((log["lab"], log.get("task")))
        if item_title is None:
            continue

        item_record = (
            await session.exec(select(ItemRecord).where(ItemRecord.title == item_title))
        ).first()
        if item_record is None:
            continue

        existing_log_id = (
            await session.exec(
                select(InteractionLog.id).where(
                    InteractionLog.external_id == log["id"]
                )
            )
        ).first()
        if existing_log_id is not None:
            continue

        session.add(
            InteractionLog(
                external_id=log["id"],
                learner_id=learner.id,
                item_id=item_record.id,
                kind="attempt",
                score=log.get("score"),
                checks_passed=log.get("passed"),
                checks_total=log.get("total"),
                created_at=_parse_submitted_at(log["submitted_at"]),
            )
        )
        created += 1

    await session.commit()
    return created


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def sync(session: AsyncSession) -> dict:
    """Run the full ETL pipeline.
    """
    items = await fetch_items()
    await load_items(items, session)

    last_synced_at = (
        await session.exec(select(func.max(InteractionLog.created_at)))
    ).first()
    logs = await fetch_logs(since=last_synced_at)
    new_records = await load_logs(logs, items, session)

    total_records = (
        await session.exec(select(func.count(InteractionLog.id)))
    ).first() or 0
    return {"new_records": new_records, "total_records": total_records}
