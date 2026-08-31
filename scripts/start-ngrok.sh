#!/usr/bin/env bash
#
# Starts the ngrok tunnel exposing the backend (started by dev-up.sh)
# to the public internet, so Twilio's webhooks can reach it.
#
# Run this in its OWN terminal, alongside dev-up.sh running in another
# — both need to stay running for the duration of a test call.
#
# ngrok's free-tier URL is different every time it (re)starts. After it
# prints a line like:
#   Forwarding  https://xxxx-xx-xx-xx-xx.ngrok-free.app -> http://localhost:8010
# you must, EVERY time that URL changes:
#   1. Update backend/.env: set PUBLIC_BASE_URL to that https:// URL,
#      and PUBLIC_DOMAIN to just its hostname (no scheme). Then
#      restart dev-up.sh (env vars are only read at process startup).
#   2. Paste the same URL + /webhooks/twilio/voice into:
#      Twilio Console -> Phone Numbers -> Manage -> Active Numbers
#      -> your number -> Voice Configuration -> "A call comes in"

set -euo pipefail
ngrok http 8010
