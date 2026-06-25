from collections import defaultdict

# PageRank 算法核心实现，使用幂迭代法计算网页的权威性得分
def compute_pagerank(
    adjacency: dict[str, list[str]],
    damping: float = 0.85,# 阻尼因子，通常设置为0.85，表示用户有85%的概率继续点击链接，15%的概率随机跳转
    iterations: int = 30,# 迭代次数
) -> dict[str, float]:
    # Sparse power iteration is enough for a 100k-scale course project.
    nodes = list(adjacency.keys())
    if not nodes:
        return {}

    initial = 1.0 / len(nodes)
    scores = {node: initial for node in nodes}
    inbound = defaultdict(list)
    out_degree = {node: max(len(links), 1) for node, links in adjacency.items()}

    for source, targets in adjacency.items():
        for target in targets:
            if target in adjacency:
                inbound[target].append(source)

    for _ in range(iterations):
        next_scores: dict[str, float] = {}
        for node in nodes:
            linked_score = sum(scores[parent] / out_degree[parent] for parent in inbound[node])
            next_scores[node] = (1 - damping) / len(nodes) + damping * linked_score
        scores = next_scores

    return scores

