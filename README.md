# 🎬 ywsj-sub-translator

基于 Web 的字幕翻译工具，上传字幕文件即可在线翻译成多种语言。支持传统翻译引擎、LLM 大模型翻译、传统翻译 API 三大类翻译方式，自带翻译进度、实时日志、在线编辑、双语字幕导出等功能。

## ✨ 功能特性

- 📝 **字幕格式** — 支持 SRT / VTT / ASS 三种格式，自动检测
- 🌐 **翻译引擎丰富**
  - 传统引擎：Google 翻译 / DeepL / LibreTranslate
  - LLM 大模型：硅基流动 / OpenAI / DeepSeek / 智谱 GLM / 月之暗面 / OpenRouter / Ollama 本地 / 任意 OpenAI 兼容 API
  - 传统翻译 API：腾讯翻译 / 百度翻译 / 有道翻译
- ⚡ **批量翻译** — 批量发送、进度条实时显示、翻译日志实时输出
- ✏️ **在线编辑** — 翻译完成后可逐条编辑译文，支持单条重新翻译
- 🌍 **双语字幕** — 支持导出双语字幕（原文+译文），可选择排列顺序
- 🧠 **智能跳过** — 混合语言字幕自动跳过已是目标语言的条目
- 🔐 **登录认证** — 可选密码登录保护，支持在线修改密码
- ⚙️ **配置管理** — `/settings` 页面集中管理 LLM 配置和翻译 API 配置，支持测试连接、自动获取模型列表
- 🐳 **Docker 部署** — 支持 amd64 + arm64 双架构，GitHub Actions 自动构建发布
- 🎨 暗色 / 亮色主题切换

## 🚀 快速部署

### Docker（推荐）

```bash
docker run -d \
  --name sub-translator \
  -p 5200:5200 \
  -v ./data:/data \
  --restart always \
  ywsj/sub-translator:latest
```

### Docker Compose

```yaml
services:
  sub-translator:
    image: ywsj/sub-translator:latest
    container_name: sub-translator
    ports:
      - "5200:5200"
    volumes:
      - ./data:/data
    restart: always
```

```bash
docker compose up -d
```

部署后访问 `http://你的IP:5200`。

> 首次访问会要求设置登录用户名和密码，设置后所有功能均需登录使用。配置数据保存在 `/data` 目录。

## 📖 使用方法

1. **上传字幕文件** — 拖拽或点击上传 `.srt` / `.vtt` / `.ass` 文件
2. **选择翻译引擎** — 在翻译页面选择引擎，或前往 `/settings` 页面预先配置 LLM / 翻译 API
3. **翻译** — 点击翻译，实时查看进度和日志
4. **在线编辑** — 翻译完成后可逐条编辑译文，或对单条重新翻译
5. **下载** — 下载翻译后的字幕，可选双语模式（原文 + 译文）

### 翻译引擎说明

| 类型 | 引擎 | 需要 API Key | 说明 |
|------|------|:---:|------|
| 传统引擎 | Google 翻译 | ❌ | 免费端点，无需配置 |
| 传统引擎 | DeepL | ✅ | 翻译质量好，需注册获取 API Key |
| 传统引擎 | LibreTranslate | ❌ | 开源自部署，填入服务地址即可 |
| LLM 大模型 | 硅基流动 SiliconFlow | ✅ | 国内可直连，有免费额度 |
| LLM 大模型 | OpenAI | ✅ | GPT 系列模型 |
| LLM 大模型 | DeepSeek | ✅ | 性价比高 |
| LLM 大模型 | 智谱 GLM | ✅ | 国产大模型 |
| LLM 大模型 | 月之暗面 | ✅ | Kimi 系列模型 |
| LLM 大模型 | OpenRouter | ✅ | 聚合平台，有免费模型 |
| LLM 大模型 | Ollama 本地 | ❌ | 本地部署，无需联网 |
| LLM 大模型 | 自定义 | ✅ | 任意 OpenAI 兼容 API |
| 翻译 API | 腾讯翻译 | ✅ | 需 SecretId + SecretKey |
| 翻译 API | 百度翻译 | ✅ | 需 APP ID + 密钥 |
| 翻译 API | 有道翻译 | ✅ | 需应用 ID + 应用密钥 |

> LLM 大模型和翻译 API 均在 `/settings` 页面统一管理，支持添加多个配置、测试连接、自动获取可用模型列表。

## 🛠️ 技术栈

- **后端** — Python / Flask / Gunicorn
- **前端** — 原生 HTML + CSS + JavaScript
- **部署** — Docker（多架构 amd64 + arm64）
- **CI/CD** — GitHub Actions 自动构建推送 Docker Hub + 创建 GitHub Release

## 📂 项目结构

```
ywsj-sub-translator/
├── app.py                 # Flask 主应用（路由、认证、任务管理）
├── translator.py          # 翻译引擎（传统引擎、LLM、翻译 API）
├── subtitle_parser.py     # 字幕解析与重建（SRT/VTT/ASS、双语）
├── templates/
│   ├── index.html         # 翻译主页面
│   ├── settings.html      # 配置管理页面
│   └── login.html         # 登录页面
├── Dockerfile
├── docker-compose.yml
└── .github/workflows/
    └── docker-publish.yml # CI 自动构建发布
```

## ☕ 请作者喝杯咖啡

如果这个项目对你有帮助，欢迎请作者喝杯咖啡 ☕️

![打赏码](assets/donation.jpg)

## 🙏 致谢

- [Flask](https://flask.palletsprojects.com/) — Web 框架
- [Gunicorn](https://gunicorn.org/) — WSGI HTTP 服务器
- 各翻译引擎 / LLM 提供商的 API 服务

## 📄 License

MIT
