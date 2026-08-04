#!/usr/bin/env bash
# ============================================================
# 一键部署脚本 — Exam Extract API
# 用法: bash deploy.sh [start|stop|restart]
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$PROJECT_DIR/.server.pid"
PORT=8081

# ---- 颜色 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${CYAN}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ============================================================
# 安装依赖
# ============================================================
setup_deps() {
    log_info "安装依赖..."
    pip install -q -r "$PROJECT_DIR/requirements.txt"
    log_info "依赖就绪 ✓"
}

# ============================================================
# 启动服务
# ============================================================
start_server() {
    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            log_warn "服务已在运行 (pid=$OLD_PID)，跳过启动"
            return
        fi
        rm -f "$PID_FILE"
    fi

    log_info "启动服务 http://0.0.0.0:$PORT ..."
    nohup python -m uvicorn app.main:app \
        --host 0.0.0.0 \
        --port "$PORT" \
        --reload \
        --log-level info \
        &> "$PROJECT_DIR/.server.log" &

    SERVER_PID=$!
    echo "$SERVER_PID" > "$PID_FILE"

    sleep 2
    if kill -0 "$SERVER_PID" 2>/dev/null; then
        log_info "服务启动成功 ✓  pid=$SERVER_PID"
        log_info "  API 文档: http://localhost:$PORT/docs"
        log_info "  健康检查: http://localhost:$PORT/health"
        log_info "  查看日志: tail -f .server.log"
    else
        log_error "服务启动失败，查看日志: cat $PROJECT_DIR/.server.log"
        rm -f "$PID_FILE"
        exit 1
    fi
}

# ============================================================
# 停止服务
# ============================================================
stop_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            log_info "停止服务 (pid=$PID)..."
            kill "$PID"
            sleep 1
            kill -9 "$PID" 2>/dev/null || true
            log_info "服务已停止 ✓"
        fi
        rm -f "$PID_FILE"
    else
        log_info "没有找到运行中的服务"
    fi
}

# ============================================================
# 主流程
# ============================================================
cd "$PROJECT_DIR"

case "${1:-start}" in
    start)
        setup_deps
        start_server
        ;;
    stop)
        stop_server
        ;;
    restart)
        stop_server
        start_server
        ;;
    *)
        echo "用法: bash deploy.sh [start|stop|restart]"
        exit 1
        ;;
esac
