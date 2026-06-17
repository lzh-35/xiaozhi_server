"""
RAG 知识库管理器 (基于 LangChain)

功能:
- 加载 knowledge_base 目录下的文档（txt/md）
- 使用阿里 DashScope text-embedding-v4 做文本向量化
- 使用 Chroma 做向量存储和相似度检索
- 支持增量更新（文档变更后自动重建索引）

依赖:
    pip install langchain langchain-community langchain-chroma langchain-text-splitters chromadb

启动时自动初始化，作为全局单例供 RAG 插件使用。
"""

import os
import hashlib
import threading
from typing import Optional, List

from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

# ───────────────────── 全局单例 ─────────────────────
_rag_manager: Optional["RAGManager"] = None
_rag_lock = threading.Lock()


def get_rag_manager(config: dict = None) -> Optional["RAGManager"]:
    """获取 RAG Manager 全局单例

    首次调用时自动从配置文件加载并初始化。
    后续调用可省略 config 参数（已缓存在单例中）。
    """
    global _rag_manager
    if _rag_manager is not None:
        return _rag_manager

    with _rag_lock:
        # 双重检查：拿到锁后再确认一次
        if _rag_manager is not None:
            return _rag_manager

        # 未传 config 时自动加载
        if config is None:
            try:
                from config.config_loader import load_config
                config = load_config()
            except Exception as e:
                logger.bind(tag=TAG).error(f"无法加载配置: {e}")
                return None

        rag_config = config.get("rag", {})
        if rag_config.get("knowledge_dir") and rag_config.get("dashscope_api_key"):
            try:
                _rag_manager = RAGManager(config)
                logger.bind(tag=TAG).info("RAG Manager 初始化成功")
            except Exception as e:
                logger.bind(tag=TAG).error(f"RAG Manager 初始化失败: {e}")
                _rag_manager = None
    return _rag_manager


# ───────────────────── RAG Manager ─────────────────────


