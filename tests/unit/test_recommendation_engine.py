from services.common.aiops_common.schemas import Incident, Severity
from services.recommendation_engine.worker import generate_recommendation


def test_cpu_incident_returns_restart_agent_action() -> None:
    incident = Incident(
        fingerprint="f1",
        host="srv-a",
        metric="cpu_saturation",
        severity=Severity.critical,
        context={"latest_value": 95},
    )
    recommendation = generate_recommendation(incident)
    assert recommendation.confidence >= 0.7
    assert recommendation.proposed_actions[0].value == "restart_agent"
