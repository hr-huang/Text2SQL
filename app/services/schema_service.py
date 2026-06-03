# app/services/schema_service.py

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


class SchemaService:
    def __init__(self):
        self.catalog_path = (
            Path(__file__).resolve().parent.parent.parent / "data" / "schema_catalog.json"
        )
        self.catalog = self._load_catalog()

        # 初始化 embedding 客户端，和 LLM 共用同一套 API key 和 base_url
        # embedding: 本地 Ollama bge-m3（1024 维，多语言）
        self._rag_threshold = int(os.getenv("RAG_THRESHOLD", "15"))
        self._chroma_path = "./chroma_data"
        if len(self.catalog["tables"]) > self._rag_threshold:
            try:
                from openai import OpenAI
                self._emb_client = OpenAI(
                    api_key="ollama",
                    base_url="http://localhost:11434/v1",
                    timeout=60.0,
                )
                self._embedding_model = "bge-m3"
                # hash 检查：schema 没变就跳过 embedding 重建
                current_hash = self._compute_schema_hash()
                stored_hash = self._get_stored_hash()
                if current_hash and current_hash == stored_hash:
                    self._load_index()
                else:
                    self._build_index()
                    if current_hash:
                        self._save_schema_hash(current_hash)
                self._embedding_available = True
            except Exception:
                self._embedding_available = False
        else:
            self._embedding_available = False

    # ── Schema Hash 缓存（避免重启重复 embedding）──────────────

    def _compute_schema_hash(self) -> str | None:
        """计算 schema + embedding 模型的联合 SHA256。模型名变了也会触发重建。"""
        try:
            raw = self.catalog_path.read_bytes()
            # 把 embedding 模型名也纳入 hash，换模型自动重建
            raw += self._embedding_model.encode()
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

    def _load_index(self):
        """直接打开已有 ChromaDB collection，不重建向量"""
        import chromadb
        self._chroma = chromadb.PersistentClient(path=self._chroma_path)
        try:
            self._table_coll = self._chroma.get_collection("schema_tables")
            self._col_coll = self._chroma.get_collection("schema_columns")
        except Exception:
            # collection 不存在（比如 chroma_data 被清过），fallback 重建
            self._build_index()

    # ── 现有方法，不动 ──────────────────────────────────────────

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

    # ── 新增：向量检索相关 ──────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        """Ollama bge-m3 转向量（1024维，多语言）"""
        resp = self._emb_client.embeddings.create(
            model=self._embedding_model,
            input=text,
        )
        return resp.data[0].embedding

    @staticmethod
    def _cosine_sim(a: list[float], b: list[float]) -> float:
        """余弦相似度。两个向量方向越接近，值越接近 1.0"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = (sum(x * x for x in a)) ** 0.5
        norm_b = (sum(x * x for x in b)) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _build_index(self):
        """启动时执行一次：用 ChromaDB 存储表和字段的向量索引"""
        import chromadb
        self._chroma = chromadb.PersistentClient(path=self._chroma_path)

        # ① 收集所有文本 + 元数据
        table_texts, table_ids, table_metas = [], [], []
        col_texts, col_ids, col_metas = [], [], []

        for table in self.catalog["tables"]:
            col_names = [c["column_name"] for c in table["columns"]]

            # 表级文本
            text_samples = ""
            num_info_parts = []
            for col in table["columns"]:
                samples = col.get("sample_values", [])
                if not samples: continue
                if any(isinstance(v, str) for v in samples) and not text_samples:
                    text_samples = ", ".join(str(v) for v in samples[:5])
                nums = [v for v in samples if isinstance(v, (int, float))]
                if nums:
                    num_info_parts.append(f"{col['column_name']}值如{min(nums)}~{max(nums)}")
            parts = [f"表 {table['table_name']}: 字段 {', '.join(col_names)}."]
            if text_samples: parts.append(f"示例: {text_samples}.")
            if num_info_parts: parts.append("; ".join(num_info_parts[:3]))
            table_texts.append(" ".join(parts))
            table_ids.append(f"t_{table['table_name']}")
            table_metas.append({"table_name": table["table_name"]})

            # 字段级文本
            for col in table["columns"]:
                samples = col.get("sample_values", [])
                sample_str = ", ".join(str(v) for v in samples[:3]) if samples else "无"
                col_texts.append(
                    f"字段 {table['table_name']}.{col['column_name']}: "
                    f"类型 {col.get('type', '')}. 样本值: {sample_str}."
                )
                col_ids.append(f"c_{table['table_name']}_{col['column_name']}")
                col_metas.append({"table_name": table["table_name"], "column_name": col["column_name"]})

        # ② 批量转向量 → 存入 ChromaDB
        all_texts = table_texts + col_texts
        all_vectors = []
        for start in range(0, len(all_texts), 50):
            resp = self._emb_client.embeddings.create(model=self._embedding_model, input=all_texts[start:start+50])
            all_vectors.extend(d.embedding for d in resp.data)

        # 表级 collection（先删再建，确保 schema 变了不会用旧索引）
        try: self._chroma.delete_collection("schema_tables")
        except: pass
        self._table_coll = self._chroma.create_collection("schema_tables")
        self._table_coll.add(ids=table_ids, embeddings=all_vectors[:len(table_texts)], metadatas=table_metas)

        # 字段级 collection
        try: self._chroma.delete_collection("schema_columns")
        except: pass
        self._col_coll = self._chroma.create_collection("schema_columns")
        self._col_coll.add(ids=col_ids, embeddings=all_vectors[len(table_texts):], metadatas=col_metas)

    # ── 改造的核心方法 ──────────────────────────────────────────

    @staticmethod
    def _keyword_score(text: str, question: str) -> float:
        """关键词匹配打分（embedding 不可用时的降级方案）"""
        # 把文本和问题都拆成词
        q_words = set(question.lower().split())
        t_words = set(text.lower().replace(".", " ").replace(":", " ").replace(",", " ").split())
        if not q_words:
            return 0.0
        overlap = q_words & t_words
        return len(overlap) / len(q_words)

    def search_relevant_schema(
        self,
        datasource_id: str,
        question: str,
        metrics: list[str] | None = None,
        dimensions: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        RAG 检索：根据用户问题，只返回相关的表和字段。

        如果 embedding 不可用，或者表很少（≤5 张），直接全量返回。
        """
        # 兜底：表≤15 张不做 RAG（召回率比 token 节省更重要），embedding 不可用不做 RAG
        if not self._embedding_available or len(self.catalog["tables"]) <= self._rag_threshold:
            return self.build_all_candidate_schema(datasource_id)

        # 验证数据源
        if self.catalog["datasource_id"] != datasource_id:
            raise ValueError(
                f"未知数据源：{datasource_id}，当前数据源是 {self.catalog['datasource_id']}"
            )

        try:
            # ① 打分（ChromaDB 向量检索 或 关键词降级）
            _use_chroma = self._embedding_available and hasattr(self, '_table_coll')
            if _use_chroma:
                question_vec = self._embed(question)
                # ChromaDB 表级检索
                table_results = self._table_coll.query(query_embeddings=[question_vec], n_results=15)
                top_table_names = {m["table_name"] for m in table_results["metadatas"][0]}
                # ChromaDB 字段级检索（入选表字段全保留 + 额外高分字段）
                col_results = self._col_coll.query(query_embeddings=[question_vec], n_results=60)
                top_col_keys: set[tuple[str, str]] = set()
                for meta in col_results["metadatas"][0]:
                    if meta["table_name"] in top_table_names:
                        top_col_keys.add((meta["table_name"], meta["column_name"]))
                # 再从非入选表补高分字段
                for meta in col_results["metadatas"][0]:
                    if len(top_col_keys) >= 60: break
                    if meta["table_name"] not in top_table_names:
                        top_col_keys.add((meta["table_name"], meta["column_name"]))
            else:
                # 关键词降级
                for table in self.catalog["tables"]:
                    col_text = " ".join(f"{c['column_name']} " + " ".join(str(v) for v in c.get("sample_values", [])[:3]) for c in table["columns"])
                    table["_score"] = self._keyword_score(table["table_name"] + " " + col_text, question)
                sorted_list = sorted(self.catalog["tables"], key=lambda t: t["_score"], reverse=True)
                top_table_names = {t["table_name"] for t in sorted_list[:12]}
                top_col_keys = set()
                for table in self.catalog["tables"]:
                    if table["table_name"] in top_table_names:
                        for col in table["columns"]:
                            top_col_keys.add((table["table_name"], col["column_name"]))

            # ④ 按原格式组装返回
            candidate_tables = []
            candidate_columns = []

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
                    if key not in top_col_keys:
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

            # ⑤ 关系只保留「两张表都在候选集里」的
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

        except Exception:
            # embedding API 调用失败 → 降级为全量返回
            return self.build_all_candidate_schema(datasource_id)
