# Remedi 宝塔部署指南

## 架构

```
公网IP:8080 → web 容器（nginx：前端静态页 + 反代 /api）→ api 容器（FastAPI:8000，SQLite 落盘）
```

## 前提

- 阿里云服务器已安装宝塔面板
- 阿里云安全组入方向放行 **8080/tcp**（控制台 → 云服务器 → 安全组）
- 宝塔面板 → 安全 → 防火墙放行 **8080**

## 步骤

### 1. 安装 Docker

宝塔面板 → 软件商店 → 搜索 `Docker` → 安装「Docker 管理器」（自带 compose v2）。

### 2. 拉代码

宝塔面板 → 终端，执行：

```bash
git clone https://github.com/iLian-150/Remedi.git /www/wwwroot/remedi
cd /www/wwwroot/remedi
```

> 仓库是私有的，clone 时按提示输入 GitHub 账号 + Personal Access Token（当密码用）。
> 不会配 token 的话，也可以在 GitHub 网页上 Download ZIP，传到宝塔文件管理器解压。

### 3. 一键启动

```bash
docker compose up -d --build
```

首次构建约 3–5 分钟（装 Python 依赖 + npm 打包前端）。构建完自动启动。

### 4. 访问

浏览器打开：`http://你的公网IP:8080`

- 首页角色选择 → 一键切换老师/学生（演示用 mock 登录，无密码）
- 演示闭环建议：学生"林小夏"交一份数学作业（故意写错一步）→ 看诊断报告 → 老师端看班级总览/纠错

## 常用命令

```bash
cd /www/wwwroot/remedi
docker compose logs -f          # 看日志
docker compose ps               # 看容器状态
docker compose restart          # 重启
docker compose down             # 停止

# 更新代码后重新部署
git pull
docker compose up -d --build
```

## 接入真实 LLM（可选）

`docker-compose.yml` 里把 `LLM_PROVIDER` 改为 `deepseek`，并填写 `DEEPSEEK_API_KEY`，然后：

```bash
docker compose up -d --build api
```

不填 key 也能跑，系统自动走 Mock（作文纠错等能力会弱一些）。

## 换 80 端口 / 绑域名（二期）

- 如宝塔自带 nginx 没占用 80，把 `docker-compose.yml` 里 `8080:80` 改为 `80:80` 后重建
- 绑自己域名：域名解析到服务器 IP，nginx 配置里加 server_name；国内域名需 ICP 备案
