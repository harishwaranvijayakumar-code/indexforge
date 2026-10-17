
# Load Test Results

## Run Summary

- Date: 2026-10-17
- Environment: Local Windows development environment
- Tool: Locust 2.46.7
- Duration: 60 seconds
- Maximum concurrent users: 5
- Ramp-up: 1 user per second
- Exit code: 0

## Aggregate Results

| Metric | Observed result |
|---|---:|
| Total requests | 183 |
| Failed requests | 0 |
| Throughput | 3.19 requests/second |
| Average latency | 36 ms |
| Median latency | 31 ms |
| 95th percentile latency | 63 ms |
| Maximum latency | 904 ms |

## Endpoint Results

| Endpoint | Requests | Failures | Average | p95 | Maximum |
|---|---:|---:|---:|---:|---:|
| `/api/search/` | 147 | 0 | 44 ms | 67 ms | 904 ms |
| `/health/` | 36 | 0 | 4 ms | 9 ms | 14 ms |

## Observations

- All 183 requests completed without a recorded HTTP failure.
- Search requests accounted for 147 requests.
- The overall p95 latency was 63 ms.
- One request reached 904 ms. The available output does not establish
  the cause of this outlier.
- The workload was intentionally small and ran against the local
  Django development server.

## Conclusion

The run establishes a useful initial local performance baseline.
It does not demonstrate production capacity or guarantee performance
under higher concurrency.

No performance optimization is justified by this run alone.
Further load testing is deferred unless a concrete performance issue
appears during deployment or smoke testing.
