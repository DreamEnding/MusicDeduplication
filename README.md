<p align="center">
  <h1 align="center">Music Deduplication</h1>
  <p align="center">本地音乐去重工具 — 扫描重复音频，智能推荐保留，一键清理释放空间</p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+">
    <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT">
  </p>
</p>

---

## 功能特性

### 重复检测与去重

- **双算法引擎**：内置规则引擎（离线）+ AI 辅助去重（OpenAI 兼容 API）
- Union-Find 聚类算法，基于 `标题 + 歌手` 签名匹配
- 智能版本识别：自动区分 TV 版、纯音版、伴奏、Live、Remix、Cover 等变体
- 5 条可配置优先级规则：信息完整度、码率、封面、文件大小、路径长度
- 逐组对比保留/重复文件详情，支持手动切换保留版本
- 搜索过滤、按歌手筛选、按可回收空间排序

### 文件管理

- 全量文件浏览：搜索、排序、分页
- 单文件/批量元数据编辑（标题、歌手、专辑、年份、流派、轨道号）
- 歌词查看与嵌入（支持 LRC 文件导入）
- 封面图片查看与上传替换
- 格式统计：总文件数、总大小、格式分布、平均码率

### 执行与安全

- 执行去重时实时进度反馈，支持中途取消
- 重复文件移动到本地备份目录（不直接删除），可安全回退
- 导出去重报告 JSON
- CSRF 中间件防护，路径校验限制访问范围
- API Key 仅会话期间使用，不持久化存储

## 支持格式

| 格式 | 元数据来源 | 码率/时长 | 歌词 | 封面 |
|------|-----------|----------|------|------|
| MP3 | ID3v2 / ID3v1 | MP3 帧头 | USLT | APIC |
| FLAC | Vorbis Comment | STREAMINFO | LYRICS | metadata_block_picture |
| M4A / ALAC | MP4 atoms | MP4 atoms | ©lyr | covr |
| WMA | ASF Header | ASF 头部 | WM/Lyrics | WM/Picture |
| OGG | Vorbis Comment | Vorbis 头部 | LYRICS | metadata_block_picture |
| WAV | — | RIFF 头部 | — | — |
| DSF | ID3v2 | DSF fmt chunk | USLT | APIC |

## 安装

需要 Python 3.12+。

```powershell
git clone https://github.com/DreamEnding/MusicDeduplication.git
cd MusicDeduplication
pip install -e .
```

## 运行

```powershell
python -m music_deduper
```

程序启动后自动打开浏览器访问 `http://127.0.0.1:8000`。

也可以直接运行入口脚本：

```powershell
python src/music_deduper/main.py
```

## 配置

复制 `.env.example` 为 `.env`，按需修改：

```powershell
copy .env.example .env
```

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `MUSIC_DEDUP_HOST` | `127.0.0.1` | 服务器监听地址 |
| `MUSIC_DEDUP_PORT` | `8000` | 服务器端口 |
| `MUSIC_DEDUP_DEBUG` | `false` | 调试模式 |
| `MUSIC_DEDUP_BACKUP_DIR` | `~/.music_deduper/backups` | 备份目录 |
| `MUSIC_DEDUP_AI_DEFAULT_URL` | — | AI API 默认地址 |
| `MUSIC_DEDUP_AI_DEFAULT_MODEL` | `gpt-4o-mini` | AI 默认模型 |
| `MUSIC_DEDUP_LOG_LEVEL` | `INFO` | 日志级别 |
| `MUSIC_DEDUP_LOG_FILE` | `music_deduper.log` | 日志文件路径 |
| `MUSIC_DEDUP_ALLOWED_ORIGINS` | localhost/127.0.0.1 | CSRF 允许的 Origin |
| `MUSIC_DEDUP_MAX_SCAN_TIMEOUT` | `300` | 扫描超时（秒） |
| `MUSIC_DEDUP_MAX_EXECUTE_TIMEOUT` | `600` | 执行超时（秒） |

## 使用流程

### 重复检测模式

1. 在左侧栏选择扫描目录（盘符或文件夹）
2. 配置保留规则（信息完整度、码率、封面等）
3. 选择去重算法（内置 / AI）并配置参数
4. 点击「开始扫描」
5. 查看右侧重复分组结果，对比保留/重复文件详情
6. 可手动切换保留版本
7. 取消「仅预览」并设置备份目录后，点击「执行去重」
8. 观察进度条，必要时可中途停止

### 文件管理模式

1. 切换到「文件管理」视图
2. 浏览全部已扫描文件，支持搜索、排序、筛选
3. 点击行展开详情，编辑元数据（标题、歌手、专辑等）
4. 查看/嵌入歌词，上传替换封面
5. 勾选多个文件进行批量编辑

