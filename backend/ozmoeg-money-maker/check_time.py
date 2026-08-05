#!/usr/bin/env python3
from datetime import datetime
from pytz import timezone

now_ny = datetime.now(timezone('America/New_York'))
print(f"Current US ET time: {now_ny.strftime('%Y-%m-%d %H:%M %p %Z')}")
in_hours = 9 <= now_ny.hour < 16
print(f"Market hours (9:30-16:00): {in_hours}")