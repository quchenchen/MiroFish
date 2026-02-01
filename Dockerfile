FROM python:3.11-slim

# 安装 Node.js （满足 >=18）及必要工具（使用清华镜像源加速）
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm curl procps \
 && rm -rf /var/lib/apt/lists/*

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

EXPOSE 3000 5001

# 同时启动前后端（开发模式）
CMD ["npm", "run", "dev"]
