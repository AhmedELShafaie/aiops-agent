from __future__ import annotations

import asyncio

from services.common.aiops_common.audit import append_audit_event, get_engine, init_audit_db
from services.common.aiops_common.config import get_settings
from services.common.aiops_common.queue import consume_stream, get_redis_client, publish_stream
from services.common.aiops_common.schemas import AuditEvent, RunbookRequest, RunbookResult


async def execute_runbook(request: RunbookRequest) -> RunbookResult:
    await asyncio.sleep(0.2)
    action = request.action.value
    if action == "restart_service":
        output = f"Restarted service on {request.host}"
    elif action == "clear_tmp":
        output = f"Cleared temporary files on {request.host}"
    elif action == "restart_agent":
        output = f"Restarted monitoring agent on {request.host}"
    else:
        return RunbookResult(
            execution_id=request.execution_id,
            success=False,
            output=f"Unsupported action {action}",
        )
    return RunbookResult(execution_id=request.execution_id, success=True, output=output)


async def main() -> None:
    settings = get_settings()
    redis = get_redis_client()
    audit_engine = get_engine()
    await init_audit_db(audit_engine)
    last_id = "0-0"

    try:
        while True:
            last_id, events = await consume_stream(redis, "runbooks.requested", last_id=last_id)
            for event in events:
                request = RunbookRequest.model_validate(event)
                if request.action.value not in settings.allowed_runbook_set:
                    await append_audit_event(
                        audit_engine,
                        AuditEvent(
                            event_type="runbook_blocked",
                            actor="runbook-executor",
                            payload={"execution_id": request.execution_id, "action": request.action.value},
                        ),
                    )
                    continue

                result = await execute_runbook(request)
                await publish_stream(redis, "runbooks.completed", result.model_dump(mode="json"))
                await append_audit_event(
                    audit_engine,
                    AuditEvent(
                        event_type="runbook_executed",
                        actor="runbook-executor",
                        payload={
                            "execution_id": result.execution_id,
                            "success": result.success,
                            "output": result.output,
                        },
                    ),
                )
            await asyncio.sleep(0.1)
    finally:
        await redis.close()
        await audit_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
