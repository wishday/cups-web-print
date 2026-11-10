FROM ubuntu:22.04

# 避免交互式安装提示
ENV DEBIAN_FRONTEND=noninteractive

# 安装所有运行时依赖（包括 CUPS、LibreOffice、中文字体、Java 等）
RUN apt-get update && apt-get install -y --no-install-recommends \
    cups \
    cups-client \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    poppler-utils \
    pdftk-java \
    python3-pip \
    # 中文字体（思源黑体 + 文泉驿备选）
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    # Java 运行时（LibreOffice 某些转换需要）
    openjdk-11-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# 刷新字体缓存（让系统立即识别新字体）
RUN fc-cache -fv

# ========== 备份默认 CUPS 配置 ==========
RUN cp -r /etc/cups /etc/cups-default

# 安装 Python 依赖（Flask、gunicorn、img2pdf 及其依赖，均有预编译 wheel，无需本地编译）
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# 复制项目源代码
COPY . .

# 暴露端口 FLASK服务和CUPS，声明cups持久化路径
EXPOSE 5000
EXPOSE 631
VOLUME ["/etc/cups"]
VOLUME ["/var/spool/cups"]
VOLUME ["/var/log/cups"]
VOLUME ["/app/uploads"]
VOLUME ["/app/previews"]

# 启动服务：先启动 CUPS，再运行 Web 应用
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 健康检查：Web 服务可响应且 CUPS 守护进程可用
# 使用 python3 而非 curl，避免额外安装依赖；start-period 覆盖 CUPS 启动等待
# /healthz 返回 200 时退出 0；返回 503 或连接失败时 urlopen 抛异常，退出码非 0
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=4)"

CMD ["/entrypoint.sh"]