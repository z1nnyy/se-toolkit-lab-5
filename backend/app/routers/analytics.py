"""Router for analytics endpoints.

Each endpoint performs SQL aggregation queries on the interaction data
populated by the ETL pipeline. All endpoints require a `lab` query
parameter to filter results by lab (e.g., "lab-01").
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Numeric, case, cast, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models.interaction import InteractionLog
from app.models.item import ItemRecord
from app.models.learner import Learner

router = APIRouter()

SCORE_BUCKETS = ["0-25", "26-50", "51-75", "76-100"]


def _lab_title_pattern(lab: str) -> str:
    """Convert a lab id like 'lab-04' to a title fragment like 'Lab 04'."""
    prefix, separator, suffix = lab.partition("-")
    if prefix == "lab" and separator and suffix:
        return f"Lab {suffix}"
    return lab


async def _get_lab_id(session: AsyncSession, lab: str) -> int | None:
    """Find the lab item id matching the requested lab identifier."""
    return (
        await session.exec(
            select(ItemRecord.id).where(
                ItemRecord.type == "lab",
                ItemRecord.title.contains(_lab_title_pattern(lab)),
            )
        )
    ).first()


async def _get_task_ids(session: AsyncSession, lab: str) -> list[int]:
    """Find task ids that belong to the selected lab."""
    lab_id = await _get_lab_id(session, lab)
    if lab_id is None:
        return []
    task_ids = await session.exec(
        select(ItemRecord.id).where(
            ItemRecord.type == "task",
            ItemRecord.parent_id == lab_id,
        )
    )
    return list(task_ids)


@router.get("/scores")
async def get_scores(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Score distribution histogram for a given lab."""
    task_ids = await _get_task_ids(session, lab)
    if not task_ids:
        return [{"bucket": bucket, "count": 0} for bucket in SCORE_BUCKETS]

    bucket_expr = case(
        (InteractionLog.score <= 25, "0-25"),
        ((InteractionLog.score > 25) & (InteractionLog.score <= 50), "26-50"),
        ((InteractionLog.score > 50) & (InteractionLog.score <= 75), "51-75"),
        else_="76-100",
    )
    rows = await session.exec(
        select(bucket_expr.label("bucket"), func.count().label("count"))
        .where(
            InteractionLog.item_id.in_(task_ids),
            InteractionLog.score.is_not(None),
        )
        .group_by(bucket_expr)
    )
    counts = {row.bucket: row.count for row in rows}
    return [
        {"bucket": bucket, "count": counts.get(bucket, 0)}
        for bucket in SCORE_BUCKETS
    ]


@router.get("/pass-rates")
async def get_pass_rates(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Per-task pass rates for a given lab."""
    lab_id = await _get_lab_id(session, lab)
    if lab_id is None:
        return []

    avg_score = func.round(cast(func.avg(InteractionLog.score), Numeric(10, 2)), 1)
    rows = await session.exec(
        select(
            ItemRecord.title.label("task"),
            avg_score.label("avg_score"),
            func.count(InteractionLog.id).label("attempts"),
        )
        .join(InteractionLog, InteractionLog.item_id == ItemRecord.id)
        .where(
            ItemRecord.type == "task",
            ItemRecord.parent_id == lab_id,
        )
        .group_by(ItemRecord.id, ItemRecord.title)
        .order_by(ItemRecord.title)
    )
    return [
        {
            "task": row.task,
            "avg_score": float(row.avg_score) if row.avg_score is not None else 0.0,
            "attempts": row.attempts,
        }
        for row in rows
    ]


@router.get("/timeline")
async def get_timeline(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Submissions per day for a given lab."""
    task_ids = await _get_task_ids(session, lab)
    if not task_ids:
        return []

    date_expr = func.date(InteractionLog.created_at)
    rows = await session.exec(
        select(
            date_expr.label("date"),
            func.count(InteractionLog.id).label("submissions"),
        )
        .where(InteractionLog.item_id.in_(task_ids))
        .group_by(date_expr)
        .order_by(date_expr)
    )
    return [{"date": str(row.date), "submissions": row.submissions} for row in rows]


@router.get("/groups")
async def get_groups(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Per-group performance for a given lab."""
    task_ids = await _get_task_ids(session, lab)
    if not task_ids:
        return []

    avg_score = func.round(cast(func.avg(InteractionLog.score), Numeric(10, 2)), 1)
    rows = await session.exec(
        select(
            Learner.student_group.label("group"),
            avg_score.label("avg_score"),
            func.count(func.distinct(InteractionLog.learner_id)).label("students"),
        )
        .join(InteractionLog, InteractionLog.learner_id == Learner.id)
        .where(InteractionLog.item_id.in_(task_ids))
        .group_by(Learner.student_group)
        .order_by(Learner.student_group)
    )
    return [
        {
            "group": row.group,
            "avg_score": float(row.avg_score) if row.avg_score is not None else 0.0,
            "students": row.students,
        }
        for row in rows
    ]
