import os
import json
import torch
from pathlib import Path
from transformers import BartTokenizer, BartForConditionalGeneration, Trainer, TrainingArguments
import mlflow
import mlflow.pytorch

# Load data – assume S3 sync has placed a JSONL file locally
DATA_PATH = Path(os.getenv("DATA_PATH", "./data/train.jsonl"))

def load_dataset(path):
    notes, summaries = [], []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            notes.append(obj["note"])
            summaries.append(obj["summary"])
    return notes, summaries

notes, summaries = load_dataset(DATA_PATH)

tokenizer = BartTokenizer.from_pretrained("facebook/bart-large")
model = BartForConditionalGeneration.from_pretrained("facebook/bart-large")

class SummarizationDataset(torch.utils.data.Dataset):
    def __init__(self, src_texts, tgt_texts, tokenizer, max_len=512):
        self.input_ids = []
        self.attention_masks = []
        self.labels = []
        for src, tgt in zip(src_texts, tgt_texts):
            enc = tokenizer(src, truncation=True, max_length=max_len, return_tensors="pt")
            dec = tokenizer(tgt, truncation=True, max_length=max_len, return_tensors="pt")
            self.input_ids.append(enc.input_ids.squeeze())
            self.attention_masks.append(enc.attention_mask.squeeze())
            self.labels.append(dec.input_ids.squeeze())
    def __len__(self):
        return len(self.input_ids)
    def __getitem__(self, idx):
        return {
            "input_ids": self.input_ids[idx],
            "attention_mask": self.attention_masks[idx],
            "labels": self.labels[idx],
        }

dataset = SummarizationDataset(notes, summaries, tokenizer)

training_args = TrainingArguments(
    output_dir="./model",
    num_train_epochs=3,
    per_device_train_batch_size=4,
    learning_rate=5e-5,
    weight_decay=0.01,
    logging_steps=50,
    report_to=["mlflow"],
    push_to_hub=False,
)

mlflow.start_run(run_name="bart-clinical-summarizer")
mlflow.log_params({"epochs": 3, "batch_size": 4, "lr": 5e-5})
trainer = Trainer(model=model, args=training_args, train_dataset=dataset)
trainer.train()
mlflow.pytorch.log_model(trainer.model, "model")
mlflow.end_run()
