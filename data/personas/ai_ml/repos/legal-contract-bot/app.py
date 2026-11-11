from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from qa_engine import answer_question

app = FastAPI(title='Legal Contract Review Bot')

class Query(BaseModel):
    question: str

@app.post('/query')
async def query_endpoint(payload: Query):
    if not payload.question:
        raise HTTPException(status_code=400, detail='Question cannot be empty')
    result = answer_question(payload.question)
    return result
