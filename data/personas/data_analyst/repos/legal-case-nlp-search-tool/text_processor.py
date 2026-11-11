import nltk
import pandas as pd
import re
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from sklearn.feature_extraction.text import TfidfVectorizer

nltk.download('stopwords', quiet=True)

# Custom legal stopwords
LEGAL_STOPWORDS = set(stopwords.words('english')) | {
    'herein', 'whereas', 'pursuant', 'aforementioned', 
    'hereinafter', 'thereto', 'thereof', 'hereby',
    'shall', 'may', 'does', 'did', 'will'
}

class LegalTextProcessor:
    def __init__(self):
        self.lemmatizer = WordNetLemmatizer()
        self.vectorizer = TfidfVectorizer(
            stop_words=LEGAL_STOPWORDS,
            max_features=5000,
            ngram_range=(1, 2),
            min_df=2
        )
        self.is_fitted = False

    def clean_text(self, text):
        if pd.isna(text):
            return ""
        text = str(text).lower()
        text = re.sub(r'[^a-z\s]', '', text)
        words = text.split()
        words = [self.lemmatizer.lemmatize(w) for w in words if w not in LEGAL_STOPWORDS]
        return ' '.join(words)

    def fit_transform(self, df, text_column='summary'):
        cleaned_texts = df[text_column].apply(self.clean_text)
        tfidf_matrix = self.vectorizer.fit_transform(cleaned_texts)
        self.is_fitted = True
        return tfidf_matrix

    def transform(self, df, text_column='summary'):
        if not self.is_fitted:
            raise ValueError("Vectorizer must be fitted before transformation")
        cleaned_texts = df[text_column].apply(self.clean_text)
        tfidf_matrix = self.vectorizer.transform(cleaned_texts)
        return tfidf_matrix

    def get_feature_names(self):
        if self.is_fitted:
            return self.vectorizer.get_feature_names_out()
        return []
