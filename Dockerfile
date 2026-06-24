FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    linux-perf \
    bpftrace \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# FlameGraph 工具
RUN git clone --depth=1 https://github.com/brendangregg/FlameGraph.git /opt/FlameGraph \
    && ln -s /opt/FlameGraph/flamegraph.pl /usr/local/bin/flamegraph.pl \
    && ln -s /opt/FlameGraph/stackcollapse-perf.pl /usr/local/bin/stackcollapse-perf.pl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

COPY . .

# 默认不运行，由 docker-compose 指定 command
CMD ["echo", "Drop container ready"]
