"""
Flipkart PlayStation Stock Monitor Bot Launcher
Entrypoint that runs main.py
"""
import asyncio
from main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
