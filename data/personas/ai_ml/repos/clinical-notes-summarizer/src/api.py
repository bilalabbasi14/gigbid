import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import BartTokenizer, BartForConditionalGeneration
import torch

app = FastAPI(title="Clinical Notes Summarizer")

class NoteRequest(BaseModel):
    note: str

class SummaryResponse(BaseModel):
    summary: str

MODEL_PATH = os.getenv("MODEL_PATH", "/opt/model")

# Load once at startup
tokenizer = BartTokenizer.from_pretrained(MODEL_PATH)
model = BartForConditionalGeneration.from_pretrained(MODEL_PATH)
model.eval()
if torch.cuda.is_available():
    model.to("cuda")

@app.post("/summarize", response_model=SummaryResponse)
async def summarize(req: NoteRequest):
    inputs = tokenizer(req.note, return_tensors="pt", max_length=1024, truncation=True)
    if torch.cuda.is_available():
        inputs = {k: v.to("cuda") for k, v in inputs.items()}
    try:
        summary_ids = model.generate(
            **inputs,
            max_length=150,
            num_beams=4,
            early_stopping=True,
        )
        summary = tokenizer.decode(summary_ids[0], skip_special_tokens=True)
        return SummaryResponse(summary=summary)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
