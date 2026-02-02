FROM python:3.11-slim

# 安装 Node.js 及必要工具
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm curl procps wget unzip netcat-openbsd \
 && rm -rf /var/lib/apt/lists/*

# 安装 Xray 客户端（用于访问 HuggingFace）
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then ARCH="64"; \
    elif [ "$ARCH" = "aarch64" ]; then ARCH="arm64-v8a"; \
    fi && \
    wget -O /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/download/v1.8.24/Xray-linux-${ARCH}.zip && \
    unzip /tmp/xray.zip -d /usr/local/bin/ xray && \
    chmod +x /usr/local/bin/xray && \
    rm /tmp/xray.zip

WORKDIR /app

# 先复制依赖描述文件以利用缓存
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/requirements.txt ./backend/

# 安装前端依赖（使用淘宝镜像源加速）
RUN npm ci --registry=https://registry.npmmirror.com \
 && npm ci --prefix frontend --registry=https://registry.npmmirror.com

# 安装后端依赖（使用清华镜像源加速）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r backend/requirements.txt

# 复制项目源码
COPY . .

# 创建 HuggingFace 缓存目录并复制本地模型
RUN mkdir -p /root/.cache/huggingface/hub/local_model
COPY models/local_model/ /root/.cache/huggingface/hub/local_model/

EXPOSE 3000 5001

# 复制入口脚本
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# 入口点：先启动代理，再启动应用
ENTRYPOINT ["docker-entrypoint.sh"]
