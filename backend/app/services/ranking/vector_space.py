import math
import re
from collections import Counter

# 向量空间模型实现，计算查询和文档的余弦相似度
# 分词正则，英文下划线数字和汉字
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    # A lightweight tokenizer keeps this project dependency-free on the API side.
    # 轻量分词器，保持项目在API端无外部依赖
    return TOKEN_RE.findall(text.lower())


def cosine_similarity(query: str, document: str) -> float:
    # 计算查询和文档的余弦相似度，作为相关性评分的一部分
    # 这里使用了tockenize函数进行文档和查询的分词处理
    query_tokens = tokenize(query)
    doc_tokens = tokenize(document)
    if not query_tokens or not doc_tokens:
        return 0.0

    # 计算词频TF
    query_tf = Counter(query_tokens)
    doc_tf = Counter(doc_tokens)
    vocabulary = set(query_tf) | set(doc_tf)

    # 构建 TF - TDF 向量
    # 这里使用简化版的 IDF ，即仅基于当前查询-文档对计算，实际应用中可以使用全局文档频率进行更准确的 IDF 计算
    # 实际应该用另一个公式  BM25
    query_vector: list[float] = []
    doc_vector: list[float] = []

    for token in vocabulary:
        # 文档频率 df：这个词在查询和文档中出现的文档数目，这里简化为 1 + 是否在查询中 + 是否在文档中，实际应用中应该基于全局文档频率计算
        df = 1 + int(token in query_tf) + int(token in doc_tf)
        # 逆文档频率 idf：使用简化的 IDF 计算公式，实际应用中应该基于全局文档频率计算
        idf = math.log(3 / df) + 1

        # 构建 TF - TDF 向量
        query_vector.append(query_tf[token] * idf)
        doc_vector.append(doc_tf[token] * idf)

    # 计算余弦相似度
    dot = sum(left * right for left, right in zip(query_vector, doc_vector))
    query_norm = math.sqrt(sum(value * value for value in query_vector))
    doc_norm = math.sqrt(sum(value * value for value in doc_vector))
    if query_norm == 0 or doc_norm == 0:
        return 0.0
    return dot / (query_norm * doc_norm)


