<p align="center">
  <h1 align="center">🔬 ChatSense</h1>
  <p align="center">
    <strong>微信聊天智能分析助手</strong><br />
    直接解密本地数据库 · 无需 Root · 无需 Hook · 零权限要求
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue" />
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey" />
  <img src="https://img.shields.io/badge/license-MIT-green" />
  <img src="https://img.shields.io/badge/tests-65%20passed-brightgreen" />
  <img src="https://img.shields.io/badge/version-1.0.0-orange" />
</p>

---

## 💡 它是什么

ChatSense 是一个 **Windows 桌面应用**，直接解密微信本地加密数据库，实时读取聊天记录，然后用 LLM 进行多维度分析——帮你理解每一次对话的质量、节奏和可改进之处。

**与市面上所有工具的根本区别**：不需要导出数据、不需要 Hook 微信进程、不需要 Root 权限。一切从你电脑上已有的加密数据库文件中直接读取，数据从未离开你的机器（除你主动选择的分析请求外）。

## ✨ 功能

| 功能 | 说明 |
|------|------|
| **🎯 8 维智能分析** | 分寸感 · 共情力 · 你来我往 · 自我展示 · 自然度 · 主动性 · 真诚感 · 升温力 |
| **💬 AI 对话顾问** | 基于当前聊天记录与 LLM 对话，获得上下文感知的回复建议 |
| **🧠 深度思考** | DeepSeek Reasoner 推理过程可视化，可折叠查看 AI 的完整思考链路 |
| **🌐 联网搜索** | 结合实时网络搜索结果，增强回答的时效性和准确性 |
| **🎤 语音转文字** | WeChat 2.x/3.x/AppStore 全版本语音消息自动转录（需腾讯云 ASR） |
| **🔄 实时同步** | watchdog 文件监控 + 3 秒轮询双重保障，微信发送消息后立即刷新 |
| **🎯 自动识别** | 自动检测当前登录的微信账户，支持标准版和 AppStore 版本 |

## 🏆 与同类工具对比

| | ChatSense | 其他工具 |
|------|-----------|---------|
| **数据获取** | 直接解密本地加密数据库 | 需要登录态抓包 / Hook 微信进程 / 手动导出 |
| **零权限** | 无需 Root / 管理员 / 无障碍权限 | 多数需要管理员权限或注入微信进程 |
| **语音转录** | 解码 MediaMSG.db 中的 SILK BLOB | 不支持或仅能读取文件系统音频文件 |
| **分析深度** | LLM 逐条标注 + Python 评分 + 不同维度不同评分逻辑 | 简单统计或单阶段 LLM 分析 |
| **实时同步** | 双重监控机制，秒级刷新 | 手动刷新或无实时能力 |
| **隐私** | 数据仅在本地，分析时才发送对话文本至 API | 部分工具会上传完整数据库或聊天记录 |

## 📊 分析维度

每个维度的**评分逻辑独立设计**，不是一刀切的"越高越好"——这源于对真实聊天数据的深入理解。

| 维度 | 评分逻辑 | 为什么 |
|------|---------|--------|
| **分寸感** Boundary | 越高越好 | 尊重边界、避免过度追问是永恒的正确 |
| **共情力** Empathy | 越高越好 | 对方表达情绪时先理解再回应，而非直接给建议 |
| **你来我往** Interaction | **中间最好** | 一方说得太多是压迫，说得太少是冷淡 |
| **自我展示** Self-disclosure | **中间最好** | 一味展示自己是自我中心，完全隐藏是无法建立信任 |
| **自然度** Naturalness | 越高越好 | 话术模板感和生硬转折都会让对方感到不适 |
| **主动性** Initiative | **中间最好** | 太被动让对方觉得你不在乎，太过主动给对方压力 |
| **真诚感** Authenticity | 越高越好 | 真诚永远是最高级的技巧 |
| **升温力** Escalation | 越高越好 | 在合适阶段自然推进关系，而非强行加速或停滞不前 |

> **每个维度都配有基于对话内容的详细文字分析**，引用具体聊天片段作为证据，给出可操作建议。

## 🚀 快速开始

### 只需三步

