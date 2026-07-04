#!/bin/bash
# Kill zombie processes before starting the bot
kill $(pgrep -f "ffmpeg.*hide_banner.*robbo_bot" 2>/dev/null) 2>/dev/null
kill $(pgrep -x "audacious" 2>/dev/null) 2>/dev/null
if [ -f obibok.pid ]; then
  kill $(cat obibok.pid) 2>/dev/null || true
fi
exit 0
