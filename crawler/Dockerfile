# 确保爬虫服务也能在内网丝滑构建
#  修正后的正确代码
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.11-slim

WORKDIR /crawler

COPY requirements.txt /crawler/requirements.txt
RUN pip install --no-cache-dir -r /crawler/requirements.txt

COPY app /crawler/app

CMD ["python", "-m", "app.run"]