1. **确保微信 PC 版已登录并运行**
2. **下载 [ChatSense.exe](https://github.com/Cusob/chatsense-pc/releases)**，双击运行
3. **Settings → API 设置**，填写 [DeepSeek API Key](https://platform.deepseek.com/)（免费注册）

### 源码运行

```bash
git clone https://github.com/Cusob/chatsense-pc.git
cd chatsense-pc
pip install -r requirements.txt
python main.py
```

### 可选功能

- **语音转录**：Settings → 语音识别，填写腾讯云 SecretId/SecretKey（每月 5,000 次免费额度）

## 🎛️ 使用指南

1. 启动后自动识别当前微信账户，加载联系人列表
2. 选择联系人，调整"加载消息数"和"分析消息数"
3. 点击 **开始分析**，等待 LLM 生成 8 维评分和详细建议
4. 切换到 **AI 对话** Tab，开启深度思考或联网搜索，自由提问
5. 点击 **导出** 保存分析报告为 PNG 或 TXT

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────────┐
│                     ChatSense                           │
├──────────┬──────────────────┬───────────────────────────┤
│ 联系人面板  │     聊天窗口       │  Dashboard / AI 对话      │
│ (PyQt6)  │    (PyQt6)       │  (QTabWidget)            │
├──────────┴──────────────────┴───────────────────────────┤
│                    引擎层                                │
├─────────────────────────────────────────────────────────┤
│ analysis_engine  │ chat_engine   │ tencent_stt          │
│ 8维分析 + 评分    │ 深度思考+搜索  │ 语音转录 + 缓存        │
├─────────────────────────────────────────────────────────┤
│ db_reader │ key_extractor │ voice_decoder │ file_watcher│
│ 多分片解密  │ pywxdump/pymem│ SILK→WAV      │ watchdog+轮询│
├─────────────────────────────────────────────────────────┤
│              微信本地加密数据库 (MSG/ChatCRMsg/ChatMsg)    │
└─────────────────────────────────────────────────────────┘
```

| 层级 | 技术栈 |
|------|--------|
| GUI | **PyQt6** |
| 解密 | **pywxdump** + **pycryptodome** (AES-256) |
| AI | **DeepSeek API** / OpenAI 兼容格式 |
| 语音 | **pysilk** (SILK v3) + **Tencent Cloud ASR** |
| 图表 | **matplotlib** (柱状图、趋势图) |
| 打包 | **PyInstaller** (单文件 .exe ~130MB) |

## 📁 项目结构

```
chatsense-pc/
├── main.py                  # 程序入口
├── pyinstaller.spec          # 打包配置
├── requirements.txt          # Python 依赖
├── config/                   # 配置管理
├── engine/                   # 核心引擎 (14 个模块)
│   ├── analysis_engine.py    # LLM 分析管道
│   ├── api_client.py         # API 客户端
│   ├── chat_engine.py        # AI 对话 + 深度思考 + 搜索
│   ├── content_parser.py     # 语音/表情 XML 解析
│   ├── db_reader.py          # 多分片数据库读取
│   ├── db_crypto.py          # AES 解密 + 密钥验证
│   ├── file_watcher.py       # 文件监控
│   ├── key_extractor.py      # 密钥提取
│   ├── scoring.py            # Python 评分算法
│   ├── tencent_stt.py        # 腾讯云 ASR
│   ├── voice_decoder.py      # MediaMSG.db → WAV
│   └── wechat_scanner.py     # 多路径自动扫描
├── models/                   # 数据模型
├── ui/                       # PyQt6 界面 (6 组件 + 3 控件)
└── tests/                    # 65 个单元测试
```

## ❓ 常见问题

**Q: 我的数据安全吗？**
A: 所有聊天数据存储在本地。分析时仅将选中的对话文本片段发送至 DeepSeek API，语音转录发送至腾讯云 ASR——不会上传完整数据库、文件列表或联系人元数据。

**Q: 为什么有些消息看不到？**
A: 默认加载 200 条消息。在 Dashboard 中调整"加载消息数"，点击"重新加载"即可加载更多。

**Q: 支持什么微信版本？**
A: WeChat 2.x（明文 MSG.db）、3.x（加密分片 MSG*.db）、AppStore 版（ChatCRMsg.db）。已在一台有 10 万条真实消息的 AppStore 版本上验证。

**Q: 为什么不支持 macOS/Linux？**
A: 解密方案依赖 Windows 特定的 pywxdump/pymem 来从微信进程内存读取 AES 密钥。

**Q: 需要付费吗？**
A: ChatSense 完全免费开源。DeepSeek API 提供免费额度（注册即送），足够日常使用。语音转录使用腾讯云 ASR 免费额度（每月 5,000 次）。

## 📄 License

MIT © ChatSense
