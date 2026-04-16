from __future__ import annotations

import hashlib
import hmac
import json
from time import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from services.common.aiops_common.audit import append_audit_event, get_engine, init_audit_db
from services.common.aiops_common.config import Settings, get_settings
from services.common.aiops_common.queue import get_redis_client, publish_stream
from services.common.aiops_common.schemas import (
    ActionType,
    ApprovalDecision,
    AuditEvent,
    Recommendation,
    RunbookRequest,
)

app = FastAPI(title="approval-orchestrator", version="0.1.0")


@app.on_event("startup")
async def startup() -> None:
    app.state.redis = get_redis_client()
    app.state.audit_engine = get_engine()
    await init_audit_db(app.state.audit_engine)


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.redis.close()
    await app.state.audit_engine.dispose()


def get_redis() -> Redis:
    return app.state.redis


def get_audit_engine() -> AsyncEngine:
    return app.state.audit_engine


def _verify_slack_signature(body: bytes, timestamp: str, signature: str, secret: str) -> bool:
    if not secret:
        return True
    if abs(time() - int(timestamp)) > 60 * 5:
        return False
    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(secret.encode(), basestring.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/recommendations")
async def list_recommendations(redis: Redis = Depends(get_redis)) -> list[dict]:
    keys = await redis.keys("recommendation:*")
    records: list[dict] = []
    for key in keys:
        raw = await redis.get(key)
        if raw:
            records.append(json.loads(raw))
    return sorted(records, key=lambda item: item["created_at"], reverse=True)


@app.post("/api/recommendations/{recommendation_id}/decision")
async def decide_recommendation(
    recommendation_id: str,
    decision: ApprovalDecision,
    redis: Redis = Depends(get_redis),
    audit_engine: AsyncEngine = Depends(get_audit_engine),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    key = f"recommendation:{recommendation_id}"
    raw = await redis.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    recommendation = Recommendation.model_validate_json(raw)
    if decision.approved:
        allowed_actions = [
            action for action in recommendation.proposed_actions if action.value in settings.allowed_runbook_set
        ]
        for action in allowed_actions:
            request = RunbookRequest(
                recommendation_id=recommendation_id,
                action=ActionType(action),
                host=recommendation.metadata.get("host", "unknown-host"),
                requested_by=decision.approver,
                parameters={"reason": decision.reason or "approved via api"},
            )
            await publish_stream(redis, "runbooks.requested", request.model_dump(mode="json"))

    await append_audit_event(
        audit_engine,
        AuditEvent(
            event_type="recommendation_decision",
            actor=decision.approver,
            payload=decision.model_dump(mode="json"),
        ),
    )
    return {"status": "recorded"}


@app.post("/slack/actions")
async def slack_actions(
    request: Request,
    x_slack_request_timestamp: str = Header(default="0"),
    x_slack_signature: str = Header(default=""),
    redis: Redis = Depends(get_redis),
    audit_engine: AsyncEngine = Depends(get_audit_engine),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    body = await request.body()
    if not _verify_slack_signature(body, x_slack_request_timestamp, x_slack_signature, settings.slack_signing_secret):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    payload = dict(await request.form())
    data = json.loads(payload.get("payload", "{}"))
    action = data.get("actions", [{}])[0]
    recommendation_id = action.get("value")
    approved = action.get("action_id") == "approve"
    user_name = data.get("user", {}).get("username", "unknown-user")

    decision = ApprovalDecision(
        recommendation_id=recommendation_id,
        approver=user_name,
        approved=approved,
        reason="slack_interactive",
    )
    await decide_recommendation(recommendation_id, decision, redis, audit_engine, settings)
    return {"status": "ok"}
