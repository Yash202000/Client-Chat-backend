from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer('all-MiniLM-L6-v2')

def get_embedding(text: str):
    return model.encode(text)

def get_embeddings_batch(texts: list) -> np.ndarray:
    """Encode a list of texts in one shot — much faster than N × get_embedding calls."""
    return model.encode(texts)

def cosine_similarity(v1, v2):
    return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
