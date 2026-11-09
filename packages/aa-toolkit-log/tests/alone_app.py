"""A small app that CI runs with only the log library installed."""

import contextlib
import io
import json
from importlib.metadata import distributions

from aa_log import configure_logging, get_logger

installed = sorted(dist.name for dist in distributions())
assert installed == ["aa-toolkit-log"], installed

log = get_logger("small_app")
stderr = io.StringIO()
with contextlib.redirect_stderr(stderr):
    configure_logging()
    log.info("it runs", extra={"code": 200})

line = json.loads(stderr.getvalue())
assert (line["logger"], line["message"], line["code"]) == ("small_app", "it runs", 200)
print("ok")
