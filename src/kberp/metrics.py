"""In-process HTTP metrics exposed at `/metrics`.

The web server is a small WSGI application, so a lock-protected in-process
aggregate is enough and avoids a second dependency. Multi-worker deployments
should scrape every worker and sum the counters, which Prometheus does.
"""

from __future__ import annotations

import threading

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, int], int] = {}
        self._buckets: dict[str, list[int]] = {}
        self._sum: dict[str, float] = {}
        self._count: dict[str, int] = {}
        self._in_flight = 0

    def start(self) -> None:
        with self._lock:
            self._in_flight += 1

    def finish(self, method: str, endpoint: str, status: int, seconds: float) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            key = (method, endpoint, int(status))
            self._requests[key] = self._requests.get(key, 0) + 1
            counts = self._buckets.setdefault(endpoint, [0] * len(BUCKETS))
            for index, bound in enumerate(BUCKETS):
                if seconds <= bound:
                    counts[index] += 1
            self._sum[endpoint] = self._sum.get(endpoint, 0.0) + seconds
            self._count[endpoint] = self._count.get(endpoint, 0) + 1

    def render(self, gauges: dict[str, float] | None = None) -> str:
        lines = [
            "# HELP kberp_http_requests_total HTTP requests by method, endpoint and status.",
            "# TYPE kberp_http_requests_total counter",
        ]
        with self._lock:
            for (method, endpoint, status), count in sorted(self._requests.items()):
                lines.append(
                    f'kberp_http_requests_total{{method="{_label(method)}",'
                    f'endpoint="{_label(endpoint)}",status="{status}"}} {count}'
                )

            lines += [
                "# HELP kberp_http_request_duration_seconds Request duration by endpoint.",
                "# TYPE kberp_http_request_duration_seconds histogram",
            ]
            for endpoint, counts in sorted(self._buckets.items()):
                for bound, count in zip(BUCKETS, counts, strict=True):
                    lines.append(
                        f'kberp_http_request_duration_seconds_bucket'
                        f'{{endpoint="{_label(endpoint)}",le="{bound}"}} {count}'
                    )
                total = self._count.get(endpoint, 0)
                lines.append(
                    f'kberp_http_request_duration_seconds_bucket'
                    f'{{endpoint="{_label(endpoint)}",le="+Inf"}} {total}'
                )
                lines.append(
                    f'kberp_http_request_duration_seconds_sum'
                    f'{{endpoint="{_label(endpoint)}"}} {self._sum.get(endpoint, 0.0):.6f}'
                )
                lines.append(
                    f'kberp_http_request_duration_seconds_count'
                    f'{{endpoint="{_label(endpoint)}"}} {total}'
                )

            lines += [
                "# HELP kberp_http_requests_in_flight Requests currently being handled.",
                "# TYPE kberp_http_requests_in_flight gauge",
                f"kberp_http_requests_in_flight {self._in_flight}",
            ]

        for name, value in sorted((gauges or {}).items()):
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"
