# 🎬 ywsj-sub-translator

基于 Web 的字幕翻译工具，上传字幕文件即可在线翻译成多种语言。

## ✨ 功能特性

- 支持 **SRT / VTT / ASS** 三种字幕格式
- 支持 **Google翻译 / DeepL / LibreTranslate / MyMemory** 多翻译引擎
- 拖拽上传，实时预览
- 批量翻译，保持时间轴不变
- 暗色/亮色主题切换
- Docker 一键部署，支持 amd64 + arm64

## 🚀 快速部署

```bash
docker run -d \
  --name sub-translator \
  -p 5200:5200 \
  --restart unless-stopped \
  ywsj/sub-translator:latest
```

或使用 docker-compose：

```yaml
services:
  sub-translator:
    image: ywsj/sub-translator:latest
    container_name: sub-translator
    ports:
      - "5200:5200"
    restart: unless-stopped
```

```bash
docker compose up -d
```

部署后访问 `http://你的IP:5200`。

## 📖 使用方法

1. **上传字幕文件** — 拖拽或点击上传 `.srt` / `.vtt` / `.ass` 文件
2. **选择翻译设置** — 选择翻译引擎、源语言、目标语言
3. **预览** — 可先预览前 10 条字幕确认解析正确
4. **翻译** — 点击翻译后自动下载翻译后的字幕文件

### 翻译引擎说明

| 引擎 | 需要 API Key | 说明 |
|------|-------------|------|
| Google翻译 | 否 | 免费端点，无需配置 |
| DeepL | 是 | 翻译质量最好，需注册获取 API Key |
| LibreTranslate | 否 | 开源自部署，填入服务地址即可 |
| MyMemory | 否 | 免费翻译 API |

## 🙏 致谢

- [webcaptioner](https://github.com/curtgrimes/webcaptioner) — 语音转文字 Web 应用的设计灵感来源

## 📄 License

MIT
