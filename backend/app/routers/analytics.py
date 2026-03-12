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


def _lab_title_pattern(lab: str) -> str:
    """Transform lab identifier to title format (e.g. 'lab-04' -> 'Lab 04')."""
    parts = lab.split("-")
    return f"Lab {parts[-1]}" if len(parts) >= 2 else lab


@router.get("/scores")
async def get_scores(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Score distribution histogram for a given lab."""
    pattern = _lab_title_pattern(lab)
    lab_stmt = select(ItemRecord.id).where(
        ItemRecord.type == "lab", ItemRecord.title.contains(pattern)
    )
    lab_result = await session.exec(lab_stmt)
    lab_row = lab_result.first()
    if lab_row is None:
        return [
            {"bucket": "0-25", "count": 0},
            {"bucket": "26-50", "count": 0},
            {"bucket": "51-75", "count": 0},
            {"bucket": "76-100", "count": 0},
        ]
    lab_id = lab_row
    task_ids_stmt = select(ItemRecord.id).where(
        ItemRecord.type == "task", ItemRecord.parent_id == lab_id
    )
    task_ids = [r for r in await session.exec(task_ids_stmt)]
    if not task_ids:
        return [
            {"bucket": "0-25", "count": 0},
            {"bucket": "26-50", "count": 0},
            {"bucket": "51-75", "count": 0},
            {"bucket": "76-100", "count": 0},
        ]
    bucket_expr = case(
        (InteractionLog.score <= 25, "0-25"),
        ((InteractionLog.score > 25) & (InteractionLog.score <= 50), "26-50"),
        ((InteractionLog.score > 50) & (InteractionLog.score <= 75), "51-75"),
        (InteractionLog.score > 75, "76-100"),
    )
    agg_stmt = (
        select(bucket_expr.label("bucket"), func.count().label("count"))
        .where(
            InteractionLog.item_id.in_(task_ids),
            InteractionLog.score.isnot(None),
        )
        .group_by(bucket_expr)
    )
    result = await session.exec(agg_stmt)
    counts = {row.bucket: row.count for row in result}
    return [
        {"bucket": "0-25", "count": counts.get("0-25", 0)},
        {"bucket": "26-50", "count": counts.get("26-50", 0)},
        {"bucket": "51-75", "count": counts.get("51-75", 0)},
        {"bucket": "76-100", "count": counts.get("76-100", 0)},
    ]


@router.get("/pass-rates")
async def get_pass_rates(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Per-task pass rates for a given lab."""
    pattern = _lab_title_pattern(lab)
    lab_stmt = select(ItemRecord.id).where(
        ItemRecord.type == "lab", ItemRecord.title.contains(pattern)
    )
    lab_result = await session.exec(lab_stmt)
    lab_row = lab_result.first()
    if lab_row is None:
        return []
    lab_id = lab_row
    tasks_stmt = select(ItemRecord.id, ItemRecord.title).where(
        ItemRecord.type == "task", ItemRecord.parent_id == lab_id
    ).order_by(ItemRecord.title)
    tasks = [(r.id, r.title) for r in await session.exec(tasks_stmt)]
    if not tasks:
        return []
    result = []
    for task_id, task_title in tasks:
        avg_score = func.round(cast(func.avg(InteractionLog.score), Numeric(10, 2)), 1)
        agg_stmt = select(
            avg_score.label("avg_score"),
            func.count(InteractionLog.id).label("attempts"),
        ).where(InteractionLog.item_id == task_id)
        row = (await session.exec(agg_stmt)).first()
        if row is not None and row.attempts > 0:
            result.append({
                "task": task_title,
                "avg_score": float(row.avg_score) if row.avg_score is not None else 0.0,
                "attempts": row.attempts,
            })
    return result


@router.get("/timeline")
async def get_timeline(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Submissions per day for a given lab."""
    pattern = _lab_title_pattern(lab)
    lab_stmt = select(ItemRecord.id).where(
        ItemRecord.type == "lab", ItemRecord.title.contains(pattern)
    )
    lab_result = await session.exec(lab_stmt)
    lab_row = lab_result.first()
    if lab_row is None:
        return []
    lab_id = lab_row
    task_ids_stmt = select(ItemRecord.id).where(
        ItemRecord.type == "task", ItemRecord.parent_id == lab_id
    )
    task_ids = [r for r in await session.exec(task_ids_stmt)]
    if not task_ids:
        return []
    date_col = func.date(InteractionLog.created_at)
    agg_stmt = (
        select(date_col.label("date"), func.count(InteractionLog.id).label("submissions"))
        .where(InteractionLog.item_id.in_(task_ids))
        .group_by(date_col)
        .order_by(date_col)
    )
    result = await session.exec(agg_stmt)
    return [
        {"date": str(row.date), "submissions": row.submissions}
        for row in result
    ]


@router.get("/groups")
async def get_groups(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Per-group performance for a given lab."""
    pattern = _lab_title_pattern(lab)
    lab_stmt = select(ItemRecord.id).where(
        ItemRecord.type == "lab", ItemRecord.title.contains(pattern)
    )
    lab_result = await session.exec(lab_stmt)
    lab_row = lab_result.first()
    if lab_row is None:
        return []
    lab_id = lab_row
    task_ids_stmt = select(ItemRecord.id).where(
        ItemRecord.type == "task", ItemRecord.parent_id == lab_id
    )
    task_ids = [r for r in await session.exec(task_ids_stmt)]
    if not task_ids:
        return []
    avg_score = func.round(cast(func.avg(InteractionLog.score), Numeric(10, 2)), 1)
    agg_stmt = (
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
    result = await session.exec(agg_stmt)
    return [
        {
            "group": row.group,
            "avg_score": float(row.avg_score) if row.avg_score is not None else 0.0,
            "students": row.students,
        }
        for row in result
    ]