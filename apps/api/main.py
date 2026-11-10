from fastapi import FastAPI

app = FastAPI(title="GigBid Student API", version="0.1.0")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "gigbid-api"}

# TODO: Add typed routers, auth, jobs, proposals, approvals, messages, runs and analytics.
# TODO: Add SSE or WebSocket streaming from LangGraph.
