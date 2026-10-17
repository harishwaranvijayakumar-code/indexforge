
# IndexForge Load Test

## Objective

Measure baseline response time, throughput, and HTTP failure rate for
the IndexForge search and health endpoints under a small local workload.

## Workload

- Tool: Locust 2.46.7
- Target: `http://127.0.0.1:8000`
- Duration: 60 seconds
- Maximum concurrent users: 5
- Ramp-up: 1 user per second
- User wait time: 1 to 2 seconds
- Search-to-health task weighting: 8:2
- Operations: read-only GET requests

## Command

```powershell
python -m locust -f locustfile.py --headless -H http://127.0.0.1:8000 -u 5 -r 1 -t 60s --stop-timeout 5 --csv indexforge-load
```

## Measurements

Record total requests, HTTP failures, throughput, average latency,
median latency, p95 latency, and the maximum observed latency.

## Limitations

This is a small local baseline, not a production capacity test.
Results depend on the local machine, development server, database,
OpenSearch state, and dataset size.

The test does not establish behavior under large workloads, sustained
traffic, distributed workers, or infrastructure outages.
