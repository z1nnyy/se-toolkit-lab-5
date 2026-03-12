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


def _auth() -> httpx.BasicAuth:
    return httpx.BasicAuth(settings.autochecker_email, settings.autochecker_password)


# ---------------------------------------------------------------------------
# Extract — fetch data from the autochecker API
# ---------------------------------------------------------------------------


async def fetch_items() -> list[dict]:
    """Fetch the lab/task catalog from the autochecker API."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{settings.autochecker_api_url}/api/items", auth=_auth()
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_logs(since: datetime | None = None) -> list[dict]:
    """Fetch check results from the autochecker API with pagination."""
    all_logs: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            params: dict = {"limit": 500}
            if since is not None:
                params["since"] = since.isoformat()
            resp = await client.get(
                f"{settings.autochecker_api_url}/api/logs",
                params=params,
                auth=_auth(),
            )
            resp.raise_for_status()
            data = resp.json()
            logs = data["logs"]
            all_logs.extend(logs)
            if not data["has_more"] or not logs:
                break
            since = datetime.fromisoformat(logs[-1]["submitted_at"])
    return all_logs


# ---------------------------------------------------------------------------
# Load — insert fetched data into the local database
# ---------------------------------------------------------------------------


async def load_items(items: list[dict], session: AsyncSession) -> int:
    """Load items (labs and tasks) into the database. Returns count of new rows."""
    created = 0
    lab_map: dict[str, ItemRecord] = {}

    for item in items:
        if item["type"] != "lab":
            continue
        lab_short_id = item["lab"]
        lab_title = item["title"]
        existing = (
            await session.exec(
                select(ItemRecord).where(
                    ItemRecord.type == "lab", ItemRecord.title == lab_title
                )
            )
        ).first()
        if existing:
            lab_map[lab_short_id] = existing
        else:
            new_lab = ItemRecord(type="lab", title=lab_title)
            session.add(new_lab)
            await session.flush()
            lab_map[lab_short_id] = new_lab
            created += 1

    for item in items:
        if item["type"] != "task":
            continue
        parent = lab_map.get(item["lab"])
        if parent is None:
            continue
        task_title = item["title"]
        existing = (
            await session.exec(
                select(ItemRecord).where(
                    ItemRecord.type == "task",
                    ItemRecord.title == task_title,
                    ItemRecord.parent_id == parent.id,
                )
            )
        ).first()
        if not existing:
            session.add(ItemRecord(type="task", title=task_title, parent_id=parent.id))
            created += 1

    await session.commit()
    return created


async def load_logs(
    logs: list[dict], items_catalog: list[dict], session: AsyncSession
) -> int:
    """Load interaction logs into the database. Returns count of new rows.

    Uses items_catalog to map API short IDs (lab, task) to item titles in the DB.
    Creates learners on the fly (find-or-create by external_id).
    Skips logs whose external_id already exists (idempotent upsert).
    """
    title_lookup: dict[tuple[str, str | None], str] = {}
    for cat in items_catalog:
        title_lookup[(cat["lab"], cat.get("task"))] = cat["title"]

    learner_cache: dict[str, Learner] = {}
    created = 0

    for log in logs:
        # --- learner (find-or-create) ---
        sid = log["student_id"]
        learner = learner_cache.get(sid)
        if learner is None:
            learner = (
                await session.exec(select(Learner).where(Learner.external_id == sid))
            ).first()
            if learner is None:
                learner = Learner(external_id=sid, student_group=log.get("group", ""))
                session.add(learner)
                await session.flush()
            learner_cache[sid] = learner

        # --- item lookup ---
        title = title_lookup.get((log["lab"], log.get("task")))
        if title is None:
            continue
        item_record = (
            await session.exec(select(ItemRecord).where(ItemRecord.title == title))
        ).first()
        if item_record is None:
            continue

        # --- idempotent upsert ---
        log_ext_id = log["id"]
        exists = (
            await session.exec(
                select(InteractionLog.id).where(
                    InteractionLog.external_id == log_ext_id
                )
            )
        ).first()
        if exists is not None:
            continue

        session.add(
            InteractionLog(
                external_id=log_ext_id,
                learner_id=learner.id,
                item_id=item_record.id,
                kind="attempt",
                score=log.get("score"),
                checks_passed=log.get("passed"),
                checks_total=log.get("total"),
                created_at=datetime.fromisoformat(log["submitted_at"]),
            )
        )
        created += 1

    await session.commit()
    return created


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def sync(session: AsyncSession) -> dict:
    """Run the full ETL pipeline and return a summary."""
    items_catalog = await fetch_items()
    await load_items(items_catalog, session)

    last_ts = (await session.exec(select(func.max(InteractionLog.created_at)))).first()

    logs = await fetch_logs(since=last_ts)
    new_records = await load_logs(logs, items_catalog, session)

    total_records = (
        await session.exec(select(func.count(InteractionLog.id)))
    ).first() or 0

    return {"new_records": new_records, "total_records": total_records}