class RAGManager:
    """基于 LangChain + Chroma + DashScope 的知识库检索器

    使用方式:
        manager = RAGManager(config)
        docs = manager.search("产品保修期多久")
    """

    def __init__(self, config: dict):
        self.config = config
        rag_config = config.get("rag", {})

        self.knowledge_dir = rag_config.get("knowledge_dir", "data/knowledge_base")
        self.persist_dir = rag_config.get("persist_dir", "data/chroma_db")
        self.chunk_size = int(rag_config.get("chunk_size", 500))
        self.chunk_overlap = int(rag_config.get("chunk_overlap", 50))
        self.top_k = int(rag_config.get("top_k", 3))
        self.api_key = rag_config.get("dashscope_api_key", "")

        # 确保目录存在
        os.makedirs(self.knowledge_dir, exist_ok=True)
        os.makedirs(self.persist_dir, exist_ok=True)

        # 初始化 Embeddings
        self.embeddings = self._init_embeddings()

        # 初始化 / 加载 VectorStore
        self.vectorstore = self._init_vectorstore()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _init_embeddings(self):
        """初始化阿里 DashScope Embeddings"""
        from langchain_community.embeddings import DashScopeEmbeddings

        return DashScopeEmbeddings(
            model="text-embedding-v4",
            dashscope_api_key=self.api_key,
        )

    def _init_vectorstore(self):
        """加载或创建 Chroma 向量库"""
        from langchain_chroma import Chroma

        # 计算文档目录的哈希，用于判断是否需要重建索引
        doc_hash = self._compute_docs_hash()
        hash_file = os.path.join(self.persist_dir, ".docs_hash")

        need_rebuild = True
        if os.path.exists(hash_file) and os.path.exists(
            os.path.join(self.persist_dir, "chroma.sqlite3")
        ):
            with open(hash_file, "r") as f:
                cached_hash = f.read().strip()
            if cached_hash == doc_hash:
                need_rebuild = False
                logger.bind(tag=TAG).info("向量库索引未变化，直接加载")

        if need_rebuild:
            logger.bind(tag=TAG).info("重建向量库索引...")
            documents = self._load_documents()
            if not documents:
                logger.bind(tag=TAG).warning(f"知识库目录为空: {self.knowledge_dir}")
                # 创建一个占位文档，避免 Chroma 空集合报错
                from langchain_core.documents import Document
                documents = [Document(page_content="占位文档", metadata={"source": "_placeholder"})]

            texts = self._split_documents(documents)
            vectorstore = Chroma.from_documents(
                documents=texts,
                embedding=self.embeddings,
                persist_directory=self.persist_dir,
            )

            # 保存文档哈希
            with open(hash_file, "w") as f:
                f.write(doc_hash)

            logger.bind(tag=TAG).info(
                f"向量库索引已重建: {len(texts)} 个文档块"
            )
            return vectorstore
        else:
            return Chroma(
                embedding_function=self.embeddings,
                persist_directory=self.persist_dir,
            )

    # ------------------------------------------------------------------
    # 文档加载
    # ------------------------------------------------------------------

    def _load_documents(self) -> list:
        """加载 knowledge_dir 下所有支持的文档（txt / md / pdf）"""
        from langchain_community.document_loaders import (
            DirectoryLoader,
            TextLoader,
            UnstructuredMarkdownLoader,
            PyPDFLoader,
        )
        import glob

        documents = []

        # 加载 .txt 文件
        txt_loader = DirectoryLoader(
            self.knowledge_dir,
            glob="**/*.txt",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"},
            show_progress=False,
        )
        try:
            documents.extend(txt_loader.load())
        except Exception as e:
            logger.bind(tag=TAG).warning(f"加载 txt 文档失败: {e}")

        # 加载 .md 文件
        try:
            md_loader = DirectoryLoader(
                self.knowledge_dir,
                glob="**/*.md",
                loader_cls=UnstructuredMarkdownLoader,
                show_progress=False,
            )
            documents.extend(md_loader.load())
        except Exception as e:
            logger.bind(tag=TAG).warning(f"加载 md 文档失败: {e}")

        # 加载 .pdf 文件
        try:
            pdf_files = glob.glob(
                os.path.join(self.knowledge_dir, "**", "*.pdf"), recursive=True
            )
            for pdf_path in pdf_files:
                try:
                    loader = PyPDFLoader(pdf_path)
                    docs = loader.load()
                    documents.extend(docs)
                    logger.bind(tag=TAG).debug(
                        f"已加载 PDF: {os.path.basename(pdf_path)} ({len(docs)} 页)"
                    )
                except Exception as e:
                    logger.bind(tag=TAG).warning(
                        f"加载 PDF 失败: {os.path.basename(pdf_path)}: {e}"
                    )
        except Exception as e:
            logger.bind(tag=TAG).warning(f"加载 PDF 文档失败: {e}")

        return documents

    def _split_documents(self, documents: list) -> list:
        """文本分块"""
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        )
        return text_splitter.split_documents(documents)

    # ------------------------------------------------------------------
    # 检索接口
    # ------------------------------------------------------------------

    def search(self, query: str, k: int = None) -> str:
        """
        语义检索相关文档

        Args:
            query: 用户查询文本
            k: 返回文档数（默认使用配置的 top_k）

        Returns:
            拼接后的 context 字符串，未找到时返回空字符串
        """
        if k is None:
            k = self.top_k

        try:
            docs = self.vectorstore.similarity_search(query, k=k)
            if not docs:
                return ""

            parts = []
            for i, doc in enumerate(docs, 1):
                source = doc.metadata.get("source", "未知")
                # 跳过占位文档
                if source == "_placeholder":
                    continue
                # 只取文件名，不要完整路径
                fname = os.path.basename(source)
                parts.append(f"[来源{i}: {fname}]\n{doc.page_content}")

            if not parts:
                return ""

            return "\n\n---\n\n".join(parts)
        except Exception as e:
            logger.bind(tag=TAG).error(f"RAG 检索失败: {e}")
            return ""

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _compute_docs_hash(self) -> str:
        """计算 knowledge_dir 下所有文档的 MD5 哈希"""
        hasher = hashlib.md5()
        if not os.path.exists(self.knowledge_dir):
            return hasher.hexdigest()

        for root, dirs, files in sorted(os.walk(self.knowledge_dir)):
            dirs.sort()
            for fname in sorted(files):
                if fname.startswith("."):
                    continue
                fpath = os.path.join(root, fname)
                hasher.update(fpath.encode())
                try:
                    with open(fpath, "rb") as f:
                        hasher.update(f.read())
                except OSError:
                    pass
        return hasher.hexdigest()

    def reload(self):
        """强制重建向量索引（知识库更新后调用）"""
        hash_file = os.path.join(self.persist_dir, ".docs_hash")
        if os.path.exists(hash_file):
            os.remove(hash_file)
        self.vectorstore = self._init_vectorstore()
        logger.bind(tag=TAG).info("RAG 索引已强制重建")
