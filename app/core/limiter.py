from slowapi import Limiter
from slowapi.util import get_remote_address

# Module-level limiter instance shared by main.py (middleware wiring)
# and endpoint modules (per-route decorators).
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
