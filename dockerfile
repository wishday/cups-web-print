FROM ubuntu:22.04

# 避免交互式安装提示
ENV DEBIAN_FRONTEND=noninteractive

# 1. 安装所有运行时依赖（包括 CUPS、LibreOffice、中文字体、Java 等）
RUN apt-get update && apt-get install -y --no-install-recommends \
    cups \
    cups-client \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    poppler-utils \
    pdftk \
    python3-pip \
    # 中文字体（思源黑体 + 文泉驿备选）
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    # Java 运行时（LibreOffice 某些转换需要）
    openjdk-11-jre-headless \
    # 系统语言环境工具
    locales \
    && rm -rf /var/lib/apt/lists/*

# 2. 配置中文语言环境（避免 locale 警告，并让 LibreOffice 识别中文）
RUN locale-gen zh_CN.UTF-8 && \
    update-locale LANG=zh_CN.UTF-8

ENV LANG=zh_CN.UTF-8 \
    LANGUAGE=zh_CN:zh \
    LC_ALL=zh_CN.UTF-8

# 3. 刷新字体缓存（让系统立即识别新字体）
RUN fc-cache -fv

# 4. 安装 Python 依赖（只有 Flask 和 Werkzeug，无需编译）
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# 5. 复制项目源代码
COPY . .

# 6. 暴露端口 FLASK服务和CUPS，声明cups持久化路径
EXPOSE 5000
EXPOSE 631
VOLUME ["/etc/cups"]
VOLUME ["/var/spool/cups"]


# 7. 启动服务：先启动 CUPS，再运行 Flask 应用
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]
