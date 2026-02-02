#!/bin/sh
set -e

# Increase HuggingFace timeout to 120 seconds
export HF_HUB_DOWNLOAD_TIMEOUT=120
export HF_HUB_ENABLE_HF_TRANSFER=0

# Create Xray config
cat > /tmp/xray-build.json << 'JSON'
{"inbounds":[{"listen":"127.0.0.1","port":20808,"protocol":"socks","settings":{"auth":"noauth","udp":true}}],"outbounds":[{"protocol":"vless","settings":{"vnext":[{"address":"text.coziai.cn","port":58794,"users":[{"id":"c95f88a7-da3a-481b-8cd1-6dd6e1c03a58","encryption":"none","flow":"xtls-rprx-vision"}]}]},"streamSettings":{"network":"tcp","security":"reality","realitySettings":{"publicKey":"x47JvY65CWmQesQuCW1udHKHQOA3cIEsmh0rNuEIn1c","shortId":"baf5c3","serverName":"yahoo.com","fingerprint":"chrome"}}}]}
JSON

# Start Xray
/usr/local/bin/xray run -c /tmp/xray-build.json >/var/log/xray.log 2>&1 &
XRAY_PID=$!

# Wait for proxy to be ready
echo "Waiting for Xray proxy to start..."
i=1
while [ $i -le 60 ]; do
    if nc -z 127.0.0.1 20808 2>/dev/null; then
        echo "Xray proxy ready after $i seconds"
        break
    fi
    i=$(expr $i + 1)
    sleep 1
done

# Set proxy with longer timeout
export http_proxy=http://127.0.0.1:20808
export https_proxy=http://127.0.0.1:20808
export REQUESTS_TIMEOUT=120

# Download model
python3 /tmp/download-hf-model.py

# Cleanup
kill $XRAY_PID 2>/dev/null
rm /tmp/xray-build.json /tmp/download-hf-model.py
echo "HuggingFace model cached successfully"
