# The redaction library is written here, with no third-party dependencies

The toolkit needs to take sensitive values out of logs first, and later out of API responses and AI workflows. We write a small library of Detectors on the standard library instead of adopting an existing one. The thorough engines bring a language-processing stack of about 50 packages and a large model, too heavy to run on every log line. The small logging-focused ones skip tracebacks or let the raw value through when they fail.

## Consequences

Patterns alone cannot find names or street addresses, so redaction reduces exposure and does not guarantee it. An app with other needs adds its own Detector. Logged text can be controlled by an attacker and the standard `re` module has no timeout, so every built-in pattern must stay fast on hostile input.
