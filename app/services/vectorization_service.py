import threading

import numpy as np

# The embedding model is loaded on first use, not at import: importing app.services happens in every
# process (API workers, the telephony voice process), and most of them never compute an embedding.
_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model


def get_embedding(text: str):
    return _get_model().encode(text)

def get_embeddings_batch(texts: list) -> np.ndarray:
    """Encode a list of texts in one shot — much faster than N × get_embedding calls."""
    return _get_model().encode(texts)

def cosine_similarity(v1, v2):
    return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
