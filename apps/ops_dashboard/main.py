from __future__ import annotations

import json
from collections import Counter

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncEngine

from services.common.aiops_common.audit import AuditEventRecord, get_engine, init_audit_db

app = FastAPI(title="ops-dashboard", version="0.1.0")


@app.on_event("startup")
async def startup() -> None:
    app.state.engine = get_engine()
    await init_audit_db(app.state.engine)


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.engine.dispose()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    engine: AsyncEngine = app.state.engine
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(AuditEventRecord).order_by(desc(AuditEventRecord.created_at)).limit(400)
            )
        ).scalars()
        items = list(rows)

    counts = Counter(item.event_type for item in items)
    rec_approved = 0
    rec_rejected = 0
    for item in items:
        if item.event_type != "recommendation_decision":
            continue
        payload = json.loads(item.payload_json)
        if payload.get("approved"):
            rec_approved += 1
        else:
            rec_rejected += 1

    list_html = "".join(
        [f"<li><b>{event_type}</b>: {value}</li>" for event_type, value in counts.most_common()]
    )

    return f"""
    <html>
      <head>
        <title>AIOps Dashboard</title>
        <style>
          body {{ font-family: sans-serif; margin: 40px; max-width: 900px; }}
          .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
        </style>
      </head>
      <body>
        <h1>AIOps Operational Summary</h1>
        <div class="card">
          <h2>Approval Metrics</h2>
          <p>Approved: {rec_approved}</p>
          <p>Rejected: {rec_rejected}</p>
        </div>
        <div class="card">
          <h2>Event Type Counts</h2>
          <ul>{list_html}</ul>
        </div>
      </body>
    </html>
    """
