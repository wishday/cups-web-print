#!/bin/bash
set -e

# 配置初始化与权限修复
if [ ! -f /etc/cups/cupsd.conf ]; then
    echo "Restoring default CUPS configuration from /etc/cups-default..."
    cp -r /etc/cups-default/* /etc/cups/
fi
chown -R lp:lp /etc/cups /var/spool/cups /var/log/cups

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

# 启动 Web 服务（gunicorn）
# 必须只用 1 个 worker：print_jobs、上传令牌、自动恢复冷却等状态都在进程内存中，
# 多 worker 会导致状态分裂（任务查不到、取消无效、自动恢复互不可见）。
# 并发能力由 --threads 提供。
gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 1 \
    --threads 8 \
    --timeout 300 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile - \
    --chdir /app \
    app:app &
APP_PID=$!

# 清理函数：容器退出时同时停止 CUPS 和 Web 服务
cleanup() {
    echo "Shutting down..."
    kill $CUPS_PID $APP_PID 2>/dev/null
}
trap cleanup EXIT

# 等待任意一个进程退出
wait -n

# 当任意进程退出时，脚本结束，容器退出
exit $?