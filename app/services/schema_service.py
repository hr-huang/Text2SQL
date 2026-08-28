# app/services/schema_service.py
"""Schema retrieval service with multi-stage RAG pipeline.

Pipeline:
    ① Vector recall  — SiliconFlow bge-m3 → ChromaDB ANN
    ② Lexical recall — BM25 (jieba tokenized) on table & column text
    ③ RRF fusion     — Reciprocal Rank Fusion over both recall sources
    ④ Rerank         — SiliconFlow bge-reranker-v2-m3 cross-encoder
    ⑤ Fallback       — any stage failure → degrade to full schema

Caching:
    Schema hash + embedding model name + reranker model name → SHA256.
    If any change, rebuild vector + BM25 indexes from scratch.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()


# ── Helpers ──────────────────────────────────────────────────────


def _rrf_fuse(ranked_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion.

    Each list contributes 1/(k + rank). Higher score = more relevant.
    Returns {item_id: rrf_score}.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _tokenize(text: str) -> list[str]:
    """Tokenize for BM25. Prefer jieba for Chinese; fall back to whitespace."""
    text = text.lower()
    try:
        import jieba
        tokens = [t for t in jieba.lcut(text) if t.strip()]
        if tokens:
            return tokens
    except Exception:
        pass
    return [t for t in text.replace(":", " ").replace(",", " ").replace(".", " ").split() if t]


# ── SchemaService ────────────────────────────────────────────────


class SchemaService:
    def __init__(self):
        self.catalog_path = (
            Path(__file__).resolve().parent.parent.parent / "data" / "schema_catalog.json"
        )
        self.catalog = self._load_catalog()

        # ── Configuration (env-driven) ──
        self._rag_threshold = int(os.getenv("RAG_THRESHOLD", "15"))
        self._hybrid_enabled = os.getenv("RAG_HYBRID_ENABLED", "1") == "1"
        self._rerank_enabled = os.getenv("RAG_RERANK_ENABLED", "1") == "1"

        self._chroma_path = "./chroma_data"
        Path(self._chroma_path).mkdir(parents=True, exist_ok=True)

        # ── SiliconFlow client (single key for embedding + rerank) ──
        self._sf_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
        self._sf_base = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/")
        self._emb_model = os.getenv("SILICONFLOW_EMBEDDING_MODEL", "BAAI/bge-m3")
        self._rerank_model = os.getenv("SILICONFLOW_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
        self._sf_timeout = float(os.getenv("SILICONFLOW_TIMEOUT", "60"))

        # Treat placeholder as not-configured.
        self._sf_configured = bool(self._sf_key) and not self._sf_key.startswith("sk-your_")

        self._embedding_available = (
            self._sf_configured and len(self.catalog["tables"]) > self._rag_threshold
        )

        # Lazy caches populated by _load_index / _build_index.
        self._chroma = None
        self._table_coll = None  # type: ignore[assignment]
        self._col_coll = None  # type: ignore[assignment]
        self._bm25_tables = None  # type: ignore[assignment]
        self._bm25_table_docs: list[str] = []
        self._bm25_table_ids: list[str] = []
        self._bm25_cols = None  # type: ignore[assignment]
        self._bm25_col_docs: list[str] = []
        self._bm25_col_ids: list[str] = []
        self._table_text_cache: dict[str, str] = {}
        self._col_text_cache: dict[str, str] = {}

        if self._embedding_available:
            current_hash = self._compute_schema_hash()
            stored_hash = self._get_stored_hash()
            try:
                if current_hash and current_hash == stored_hash:
                    self._load_index()
                    # _load_index handles its own BM25 persistence via _build_index fallback
                else:
                    self._build_index()
                    self._persist_bm25()
                    if current_hash:
                        self._save_schema_hash(current_hash)
            except Exception as exc:
                # Embedding/rerank 不可用 → 关闭 RAG，回到全量 schema
                print(f"[SchemaService] RAG init failed ({type(exc).__name__}: {exc}); falling back to full schema.")
                self._embedding_available = False
                self._chroma = None
                self._table_coll = None
                self._col_coll = None
                self._bm25_tables = None
                self._bm25_cols = None

    # ══════════════════════════════════════════════════════════════
    # Cache hash
    # ══════════════════════════════════════════════════════════════

    def _compute_schema_hash(self) -> str | None:
        """SHA256 of (catalog bytes + embedding model + reranker model).

        Any change in catalog or model triggers index rebuild.
        """
        try:
            raw = self.catalog_path.read_bytes()
            raw += self._emb_model.encode()
            raw += self._rerank_model.encode()
            return hashlib.sha256(raw).hexdigest()
        except Exception:
            return None

    def _hash_file_path(self) -> Path:
        return Path(self._chroma_path) / ".schema_hash"

    def _get_stored_hash(self) -> str | None:
        try:
            hp = self._hash_file_path()
            if hp.exists():
                return hp.read_text().strip()
        except Exception:
            pass
        return None

    def _save_schema_hash(self, h: str) -> None:
        try:
            hp = self._hash_file_path()
            hp.parent.mkdir(parents=True, exist_ok=True)
            hp.write_text(h)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # Catalog helpers (unchanged behavior)
    # ══════════════════════════════════════════════════════════════

    def _load_catalog(self) -> dict[str, Any]:
        if not self.catalog_path.exists():
            raise FileNotFoundError(
                "找不到 data/schema_catalog.json，请先运行 scripts/build_schema_catalog.py"
            )
        return json.loads(self.catalog_path.read_text(encoding="utf-8"))

    def get_all_schema(self, datasource_id: str) -> dict[str, Any]:
        if self.catalog["datasource_id"] != datasource_id:
            raise ValueError(
                f"未知数据源：{datasource_id}，当前数据源是 {self.catalog['datasource_id']}"
            )
        return self.catalog

    def get_table_schema(
        self, datasource_id: str, table_name: str
    ) -> dict[str, Any]:
        catalog = self.get_all_schema(datasource_id)
        for table in catalog["tables"]:
            if table["table_name"] == table_name:
                return table
        return {
            "table_name": table_name,
            "error": f"没有找到表：{table_name}",
            "columns": [],
        }

    def build_all_candidate_schema(self, datasource_id: str) -> dict[str, Any]:
        """全量返回（保留给 tools 和 repair agent 使用，它们需要完整 schema）"""
        catalog = self.get_all_schema(datasource_id)
        candidate_tables = []
        candidate_columns = []

        for table in catalog["tables"]:
            candidate_tables.append({
                "table_name": table["table_name"],
                "business_name": table.get("business_name", table["table_name"]),
                "description": table.get("description", ""),
                "primary_key": table.get("primary_key"),
            })
            for column in table.get("columns", []):
                candidate_columns.append({
                    "table_name": table["table_name"],
                    "column_name": column["column_name"],
                    "type": column.get("type", ""),
                    "business_name": column.get("business_name", column["column_name"]),
                    "description": column.get("description", ""),
                    "sample_values": column.get("sample_values", []),
                    "is_primary_key": column.get("is_primary_key", False),
                    "is_foreign_key": column.get("is_foreign_key", False),
                    "references": column.get("references"),
                })

        return {
            "candidate_tables": candidate_tables,
            "candidate_columns": candidate_columns,
            "candidate_relationships": catalog.get("relationships", []),
        }

    # ══════════════════════════════════════════════════════════════
    # SiliconFlow embedding & rerank
    # ══════════════════════════════════════════════════════════════

    def _embed(self, text: str) -> list[float]:
        return self._embed_batch([text])[0]

    def _embed_batch(self, texts: list[str], batch: int = 50) -> list[list[float]]:
        if not self._sf_configured:
            raise RuntimeError("SiliconFlow API key not configured")
        from openai import OpenAI
        client = OpenAI(api_key=self._sf_key, base_url=self._sf_base, timeout=self._sf_timeout)
        all_vectors: list[list[float]] = []
        for start in range(0, len(texts), batch):
            resp = client.embeddings.create(model=self._emb_model, input=texts[start:start + batch])
            all_vectors.extend(d.embedding for d in resp.data)
        return all_vectors

    def _rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        """Call SiliconFlow /v1/rerank. Returns [(original_index, score), ...] sorted by score desc.

        On failure or when disabled, returns identity ranking (1/(i+1) score) so downstream
        code can still proceed.
        """
        if not documents:
            return []
        if not (self._sf_configured and self._rerank_enabled):
            return [(i, 1.0 / (i + 1)) for i in range(min(top_n, len(documents)))]
        try:
            payload = {
                "model": self._rerank_model,
                "query": query,
                "documents": documents,
                "top_n": min(top_n, len(documents)),
                "return_documents": False,
            }
            with httpx.Client(timeout=self._sf_timeout) as client:
                resp = client.post(
                    f"{self._sf_base}/rerank",
                    headers={
                        "Authorization": f"Bearer {self._sf_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
            return [(r["index"], float(r["relevance_score"])) for r in data["results"]]
        except Exception:
            return [(i, 1.0 / (i + 1)) for i in range(min(top_n, len(documents)))]

    # ══════════════════════════════════════════════════════════════
    # Index build / load
    # ══════════════════════════════════════════════════════════════

    def _build_texts(self) -> tuple[list[str], list[str], list[str], list[str], list[dict], list[dict]]:
        """Build (table_texts, table_ids, col_texts, col_ids, table_metas).

        Also caches text for later reranking.
        """
        table_texts: list[str] = []
        table_ids: list[str] = []
        table_metas: list[dict] = []
        col_texts: list[str] = []
        col_ids: list[str] = []
        col_metas: list[dict] = []

        for table in self.catalog["tables"]:
            col_names = [c["column_name"] for c in table["columns"]]

            text_samples = ""
            num_info_parts: list[str] = []
            for col in table["columns"]:
                samples = col.get("sample_values", [])
                if not samples:
                    continue
                if any(isinstance(v, str) for v in samples) and not text_samples:
                    text_samples = ", ".join(str(v) for v in samples[:5])
                nums = [v for v in samples if isinstance(v, (int, float))]
                if nums:
                    num_info_parts.append(
                        f"{col['column_name']}值如{min(nums)}~{max(nums)}"
                    )
            parts = [f"表 {table['table_name']}: 字段 {', '.join(col_names)}."]
            if text_samples:
                parts.append(f"示例: {text_samples}.")
            if num_info_parts:
                parts.append("; ".join(num_info_parts[:3]))
            table_text = " ".join(parts)
            table_texts.append(table_text)
            table_ids.append(f"t_{table['table_name']}")
            table_metas.append({"table_name": table["table_name"]})
            self._table_text_cache[table["table_name"]] = table_text

            for col in table["columns"]:
                samples = col.get("sample_values", [])
                sample_str = ", ".join(str(v) for v in samples[:3]) if samples else "无"
                col_text = (
                    f"字段 {table['table_name']}.{col['column_name']}: "
                    f"类型 {col.get('type', '')}. 样本值: {sample_str}."
                )
                col_texts.append(col_text)
                col_ids.append(f"c_{table['table_name']}_{col['column_name']}")
                col_metas.append({
                    "table_name": table["table_name"],
                    "column_name": col["column_name"],
                })
                self._col_text_cache[f"{table['table_name']}.{col['column_name']}"] = col_text

        return table_texts, table_ids, col_texts, col_ids, table_metas, col_metas

    def _build_index(self):
        """Build (or rebuild) ChromaDB vector store + BM25 lexical index."""
        import chromadb
        from rank_bm25 import BM25Okapi

        self._chroma = chromadb.PersistentClient(path=self._chroma_path)

        table_texts, table_ids, col_texts, col_ids, table_metas, col_metas = self._build_texts()

        # ── Vector embeddings (SiliconFlow bge-m3) ──
        all_texts = table_texts + col_texts
        all_vectors = self._embed_batch(all_texts)

        # 表级 collection
        try:
            self._chroma.delete_collection("schema_tables")
        except Exception:
            pass
        self._table_coll = self._chroma.create_collection("schema_tables")
        self._table_coll.add(
            ids=table_ids,
            embeddings=all_vectors[: len(table_texts)],
            metadatas=table_metas,
        )

        # 字段级 collection
        try:
            self._chroma.delete_collection("schema_columns")
        except Exception:
            pass
        self._col_coll = self._chroma.create_collection("schema_columns")
        self._col_coll.add(
            ids=col_ids,
            embeddings=all_vectors[len(table_texts):],
            metadatas=col_metas,
        )

        # ── BM25 lexical index ──
        self._bm25_table_docs = table_texts
        self._bm25_table_ids = table_ids
        self._bm25_tables = BM25Okapi([_tokenize(t) for t in table_texts])

        self._bm25_col_docs = col_texts
        self._bm25_col_ids = col_ids
        self._bm25_cols = BM25Okapi([_tokenize(t) for t in col_texts])

    def _load_index(self):
        """Load ChromaDB collections and BM25 from cache if hash matches."""
        import chromadb

        self._chroma = chromadb.PersistentClient(path=self._chroma_path)
        try:
            self._table_coll = self._chroma.get_collection("schema_tables")
            self._col_coll = self._chroma.get_collection("schema_columns")
        except Exception:
            self._build_index()
            return

        bm25_path = Path(self._chroma_path) / "bm25.pkl"
        if bm25_path.exists():
            try:
                with open(bm25_path, "rb") as f:
                    data = pickle.load(f)
                    self._bm25_table_docs = data["table_docs"]
                    self._bm25_table_ids = data["table_ids"]
                    self._bm25_tables = data["table_obj"]
                    self._bm25_col_docs = data["col_docs"]
                    self._bm25_col_ids = data["col_ids"]
                    self._bm25_cols = data["col_obj"]
            except Exception:
                self._build_index()
                return
        else:
            self._build_index()
            return

        # Rebuild text caches from loaded catalog (texts themselves not persisted,
        # but are deterministic given the catalog).
        for table in self.catalog["tables"]:
            self._table_text_cache[table["table_name"]] = (
                f"表 {table['table_name']}: " + table.get("description", "")
            )
            for col in table.get("columns", []):
                self._col_text_cache[f"{table['table_name']}.{col['column_name']}"] = (
                    f"字段 {table['table_name']}.{col['column_name']}"
                )

    def _persist_bm25(self):
        """Persist BM25 to disk after _build_index."""
        try:
            path = Path(self._chroma_path) / "bm25.pkl"
            with open(path, "wb") as f:
                pickle.dump({
                    "table_docs": self._bm25_table_docs,
                    "table_ids": self._bm25_table_ids,
                    "table_obj": self._bm25_tables,
                    "col_docs": self._bm25_col_docs,
                    "col_ids": self._bm25_col_ids,
                    "col_obj": self._bm25_cols,
                }, f)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # Core RAG: hybrid retrieval + RRF + rerank
    # ══════════════════════════════════════════════════════════════

    def search_relevant_schema(
        self,
        datasource_id: str,
        question: str,
        metrics: list[str] | None = None,
        dimensions: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """RAG: hybrid vector + BM25 → RRF → rerank → schema."""
        # 兜底：未配置 SF 或表过少 → 全量返回
        if not self._embedding_available or len(self.catalog["tables"]) <= self._rag_threshold:
            return self.build_all_candidate_schema(datasource_id)

        if self.catalog["datasource_id"] != datasource_id:
            raise ValueError(
                f"未知数据源：{datasource_id}，当前数据源是 {self.catalog['datasource_id']}"
            )

        try:
            return self._hybrid_search(question)
        except Exception:
            # 任何阶段失败 → 降级到全量
            return self.build_all_candidate_schema(datasource_id)

    def _hybrid_search(self, question: str) -> dict[str, Any]:
        # ── Vector recall (table-level + column-level) ──
        question_vec = self._embed(question)
        table_results = self._table_coll.query(
            query_embeddings=[question_vec], n_results=30
        )
        col_results = self._col_coll.query(
            query_embeddings=[question_vec], n_results=60
        )

        vector_table_ranks = [
            m["table_name"] for m in table_results["metadatas"][0]
        ]
        vector_col_ranks = [
            (m["table_name"], m["column_name"])
            for m in col_results["metadatas"][0]
        ]

        # ── BM25 lexical recall ──
        bm25_table_ranks: list[str] = []
        bm25_col_ranks: list[tuple[str, str]] = []
        if self._hybrid_enabled and self._bm25_tables is not None:
            tokens = _tokenize(question)
            scores = self._bm25_tables.get_scores(tokens)
            bm25_table_ranks = [
                self._bm25_table_ids[i].removeprefix("t_")
                for i in scores.argsort()[::-1]
            ]
        if self._hybrid_enabled and self._bm25_cols is not None:
            tokens = _tokenize(question)
            scores = self._bm25_cols.get_scores(tokens)
            bm25_col_ranks = []
            for i in scores.argsort()[::-1]:
                cid = self._bm25_col_ids[i]
                if cid.startswith("c_"):
                    t, c = cid[2:].split(".", 1)
                    bm25_col_ranks.append((t, c))

        # ── RRF fusion ──
        table_rrf = _rrf_fuse([vector_table_ranks, bm25_table_ranks])
        col_rrf_raw = _rrf_fuse(
            [
                [f"{t}.{c}" for t, c in vector_col_ranks],
                [f"{t}.{c}" for t, c in bm25_col_ranks],
            ]
        )
        col_rrf = {tuple(k.split(".", 1)): v for k, v in col_rrf_raw.items()}

        # ── Rerank top candidates ──
        top_table_candidates = sorted(
            table_rrf.items(), key=lambda x: x[1], reverse=True
        )[:20]
        rerank_in = [self._table_text_cache.get(name, name) for name, _ in top_table_candidates]
        reranked = self._rerank(question, rerank_in, top_n=12)
        top_table_names: set[str] = {
            top_table_candidates[idx][0] for idx, _ in reranked
        }
        if not top_table_names:
            top_table_names = {name for name, _ in top_table_candidates[:10]}

        # 入选表的所有列 + RRF top 60 列（仅入选表）
        selected_cols: set[tuple[str, str]] = set()
        for table in self.catalog["tables"]:
            if table["table_name"] in top_table_names:
                for col in table["columns"]:
                    selected_cols.add((table["table_name"], col["column_name"]))
        for k, _ in sorted(col_rrf.items(), key=lambda x: x[1], reverse=True)[:60]:
            if len(selected_cols) >= 80:
                break
            t, c = k
            if t in top_table_names:
                selected_cols.add((t, c))

        # ── Build response in canonical shape ──
        candidate_tables: list[dict[str, Any]] = []
        candidate_columns: list[dict[str, Any]] = []
        for table in self.catalog["tables"]:
            if table["table_name"] not in top_table_names:
                continue
            candidate_tables.append({
                "table_name": table["table_name"],
                "business_name": table.get("business_name", table["table_name"]),
                "description": table.get("description", ""),
                "primary_key": table.get("primary_key"),
            })
            for column in table.get("columns", []):
                key = (table["table_name"], column["column_name"])
                if key not in selected_cols:
                    continue
                candidate_columns.append({
                    "table_name": table["table_name"],
                    "column_name": column["column_name"],
                    "type": column.get("type", ""),
                    "business_name": column.get("business_name", column["column_name"]),
                    "description": column.get("description", ""),
                    "sample_values": column.get("sample_values", []),
                    "is_primary_key": column.get("is_primary_key", False),
                    "is_foreign_key": column.get("is_foreign_key", False),
                    "references": column.get("references"),
                })

        all_relationships = self.catalog.get("relationships", [])
        filtered_relationships = [
            r for r in all_relationships
            if r["left_table"] in top_table_names
            and r["right_table"] in top_table_names
        ]

        return {
            "candidate_tables": candidate_tables,
            "candidate_columns": candidate_columns,
            "candidate_relationships": filtered_relationships,
        }