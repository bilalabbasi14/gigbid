import json
import torch
import torch.nn as nn
import numpy as np
from mlflow import pyfunc
from flask import Flask, request, jsonify

app = Flask(__name__)

# Load the model logged by MLflow (assumes env var MODEL_URI set by SageMaker)
model = pyfunc.load_model(os.getenv('MODEL_URI'))

@app.route('/ping')
def ping():
    return 'pong', 200

@app.route('/invocations', methods=['POST'])
def invocations():
    data = request.get_json(force=True)
    # Expect list of sequences [[t1, t2, ...], ...]
    inputs = torch.tensor(np.array(data['instances']), dtype=torch.float32)
    preds = model.predict(inputs)
    return jsonify({'predictions': preds.tolist()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
