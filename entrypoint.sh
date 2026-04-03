#!/bin/bash
set -e

# 启动 CUPS 服务（后台运行）
/usr/sbin/cupsd -f &
CUPS_PID=$!

# 等待 CUPS 完全就绪（最长等待30秒，使用退出码检查，兼容中英文）
echo "Waiting for CUPS to be ready..."
for i in {1..30}; do
    if lpstat -r >/dev/null 2>&1; then
        echo "CUPS is ready."
        break
    fi
    if [ $i -eq 30 ]; then
        echo "Timeout waiting for CUPS to start." >&2
        # 可选：输出调试信息
        echo "CUPS process status:"
        ps aux | grep cupsd || true
        exit 1
    fi
    sleep 1
done

# 启动 Flask 应用
python3 /app/app.py &
APP_PID=$!

# 定义清理函数（可选）
cleanup() {
    echo "Shutting down..."
    kill $CUPS_PID $APP_PID 2>/dev/null
}
trap cleanup EXIT

# 等待任意一个进程退出
wait -n

# 当任意进程退出时，脚本结束，容器退出
exit $?