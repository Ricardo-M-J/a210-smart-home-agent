#!/bin/sh

EVENT_JSON="$1"
LOG_FILE="${AGENT_BUTLER_LOG:-./agent_butler_events.log}"

printf '%s\n' "$EVENT_JSON"
printf '%s\n' "$EVENT_JSON" >> "$LOG_FILE"

# Replace this file with real integrations such as TTS, SMTP, SIP phone,
# MQTT, or HomeAssistant calls. Keep the JSON argument as the stable boundary.
