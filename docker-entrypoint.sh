#!/bin/bash
# Docker 入口脚本 - 启动代理和应用

# VLESS 代理配置（从环境变量读取）
VLESS_UUID=${VLESS_UUID:-"c95f88a7-da3a-481b-8cd1-6dd6e1c03a58"}
VLESS_SERVER=${VLESS_SERVER:-"text.coziai.cn"}
VLESS_PORT=${VLESS_PORT:-"58794"}
VLESS_PBK=${VLESS_PBK:-"x47JvY65CWmQesQuCW1udHKHQOA3cIEsmh0rNuEIn1c"}
VLESS_SNI=${VLESS_SNI:-"yahoo.com"}
VLESS_SID=${VLESS_SID:-"baf5c3"}
VLESS_SPX=${VLESS_SPX:-"/"}

# 创建 Xray 配置
cat > /tmp/xray-config.json <<EOFX
{
  "inbounds": [{
    "listen": "127.0.0.1",
    "port": 20808,
    "protocol": "socks",
    "settings": {
      "auth": "noauth",
      "udp": true
    }
  }],
  "outbounds": [{
    "protocol": "vless",
    "settings": {
      "vnext": [{
        "address": "$VLESS_SERVER",
        "port": $VLESS_PORT,
        "users": [{
          "id": "$VLESS_UUID",
          "encryption": "none",
          "flow": "xtls-rprx-vision"
        }]
      }]
    },
    "streamSettings": {
      "network": "tcp",
      "security": "reality",
      "realitySettings": {
        "publicKey": "$VLESS_PBK",
        "shortId": "$VLESS_SID",
        "serverName": "$VLESS_SNI",
        "fingerprint": "chrome"
      },
      "tcpSettings": {
        "header": {
          "type": "none"
        }
      }
    }
  }]
}
EOFX

# 启动 Xray 代理（后台运行）
echo "Starting Xray proxy..."
/usr/local/bin/xray run -c /tmp/xray-config.json &
XRAY_PID=$!

# 等待代理启动
sleep 3

# 设置代理环境变量
export http_proxy=http://127.0.0.1:20808
export https_proxy=http://127.0.0.1:20808
export HTTP_PROXY=http://127.0.0.1:20808
export HTTPS_PROXY=http://127.0.0.1:20808
export no_proxy=localhost,127.0.0.1,neo4j,qdrant,dashscope.aliyuncs.com,aliyuncs.com

echo "Proxy configured. Starting application..."

# 清理函数
cleanup() {
    echo "Stopping Xray..."
    kill $XRAY_PID 2>/dev/null
}

# 注册清理
trap cleanup EXIT TERM INT

# 启动应用
exec npm run dev
