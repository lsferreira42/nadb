# Structured Logging

NADB configures component loggers and performance loggers through `LoggingConfig`.

```python
from logging_config import LoggingConfig

logger = LoggingConfig.get_logger("application")
perf = LoggingConfig.get_performance_logger("storage")
```

Structured log output includes timestamp, level, logger, module, function, line, thread ID, operation, duration, and selected metrics.

Sensitive fields are redacted when logged through structured extras:

- `key`
- `value`
- `data`
- `password`
- `secret`
- `token`

Prefer `key_hash` in application logs when a stable identifier is useful without exposing raw keys.

When `enable_otel=True`, NADB attempts to create optional OpenTelemetry spans if `opentelemetry-api` is installed. Operation counters are always available through `get_otel_metrics()`.
