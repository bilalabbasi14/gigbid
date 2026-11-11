from transformers import pipeline
from retriever import retrieve
import os

# Load a fine‑tuned risk classification model (placeholder name)
qa_pipe = pipeline('text-generation', model='priyaran/bert-risk-finetuned', tokenizer='priyaran/bert-risk-finetuned', max_new_tokens=150)

PROMPT_TEMPLATE = (
    "You are a legal assistant. Using the following retrieved clauses, answer the user's question. "
    "Cite clause IDs in brackets.\n\n"
    "Clauses:\n{clauses}\n\nQuestion: {question}\nAnswer:"
)

def answer_question(question: str, top_k: int = 5):
    retrieved = retrieve(question, k=top_k)
    clause_str = "\n".join([f"[{cid}] {text}" for cid, text in retrieved])
    prompt = PROMPT_TEMPLATE.format(clauses=clause_str, question=question)
    result = qa_pipe(prompt, do_sample=False)[0]['generated_text']
    # Strip the prompt part
    answer = result.split('Answer:')[-1].strip()
    return {"answer": answer, "citations": [cid for cid, _ in retrieved]}

if __name__ == '__main__':
    q = "Which clauses expose the client to indemnity risk?"
    print(answer_question(q))