## 算法详解

### 内置算法（默认）

基于标签文本匹配的 Union-Find 去重，完全离线运行：

1. **签名构建**：从元数据提取 `artist + title`，从文件名推断 `Artist - Title` 模式
2. **文本标准化**：转小写、去特殊字符、统一空格
3. **版本标签提取**：正则匹配 TV 版、纯音版、伴奏、Live、Remix 等，不同版本不归为同组
4. **Union-Find 聚类**：相同签名的曲目合并为一组
5. **保留选择**：按启用的规则评分，分数最高者保留；平局时按路径深度和长度稳定排序

### AI 算法

通过 OpenAI 兼容 API 接入大语言模型：

- 发送文件元数据（标题、歌手、专辑、码率、时长、大小）至 LLM 分析
- 支持任意 OpenAI 兼容接口（OpenAI / DeepSeek / 通义千问 / 本地模型等）
- 批量处理（50 首/批，最多 20 批），带实时进度反馈
- LLM 返回结构化 JSON，解析后构建重复分组

## API 文档

启动服务后访问 `http://127.0.0.1:8000/docs` 查看自动生成的 Swagger 文档。

### 核心端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/roots` | 列出可用盘符 |
| `GET` | `/api/browse?path=` | 目录浏览 |
| `POST` | `/api/scan` | 启动扫描任务 |
| `GET` | `/api/scan/{id}/status` | 轮询扫描进度 |
| `POST` | `/api/scan/{id}/stop` | 停止扫描 |
| `PUT` | `/api/rules` | 更新保留规则 |
| `GET` | `/api/groups` | 获取重复分组 |
| `GET` | `/api/groups/{id}` | 获取单个分组详情 |
| `PUT` | `/api/groups/{id}/keep?path=` | 切换保留版本 |
| `POST` | `/api/execute` | 执行去重 |
| `GET` | `/api/execute/{id}/status` | 轮询执行进度 |
| `POST` | `/api/execute/{id}/stop` | 停止执行 |
| `GET` | `/api/tracks` | 文件列表（搜索/排序/分页） |
| `PUT` | `/api/tracks/update` | 更新单文件元数据 |
| `PUT` | `/api/tracks/batch-update` | 批量更新元数据 |
| `GET` | `/api/tracks/lyrics?path=` | 读取歌词 |
| `PUT` | `/api/tracks/lyrics` | 写入歌词 |
| `POST` | `/api/tracks/cover` | 上传封面 |
| `GET` | `/api/cover/{hash}` | 获取封面图片 |
| `GET` | `/api/export` | 导出 JSON 报告 |

## 项目结构

```text
MusicDeduplication/
├── main.py                    # 快捷入口脚本
├── pyproject.toml             # 项目配置与依赖
├── .env.example               # 环境变量模板
├── src/music_deduper/
│   ├── __init__.py
│   ├── __main__.py            # python -m 入口
│   ├── main.py                # 启动 uvicorn + 打开浏览器
│   ├── server.py              # FastAPI 应用与全部 API 路由
│   ├── scanner.py             # 文件扫描与盘符枚举
│   ├── audio_metadata.py      # 音频元数据解析（mutagen）+ 封面/歌词
│   ├── dedupe.py              # Union-Find 去重算法与规则引擎
│   ├── ai_dedupe.py           # AI 辅助去重（LLM API 调用）
│   ├── models.py              # 数据模型（AudioTrack / DuplicateGroup）
│   ├── config.py              # pydantic-settings 配置管理
│   └── static/
│       ├── index.html         # 前端页面
│       ├── style.css          # 样式
│       └── app.js             # 前端逻辑
└── tests/
    ├── test_models.py         # 数据模型测试
    ├── test_audio_metadata.py # 元数据解析测试
    ├── test_rules.py          # 去重规则测试
    ├── test_scanner.py        # 扫描器测试
    ├── test_server.py         # API 端点测试
    └── test_integration.py    # 集成测试
```

## 测试

```powershell
pip install pytest
pytest tests/ -v
```

## 技术栈

- **后端**：FastAPI + uvicorn
- **前端**：原生 HTML / CSS / JavaScript（无框架）
- **元数据**：mutagen
- **AI**：httpx（OpenAI 兼容 API）
- **配置**：pydantic-settings

## 注意事项

- 去重判断基于 `标题 + 歌手`，标签缺失时退回文件名解析
- 内置算法未做声纹级别比对，标签完全相同的不同版本可能被归为同组
- AI 算法可更准确地区分版本变体，但需要网络和 API 费用
- 建议执行前先预览结果，确认无误后再去重
- 重复文件移动到备份目录，不会直接删除

## License

MIT
