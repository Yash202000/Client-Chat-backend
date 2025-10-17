from transformers import AutoTokenizer, AutoModel
import torch

def get_embeddings(texts: list[str], model_name: str = "nvidia/llama-3.2-nemoretriever-1b-vlm-embed-v1"):
    """
    Generates embeddings for a list of texts using the specified NVIDIA model.
    """
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)

    inputs = tokenizer(texts, padding=True, truncation=True, return_tensors="pt")
    
    with torch.no_grad():
        embeddings = model(**inputs).last_hidden_state.mean(dim=1)
        
    return embeddings.cpu().numpy()
