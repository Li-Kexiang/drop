FROM python:3.10-slim

# 安装 perf、bpftrace 及相关依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    linux-perf \
    bpftrace \
    linux-headers-amd64 \
    curl \
    git \
    ca-certificates \
    kmod \
    && rm -rf /var/lib/apt/lists/* \
    && if [ ! -f /usr/bin/perf ]; then \
         PERF=$(ls /usr/bin/perf* 2>/dev/null | head -1); \
         [ -n "$PERF" ] && ln -s "$PERF" /usr/bin/perf; \
       fi \
    && echo "perf: $(which perf 2>/dev/null || echo NOT FOUND)" \
    && echo "bpftrace: $(which bpftrace 2>/dev/null || echo NOT FOUND)"

# FlameGraph 工具
RUN git clone --depth=1 https://github.com/brendangregg/FlameGraph.git /opt/FlameGraph \
    && ln -s /opt/FlameGraph/flamegraph.pl /usr/local/bin/flamegraph.pl \
    && ln -s /opt/FlameGraph/stackcollapse-perf.pl /usr/local/bin/stackcollapse-perf.pl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

COPY . .

CMD ["echo", "Drop container ready"]
