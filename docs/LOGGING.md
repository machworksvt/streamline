# Centralized Logging System

## Overview

All logging in Streamline flows through Python's standard `logging` module and is automatically published to the event bus for display in the TUI's `CollapsibleLog` widget.

## Usage in Code

### Basic Logging

```python
from streamline.core.logging import get_logger

logger = get_logger(__name__)

# Simple messages
logger.info("Operation completed")
logger.warning("Configuration may be stale")
logger.error("Failed to load file")
```

### Structured Logging with Context

```python
# Add context data
logger.info(
    "Analysis job queued",
    context={"job_id": "abc123", "analysis": "stability"}
)

# Add hints for troubleshooting
logger.warning(
    "Cache miss for configuration",
    context={"config_id": "baseline"},
    hint="Try invalidating the cache"
)

# Add error codes
logger.error(
    "VSP session unavailable",
    code="VSP_001",
    hint="Ensure OpenVSP is installed"
)
```

### Bound Loggers

```python
# Bind context that persists across log calls
logger = get_logger(__name__).bind(session_id="xyz789")

logger.info("Session started")  # Includes session_id automatically
logger.debug("Processing item", context={"item": 42})  # Merges with session_id
```

### Exception Logging

```python
try:
    risky_operation()
except Exception as exc:
    logger.exception("Operation failed")  # Includes full traceback
```

## TUI Display Features

### Log Level Filtering

```python
# Set minimum level to display (in your app)
self.log_panel.set_min_level("INFO")  # or logging.INFO
```

### Event-Based Logging

The `CollapsibleLog` widget automatically:
- **Colors** log levels (DEBUG=cyan, INFO=green, WARNING=yellow, ERROR=red)
- **Displays context** as structured key=value pairs
- **Shows hints** in italic for troubleshooting
- **Renders tracebacks** for exceptions
- **Filters** by minimum log level

### Example Output

```
[INFO] Analysis job queued | analysis='stability' job_id='abc123'
[WARNING] Cache miss for configuration | config_id='baseline' hint: Try invalidating the cache
[ERROR] VSP session unavailable hint: Ensure OpenVSP is installed
```

## Configuration

### From Code

```python
from streamline.core.logging import setup_logging, LoggingConfig

setup_logging(LoggingConfig(
    level="DEBUG",
    console=True,
    logfile=Path("streamline.log"),
    propagate=True
))
```

### From Environment

```bash
export STREAMLINE_LOG_LEVEL=DEBUG
export STREAMLINE_LOG_FILE=/path/to/streamline.log
python -m streamline.app
```

### From CLI

```bash
python -m streamline.app --debug
python -m streamline.app --log-level=INFO
python -m streamline.app --log-file=debug.log
```

## Architecture

1. **Python logging** → All loggers use standard `logging` module
2. **EventBusLogHandler** → Captures log records and publishes `LogMessageEvent`
3. **Event Bus** → Distributes events to all subscribers
4. **CollapsibleLog** → Receives events and displays formatted output

This ensures:
- ✅ All logs flow through one system
- ✅ No duplicate log configuration
- ✅ Structured data preserved
- ✅ TUI and file output synchronized
- ✅ Thread-safe event delivery
