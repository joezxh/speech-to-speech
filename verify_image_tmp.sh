#!/bin/sh
set -e
ls /app/console/app/main.py /app/console/static/index.html /usr/src/app/src/speech_to_speech/agent/embedded.py >/dev/null && echo "files OK"
test ! -f /app/console/.env && echo "no dev .env OK"
/usr/src/app/.venv/bin/python -c "import torch; print('torch', torch.__version__)"
/usr/src/app/.venv/bin/python -c "import speech_to_speech.agent_integration as a; print('agent flag', a.WITH_FLAG)"
/usr/src/app/.venv/bin/python -c "import speech_to_speech.api.openai_realtime.agent_routes as r; print('agent routes OK')"
