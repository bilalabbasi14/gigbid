import os
import pdfplumber
import psycopg2
from psycopg2.extras import execute_values
from transformers import AutoTokenizer, AutoModel
import torch

# DB connection (environment variables set in Docker)
conn = psycopg2.connect(
    host=os.getenv('POSTGRES_HOST', 'db'),
    dbname=os.getenv('POSTGRES_DB', 'contracts'),
    user=os.getenv('POSTGRES_USER', 'postgres'),
    password=os.getenv('POSTGRES_PASSWORD', 'example')
)

tokenizer = AutoTokenizer.from_pretrained('bert-base-uncased')
model = AutoModel.from_pretrained('bert-base-uncased')
model.eval()


def embed_text(text: str):
    inputs = tokenizer(text, return_tensors='pt', truncation=True, max_length=128)
    with torch.no_grad():
        embeddings = model(**inputs).last_hidden_state[:,0,:]
    return embeddings.squeeze().cpu().numpy().tolist()


def process_contract(pdf_path: str, contract_id: int):
    clauses = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue
            # naive split on line breaks – real code would use NLP clause detection
            for i, clause in enumerate(text.split('\n')):
                clause = clause.strip()
                if clause:
                    clause_id = f"{contract_id}_{page_num}_{i}"
                    embedding = embed_text(clause)
                    clauses.append((clause_id, contract_id, page_num, clause, embedding))
    return clauses


def store_clauses(clauses):
    with conn.cursor() as cur:
        sql = """
        INSERT INTO clauses (clause_id, contract_id, page_number, text, embedding)
        VALUES %s
        ON CONFLICT (clause_id) DO UPDATE SET text = EXCLUDED.text, embedding = EXCLUDED.embedding;
        """
        execute_values(cur, sql, clauses)
    conn.commit()

if __name__ == '__main__':
    # Example ingestion of all PDFs in ./data
    for fname in os.listdir('data'):
        if fname.lower().endswith('.pdf'):
            cid = int(os.path.splitext(fname)[0].replace('contract_', ''))
            path = os.path.join('data', fname)
            clause_rows = process_contract(path, cid)
            store_clauses(clause_rows)
            print(f"Ingested {len(clause_rows)} clauses from {fname}")
