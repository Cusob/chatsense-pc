<p align="center">
  <img src="" alt="ChatSense" width="120" />
</p>
<h1 align="center">ChatSense</h1>
<p align="center">
  <strong>微信聊天智能分析助手</strong>
  <br />
  直接读取本地加密数据库 · 无需 Root/Hook · 零权限要求
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python" />
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey.svg" alt="Platform" />
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License" />
  <img src="https://img.shields.io/badge/tests-65%20passed-brightgreen.svg" alt="Tests" />
  <img src="https://img.shields.io/badge/version-1.0.0-orange.svg" alt="Version" />
</p>

---

## 为什么选择 ChatSense

不同于市面工具需要导出数据、Hook 微信进程或手动转录——**ChatSense 从本地加密数据库直接解密读取**，零延迟、零数据泄露风险。适用于 WeChat 2.x / 3.x / AppStore 全版本。

## 核心功能

| 功能 | 说明 |
|------|------|
| **8 维分析** | 分寸感 · 共情力 · 你来我往 · 自我展示 · 自然度 · 主动性 · 真诚感 · 升温力 |
| **AI 对话** | 基于当前聊天记录与 LLM 对话，获取上下文感知的回复建议 |
| **深度思考** | DeepSeek Reasoner 推理过程可视化，可折叠展开 |
| **联网搜索** | 结合 DuckDuckGo 搜索结果增强 AI 回答质量 |
| **语音转录** | WeChat 2.x/3.x 语音消息自动转文字（需腾讯云 ASR） |
| **实时监控** | watchdog 文件变更检测 + 3 秒轮询双保险，新消息自动刷新 |
| **自动识别** | 自动检测当前登录的微信账户，无需手动选择 |

## 分析维度

每个维度提供**基于具体对话内容的详细分析**，引用实际聊天片段作为证据，给出可操作建议。

| 维度 | 评分逻辑 | 说明 |
|------|---------|------|
| **分寸感** Boundary | 越高越好 | 是否尊重边界，避免过度追问 |
| **共情力** Empathy | 越高越好 | 对方表达情绪时先理解而非给建议 |
| **你来我往** Interaction | 中间最好 | 双方发言平衡度，避免一方主导 |
| **自我展示** Self-disclosure | 中间最好 | 太少不了解你，太多显得自我中心 |
| **自然度** Naturalness | 越高越好 | 对话流畅度，有无模板感 |
| **主动性** Initiative | 中间最好 | 太少被动，太多给对方压力 |
| **真诚感** Authenticity | 越高越好 | 表达真实度，有人工话术则减分 |
| **升温力** Escalation | 越高越好 | 关系推进是否自然，是否适合当前阶段 |

## 快速开始

### 前置条件

