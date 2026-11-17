@echo off
cd /d d:\work\qwen-audio-agent\speech-to-speech-src\console\frontend
npx vitest run 2>&1 | findstr "Test Files Tests FAIL"
