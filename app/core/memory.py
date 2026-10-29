import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from chromadb.api.types import Documents, EmbeddingFunction
from chromadb.utils.embedding_functions import register_embedding_function

from app.core.config import settings

try:
    import chromadb
except ImportError:  # pragma: no cover - exercised only when the extra is missing
    chromadb = None

COLLECTION_NAME = "policy_telemetry_history"
_CLIENTS: Dict[str, Any] = {}


@register_embedding_function
class HashEmbeddingFunction(EmbeddingFunction[Documents]):
    """Local 32-d hash embedder. Avoids the default ONNX model download."""

    def __init__(self) -> None:
        return None

    def __call__(self, input: Documents):
        vectors = []
        for text in input:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vector = np.frombuffer(digest, dtype=np.uint8).astype(np.float32)
            vectors.append((vector + 1.0) / 256.0)
        return vectors

    @staticmethod
    def name() -> str:
        return "dmue_hash"

    @staticmethod
    def build_from_config(config: Dict[str, Any]) -> "HashEmbeddingFunction":
        return HashEmbeddingFunction()

    def get_config(self) -> Dict[str, Any]:
        return {}

    def default_space(self) -> str:
        return "cosine"


def _client(persist_dir: str):
    if chromadb is None:
        raise RuntimeError("chromadb is not installed")
    if persist_dir not in _CLIENTS:
        _CLIENTS[persist_dir] = chromadb.PersistentClient(path=persist_dir)
    return _CLIENTS[persist_dir]


class PolicyMemoryManager:
    def __init__(self, persist_dir: Optional[str] = None):
        path = persist_dir or settings.CHROMA_PERSIST_DIR
        self.persist_dir = path
        self.client = _client(path)
        embedder = HashEmbeddingFunction()
        try:
            self.collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=embedder,
            )
        except Exception:
            try:
                self.client.delete_collection(COLLECTION_NAME)
            except Exception:
                pass
            self.collection = self.client.create_collection(
                name=COLLECTION_NAME,
                embedding_function=embedder,
            )

    def record_underwriting_event(
        self, policy_id: str, risk_score: float, premium: float, reasons: list
    ):
        factor_text = ", ".join(reasons) if reasons else "No extra risk factors were found."
        document = (
            f"Policy {policy_id} scored risk {float(risk_score)} "
            f"with premium ${float(premium):.2f}. Key factors: {factor_text}"
        )
        digest = hashlib.sha256(
            f"{policy_id}|{document}|{uuid.uuid4()}".encode("utf-8")
        ).hexdigest()[:16]
        recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.collection.add(
            documents=[document],
            metadatas=[
                {
                    "policy_id": policy_id,
                    "risk_score": float(risk_score),
                    "premium": float(premium),
                    "recorded_at": recorded_at,
                }
            ],
            ids=[f"{policy_id}_{digest}"],
        )
        return f"{policy_id}_{digest}"

    def get_policy_context(self, policy_id: str, limit: int = 3) -> Dict[str, Any]:
        found = self.collection.get(where={"policy_id": policy_id})
        ids = found.get("ids") or []
        if not ids:
            return {"documents": [], "metadatas": [], "ids": []}

        n_results = min(max(int(limit), 1), len(ids))
        results = self.collection.query(
            query_texts=[f"Historical underwriting and safety risk for policy {policy_id}"],
            n_results=n_results,
            where={"policy_id": policy_id},
        )
        return {
            "documents": (results.get("documents") or [[]])[0],
            "metadatas": (results.get("metadatas") or [[]])[0],
            "ids": (results.get("ids") or [[]])[0],
        }
