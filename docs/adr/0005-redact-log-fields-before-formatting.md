# Logs are redacted field by field, before formatting

The log library redacts each field (the message with its arguments filled in, the traceback and every extra) before the formatter builds the line, and never the finished line. Trying the finished line showed why: `password=\S+` also consumed the closing quote and produced invalid JSON, a password inside JSON text was missed because its quotes were escaped, and text and JSON output needed different rules for the same field.

## Consequences

The log library accepts a plain function, so it never imports the redaction library (ADR 0001) and only an app connects the two. If that function fails, the log library writes `[REDACTION FAILED]` in place of the content, so the app keeps running and raw text never gets out.

Redaction runs in a handler filter that passes on a redacted copy of the record. Redacting in the formatter is too late: when a log call's arguments don't fit its message, `logging` prints the raw message and arguments to stderr. The filter must catch every error, because one raised there reaches the app.
