# 架构说明

## 1. 数据流

1. `crawler` 从种子站点开始抓取 HTML 和附件链接。
2. 原始网页和附件保存到 `data/snapshots/`，同时把结构化记录写入 `data/raw/`。
3. 清洗后的记录进入 `Elasticsearch`，索引字段包括正文、标题、锚文本、站点、学院、附件类型、快照路径等。
4. 查询服务先用 ES 做候选召回，再结合 `PageRank + 个性化匹配` 重排。
5. 用户的注册信息、查询日志、点击日志写入 `SQLite`，用于历史记录与推荐。

## 2. 为什么选这个组合

- `Elasticsearch`：倒排索引、多字段检索、短语查询、suggest、过滤能力都很合适。
- `Tika`：统一解析 `pdf/doc/docx/xls/xlsx/ppt/pptx` 等附件。
- `FastAPI`：接口清晰，课程项目开发速度快。
- `SQLite`：演示成本低，足够承载登录、日志、推荐画像等元数据。

## 3. 索引域设计

- `title`：网页标题或附件标题
- `content`：正文主文本
- `anchor_texts`：指向该文档的锚文本集合
- `site_name`：所属站点
- `departments`：学院/部门标签
- `audiences`：适用人群，如本科生/研究生/教师
- `doc_kind`：`html/pdf/docx/xlsx/...`
- `pagerank`：离线计算的链接分析分数
- `snapshot_path`：网页快照或附件原件的本地路径

## 4. 排序公式

默认采用两级混合：

```text
content_score = 0.8 * lexical_score + 0.2 * pagerank_score
final_score   = 0.7 * content_score + 0.3 * profile_score
```

- `lexical_score`：由 ES 召回分值和向量空间余弦相似度综合得到
- `pagerank_score`：离线 PageRank 归一化值
- `profile_score`：用户身份、专业、检索需求与文档标签的匹配度

## 5. 课程答辩时可重点展示

- 为什么要把附件抽取也纳入统一索引
- 为什么锚文本能提升召回效果
- 为什么个性化排序不应直接覆盖通用相关性，而是做加权修正
- 为什么网页快照能解决“原网页被改动/删除”的可追溯问题

