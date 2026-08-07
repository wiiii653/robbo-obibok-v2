#!/bin/bash
# Kill only this service's old ffmpeg and bot processes before startup.
kill $(pgrep -f "ffmpeg.*hide_banner.*robbo_bot" 2>/dev/null) 2>/dev/null
if [ -f obibok.pid ]; then
  kill $(cat obibok.pid) 2>/dev/null || true
fi
exit 0
