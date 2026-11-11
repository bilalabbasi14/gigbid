import os
import torch
from sentence_transformers import SentenceTransformer

# Load model once (cached)
_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_MODEL = SentenceTransformer(_MODEL_NAME)

def embed_text(text: str):
    """Return a normalized 384‑dim embedding for the given text."""
    vec = MODEL.encode(text, normalize_embeddings=True)
    return torch.tensor(vec, dtype=torch.float32)
