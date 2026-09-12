import asyncio
import logging

from app.worker.runner import main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

if __name__ == "__main__":
    asyncio.run(main())
