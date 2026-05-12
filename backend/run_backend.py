import os

import uvicorn


if __name__ == "__main__":
    port = int(os.getenv("BACKEND_PORT", "8020"))
    reload = os.getenv("BACKEND_RELOAD", "false").lower() == "true"
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=reload)