- **Windows 10/11**
- **微信 PC 版已登录并运行**（WeChat.exe / WeChatStore.exe）
- **[DeepSeek API Key](https://platform.deepseek.com/)**（免费注册即可）

### 使用 .exe（推荐）

从 [Releases](https://github.com/Cusob/chatsense-pc/releases) 下载 `ChatSense.exe`，双击运行即可。无需安装 Python。

### 源码运行

```bash
git clone https://github.com/Cusob/chatsense-pc.git
cd chatsense-pc
pip install -r requirements.txt
python main.py
```

### 配置步骤

1. **Settings → API 设置**：填写 DeepSeek API Key 和 API URL，点击"测试连接"
2. （可选）**Settings → 语音识别**：填写腾讯云 SecretId/SecretKey，启用语音转录
3. 选择联系人 → 点击"开始分析" 或切换到 "AI 对话" Tab

## 界面

三栏布局，右侧 Dashboard 分析结果与 AI 对话自由切换。

```
┌──────────┬───────────────────┬────────────────────────────┐
│ 联系人列表  │     聊天窗口        │  Dashboard / AI 对话        │
│ 🔍 搜索    │  ┌─────────────┐  │  ┌──────────────────────┐ │
│ ● Alice   │  │ 我: 你好      │  │  │ 分析结果 │ AI 对话    │ │
│   Bob     │  │ Alice: 嗨!   │  │  │ 分寸感(75) ━━━━━━━━  │ │
│ ● Carol   │  │ 我: 今天有空  │  │  │ 共情力(55) ━━━━━━    │ │
│           │  │ ...          │  │  │ ...                   │ │
│           │  └─────────────┘  │  └──────────────────────┘ │
└──────────┴───────────────────┴────────────────────────────┘
```

## 技术架构

| 层级 | 技术 |
|------|------|
| GUI | **PyQt6** — 三栏 QSplitter 布局，QTabWidget 分析/对话切换 |
| 解密 | **pywxdump** + **pycryptodome** — AES-256 解密微信数据库 |
| 数据库 | **ChatCRMsg** / **ChatMsg** / **MSG** — 适配 2.x/3.x/AppStore |
| 语音 | **pysilk** (SILK v3 解码) + **Tencent Cloud ASR** (转录) |
| 图表 | **matplotlib** — 柱状图、趋势图、雷达图 |
| 监控 | **watchdog** + 3 秒轮询 — 双重保障实时更新 |
| AI | **DeepSeek API** 兼容格式 — 分析 + 对话 + 深度思考 |
| 打包 | **PyInstaller** — 单文件 .exe (~130MB) |

## 项目结构

```
chatsense-pc/
├── main.py                     # 程序入口
├── pyinstaller.spec             # PyInstaller 打包配置
├── requirements.txt             # Python 依赖
├── config/                      # 配置管理
├── engine/                      # 核心引擎（14 个模块）
│   ├── analysis_engine.py       # 8 维 LLM 分析管道
│   ├── api_client.py            # OpenAI/Anthropic 兼容 API 客户端
│   ├── chat_engine.py           # AI 对话引擎（深度思考 + 联网搜索）
│   ├── content_parser.py        # 语音/表情 XML 解析
│   ├── db_crypto.py             # AES 解密 + 密钥验证
│   ├── db_reader.py             # 多分片多格式数据库读取
│   ├── file_watcher.py          # watchdog 文件监控
│   ├── key_extractor.py         # pywxdump/pymem 密钥提取
│   ├── scoring.py               # Python 评分算法
│   ├── tencent_stt.py           # 腾讯云 ASR + 转录缓存
│   ├── voice_decoder.py         # MediaMSG.db BLOB → WAV
│   └── wechat_scanner.py        # 多路径自动扫描
├── models/                      # 数据模型
├── ui/                          # PyQt6 界面
│   ├── chat_tab.py              # AI 对话 Tab
│   ├── chat_view.py             # 聊天气泡
│   ├── contact_panel.py         # 联系人列表
│   ├── dashboard.py             # 分析面板
│   ├── main_window.py           # 主窗口
│   ├── settings_dialog.py       # 设置对话框
│   └── widgets/                 # 自定义控件
└── tests/                       # 65 个单元测试
```

## 常见问题

**Q: 需要 Root 或 Hook 微信吗？**
A: 不需要。ChatSense 通过 pywxdump 从微信进程内存中读取 AES 密钥，然后直接解密本地数据库文件，只读模式，不修改任何微信文件。

**Q: 支持哪些微信版本？**
A: WeChat 2.x（明文 MSG.db）、3.x（加密 MSG*.db 分片）、AppStore 版（ChatCRMsg.db）。

**Q: 数据安全吗？**
A: 所有数据仅存储在本地。聊天分析发送给 DeepSeek API，语音转录发送给腾讯云 ASR——与其他 AI 工具相同。不发送文件列表、联系人元数据或数据库文件本身。

**Q: 为什么有些消息看不到？**
A: 默认加载 200 条消息。在 Dashboard 中调整"加载消息数"，点击"重新加载"即可。

## License

MIT © ChatSense
