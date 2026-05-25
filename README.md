<p align="center">
  <h1 align="center">ChatSense</h1>
  <p align="center">微信聊天智能分析助手 — 直接读取本地加密数据库，无需 Root / Hook</p>
</p>

---

## 功能

| 功能 | 说明 |
|------|------|
| **8 维分析** | 分寸感、共情力、你来我往、自我展示、自然度、主动性、真诚感、升温力 |
| **AI 对话** | 基于当前聊天记录与 LLM 对话，获取上下文感知的回复建议 |
| **深度思考** | DeepSeek Reasoner 推理过程可视化（可折叠展示） |
| **联网搜索** | 结合网络搜索结果增强 AI 回答质量 |
| **语音转录** | WeChat 2.x/3.x 语音消息自动转文字（需配置腾讯云 ASR） |
| **实时监控** | 文件变更检测 + 3 秒轮询双重保障，新消息自动刷新 |
| **自动识别** | 自动检测当前登录的微信账户，无需手动选择 |

## 分析维度

| 维度 | 说明 | 评分逻辑 |
|------|------|---------|
| 分寸感 | 是否尊重边界、避免过度追问 | 过高 > 适中 |
| 共情力 | 对方表达情绪时是否先理解而非给建议 | 越高越好 |
| 你来我往 | 双方发言平衡度 | 中间最好 |
| 自我展示 | 展示自己的程度 | 中间最好 |
| 自然度 | 对话是否流畅自然 | 越高越好 |
| 主动性 | 发起话题的程度 | 中间最好 |
| 真诚感 | 表达真实度，有无话术套路 | 越高越好 |
| 升温力 | 关系推进的自然程度 | 越高越好 |

## 快速开始

### 前置条件

- Windows 10/11
- 微信 PC 版已登录并运行（WeChat.exe / WeChatStore.exe）
- [DeepSeek API Key](https://platform.deepseek.com/)（免费注册）

### 下载使用

从 [Releases](../../releases) 下载 `ChatSense.exe`，双击运行。

### 源码运行

```bash
pip install -r requirements.txt
python main.py
```

### 配置

Settings → API 设置：填写 DeepSeek API Key。语音识别可选。

## 技术栈

| 组件 | 技术 |
|------|------|
| GUI | PyQt6 |
| 加密解密 | pywxdump + pycryptodome (AES-256) |
| 语音解码 | pysilk (SILK v3) + Tencent Cloud ASR |
| 图表 | matplotlib |
| 文件监控 | watchdog + 3s 轮询 |
| 打包 | PyInstaller (单文件 .exe) |

## 项目结构

```
ChatSense-PC/
├── main.py                 # 入口
├── config/                 # 配置管理
├── engine/                 # 核心引擎 (14 模块)
│   ├── analysis_engine.py  # LLM 分析管道
│   ├── api_client.py       # API 客户端
│   ├── chat_engine.py      # AI 对话引擎
│   ├── db_reader.py        # 数据库读取
│   ├── file_watcher.py     # 文件监控
│   ├── key_extractor.py    # 密钥提取
│   ├── tencent_stt.py      # 腾讯云 ASR
│   └── voice_decoder.py    # 语音解码
├── models/                 # 数据模型
├── ui/                     # PyQt6 界面
└── tests/                  # 65 个单元测试
```

## 系统要求

- Windows 10/11 · 微信 PC 版 2.x / 3.x / AppStore 版
- Python 3.11+（源码运行）· 无 GPU 要求

## License

MIT
