"""Platform-side services that manage the speech-to-speech deployment.

Deliberately separate from `speech_to_speech` (the upstream runtime): everything
here may be rewritten without touching the pipeline it manages. The only module
that imports the runtime package is `validator`, and only for `load_config` /
`validate_config` / `resolve_config`.
"""
