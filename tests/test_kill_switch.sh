#!/usr/bin/env bash
# Basic kill switch smoke test. Requires ZeusPrompter to be installed
# (zeus on PATH and ~/.zeus-prompter/core/config.json present).

zeus off
zeus status | grep -q "PAUSED" && echo "PASS: off works" || echo "FAIL: off"
zeus on
zeus status | grep -q "ACTIVE" && echo "PASS: on works" || echo "FAIL: on"
zeus off --tool cursor
zeus status | grep -q "off" && echo "PASS: tool-specific off works" || echo "FAIL: tool-specific"
zeus on --tool cursor
echo "Kill switch tests complete."
