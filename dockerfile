# 第一阶段：构建阶段，用于安装系统依赖和Python包
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    cups \
    cups-client \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    poppler-utils \
    pdftk \
    python3-pip \
    python3-setuptools \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip3 install --no-cache-dir -r requirements.txt

# 第二阶段：运行阶段
FROM ubuntu:22.04

# 只安装 cups 服务（确保启动脚本完整）
RUN apt-get update && apt-get install -y --no-install-recommends cups cups-client \
    && rm -rf /var/lib/apt/lists/*

# 其他所有软件（libreoffice, pdftk, python 包等）从 builder 复制
COPY --from=builder /usr/lib /usr/lib
COPY --from=builder /usr/bin /usr/bin
COPY --from=builder /usr/share /usr/share
# Ubuntu 22.04 默认 Python 3.10，路径固定。若未来升级基础镜像，需同步修改此路径。
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages 
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

WORKDIR /app
EXPOSE 5000

CMD service cups start && python3 app.py
