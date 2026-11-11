import os
import json
import psycopg2
import numpy as np
from langchain.llms import OpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from embed import embed_text

# Database connection (read from env)
DB_CONN = psycopg2.connect(
    host=os.getenv("PGHOST", "localhost"),
    port=int(os.getenv("PGPORT", 5432)),
    dbname=os.getenv("PGDATABASE", "ecom"),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD", "secret"),
)

LLM = OpenAI(model_name="gpt-3.5-turbo", temperature=0.7)

PROMPT = PromptTemplate(
    template="""You are a helpful e‑commerce assistant. Based on the following product candidates and the user's recent activity, suggest the top 5 products with a short marketing line (max 20 words each).\n\nUser activity: {activity}\n\nProducts:\n{products}\n\nAnswer in JSON list format.""",
    input_variables=["activity", "products"],
)

chain = RetrievalQA.from_chain_type(
    llm=LLM,
    chain_type="stuff",
    prompt=PROMPT,
    return_source_documents=False,
)

def fetch_similar_products(query_vec, top_k=5):
    cur = DB_CONN.cursor()
    sql = """
        SELECT id, title, description, embedding
        FROM products
        ORDER BY embedding <=> %s
        LIMIT %s;
    """
    cur.execute(sql, (query_vec.tolist(), top_k))
    rows = cur.fetchall()
    cur.close()
    return [
        {"id": r[0], "title": r[1], "description": r[2]}
        for r in rows
    ]

def get_recommendations(user_id: str, session_events: list[str]):
    # Simple concatenation of events as context
    context = " ".join(session_events)
    query_vec = embed_text(context)
    candidates = fetch_similar_products(query_vec)
    product_str = "\n".join([f"- {p['title']}: {p['description']}" for p in candidates])
    result = chain.run({"activity": context, "products": product_str})
    # Expecting JSON list from LLM
    try:
        recs = json.loads(result)
    except json.JSONDecodeError:
        recs = [{"title": p["title"], "copy": p["description"]} for p in candidates]
    return recs
