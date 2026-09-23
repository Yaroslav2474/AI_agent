import asyncio
import sys
from src.init_db import initialize_bookings

if __name__ == "__main__":
    force = "--force" in sys.argv or "-f" in sys.argv
    asyncio.run(initialize_bookings(force_reload=force))
