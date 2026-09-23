"""Chat suitability for installed specialist models.

Vision capability alone does not disqualify a general chat model (Qwen and
Llama can support both). Only known specialist families are excluded here.
Unknown/custom models remain selectable.
"""


def model_purpose(model: str) -> str:
    family = model.lower().rsplit("/", 1)[-1].split(":", 1)[0]
    if family == "moondream" or family.startswith("moondream-"):
        return "vision"
    if family.startswith(("nomic-embed", "mxbai-embed", "snowflake-arctic-embed", "bge-", "embeddinggemma")):
        return "embedding"
    return "chat"
