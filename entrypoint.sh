#!/bin/bash
set -e  # 遇到错误立即退出

# 启动 CUPS（前台模式，放后台）
/usr/sbin/cupsd -f &
CUPS_PID=$!

# 启动 Python 应用（放后台）
python3 /app/app.py &
APP_PID=$!

# 定义一个清理函数
cleanup() {
    echo "Shutting down services..."
    kill $CUPS_PID $APP_PID 2>/dev/null
    exit 0
}

# 捕获 SIGTERM 信号，优雅关闭
trap cleanup SIGTERM SIGINT

# 等待任意子进程退出
wait -n

# 如果到这里说明某个进程退出了，执行清理
cleanup
