import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import numpy as np

class CaseOutcomePredictor:
    def __init__(self):
        self.model = LogisticRegression(max_iter=1000, random_state=42)
        self.is_trained = False

    def prepare_features(self, tfidf_matrix, metadata_df):
        # Combine TF-IDF features with metadata numeric features
        numeric_cols = ['court_level_encoded', 'filing_year']
        numeric_data = metadata_df[numeric_cols].values
        combined = np.hstack([tfidf_matrix.toarray(), numeric_data])
        return combined

    def train(self, features, labels):
        X_train, X_test, y_train, y_test = train_test_split(
            features, labels, test_size=0.2, random_state=42, stratify=labels
        )
        self.model.fit(X_train, y_train)
        
        # Evaluation on test set
        y_pred = self.model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        report = classification_report(y_test, y_pred)
        
        self.is_trained = True
        return {'accuracy': accuracy, 'report': report}

    def predict_outcome(self, features):
        if not self.is_trained:
            raise ValueError("Model must be trained before prediction")
        probabilities = self.model.predict_proba(features)
        predictions = self.model.predict(features)
        return predictions, probabilities

class SimilarityRecommender:
    def __init__(self):
        pass

    def find_similar_cases(self, query_vector, corpus_vectors, top_k=5):
        if len(corpus_vectors) == 0:
            return []
        similarities = cosine_similarity(query_vector, corpus_vectors)
        similarity_scores = similarities[0]
        
        # Get top k indices
        top_indices = np.argsort(similarity_scores)[::-1][:top_k]
        return list(top_indices)
