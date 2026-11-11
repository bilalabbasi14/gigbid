import os
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from recommender import get_recommendations

app = FastAPI(title="RAG Product Recommender")

class RecommendRequest(BaseModel):
    user_id: str
    session_events: list[str]

@app.post("/recommend")
async def recommend(req: RecommendRequest):
    try:
        recs = get_recommendations(req.user_id, req.session_events)
        return {"recommendations": recs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
