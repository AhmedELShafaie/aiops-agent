from locust import HttpUser, between, task


class IngestUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def ingest(self) -> None:
        self.client.post(
            "/ingest",
            json={
                "source": "prometheus",
                "host": "loadtest-host-1",
                "metric": "cpu_usage",
                "value": 88.4,
                "threshold": 80.0,
                "severity": "warning",
                "tags": {"env": "prod", "team": "sre"},
            },
            headers={"x-client-id": "load-test"},
        )
