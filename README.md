# NK 小灵通

基于 `Elasticsearch + FastAPI + Tika + Docker` 的南开大学站内搜索课程项目骨架，覆盖以下核心要求：

- 多站点礼貌抓取，遵循 `robots.txt`
- 网页正文、锚文本、附件全文联合索引
- 支持普通查询、文档查询、短语查询、通配查询
- PageRank + 个性化权重混合排序
- 登录注册、查询日志、网页快照、推荐、查询纠错

## 目录结构

```text
.
|-- backend/                 # 查询服务与页面
|-- crawler/                 # 礼貌爬虫与清洗管道
|-- data/
|   |-- raw/                 # 原始抓取记录
|   |-- clean/               # 清洗后的 JSONL 记录
|   `-- snapshots/           # 网页快照与附件原件
|-- docs/                    # 方案说明
|-- infra/elasticsearch/     # 安装中文分词插件的 ES 镜像
|-- scripts/                 # Windows 启动脚本
`-- docker-compose.yml
```

## 快速启动

1. 复制环境变量文件

```powershell
Copy-Item .env.example .env
```

2. 启动基础服务

```powershell
docker compose up --build
```

3. 重建索引

如果你之前已经建过索引，先用重建脚本删除旧索引并创建新映射。自动补全现在包含：

- 中文前缀自动补全
- 拼音全拼自动补全，例如 `rengong zhineng`
- 拼音简拼自动补全，例如 `rgzn`

```powershell
docker compose exec api python -m app.services.indexing.rebuild_index
```

4. 启动爬虫

```powershell
docker compose --profile crawler up crawler
```

5. 导入清洗结果

```powershell
docker compose exec api python -m app.services.indexing.bulk_loader
docker compose exec api python -m app.services.indexing.update_pagerank
```

如果你已经爬完数据，不需要再次启动爬虫，直接执行“重建索引 + 导入清洗结果”即可。

6. 打开页面

- 搜索首页: `http://localhost:8080`
- Kibana: `http://localhost:5601`

## 抓取建议

- 请在校内网络中运行爬虫，降低跨网访问波动。
- 每个子域名都应单独检查 `robots.txt`，本框架会自动读取并缓存。
- `CRAWL_CONCURRENCY` 建议先从 `8~12` 开始，不要一开始就拉高。
- 抓取目标不少于 `100000` 条时，优先抓取“新闻列表页/通知列表页/学院公告页/附件下载页/历年归档页”。

更具体的抓取与索引说明见：

- [docs/crawl_strategy.md](/d:/IR/docs/crawl_strategy.md)
- [docs/architecture.md](/d:/IR/docs/architecture.md)
