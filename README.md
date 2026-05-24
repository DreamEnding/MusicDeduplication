<p align="center">
  <h1 align="center">Music Deduplication</h1>
  <p align="center">本地音乐去重工具 — 扫描重复音频，智能推荐保留，一键清理释放空间</p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+">
    <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT">
  </p>
</p>

---

## 功能

- Web 界面操作，打开浏览器即可使用
- 扫描 Windows 盘符或任意音乐目录
- **双算法引擎**：内置规则引擎 + AI 辅助去重（支持 OpenAI 兼容 API）
- 自定义去重规则优先级（信息完整度、码率、封面、文件大小、路径长度）
- 识别「歌名-歌手 / 歌手-歌名」倒置命名，区分版本变体（TV版 / 伴奏 / Remix 等）
- 逐组对比保留/重复文件详情，支持手动切换保留
- 搜索过滤、按歌手筛选、按可回收空间排序
- 执行去重时实时进度反馈，支持中途取消
- 导出去重报告 JSON
- 重复文件移动到本地备份目录，可安全回退

## 支持格式

| 格式 | 元数据来源 | 码率/时长 |
|------|-----------|----------|
| MP3 | ID3v2 / ID3v1 | MP3 帧头解析 |
| FLAC | Vorbis Comment | STREAMINFO |
| M4A / ALAC | MP4 atoms | MP4 atoms |
| WMA | ASF Header Object | ASF 头部 |
| OGG | Vorbis Comment | Vorbis 头部 |
| WAV | — | RIFF 头部 |
| DSF | ID3v2 | DSF fmt chunk |

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

## 使用流程

1. 在左侧栏选择扫描目录（盘符或文件夹）
2. 选择去重算法（内置 / AI）并配置规则
3. 点击「开始扫描」
4. 查看右侧重复分组结果，对比保留/重复文件详情
5. 可手动切换保留版本
6. 取消「仅预览」并设置备份目录后，点击「执行去重」
7. 观察进度条，必要时可中途停止

## 算法选项

### 内置算法（默认）

基于标签文本匹配的 Union-Find 去重，完全离线运行：
- 标准化标题 + 歌手名，支持中英文混合
- 自动识别版本标签（TV版、伴奏、Live、Remix 等）
- 可配置 5 条优先级规则选择保留版本

### AI 算法

通过 OpenAI 兼容 API 接入大语言模型，辅助判断重复关系：
- 发送文件元数据（标题、歌手、专辑、码率等）至 LLM 分析
- 支持任意 OpenAI 兼容接口（OpenAI / DeepSeek / 通义千问 / 本地模型等）
- 批量处理，带实时进度反馈
- API Key 仅在会话期间使用，不会持久化存储

## 项目结构

```text
src/music_deduper/
  main.py            # 入口：启动 uvicorn 并打开浏览器
  server.py          # FastAPI 应用与 API 路由
  scanner.py         # 文件扫描与后台任务管理
  audio_metadata.py  # 基于 mutagen 的音频元数据解析
  dedupe.py          # 重复检测（Union-Find）与去重规则
  ai_dedupe.py       # AI 辅助去重（LLM API 调用）
  models.py          # 数据模型（AudioTrack / DuplicateGroup）
  static/
    index.html       # 前端页面
    style.css        # 样式
    app.js           # 前端逻辑
tests/
  test_models.py
  test_audio_metadata.py
  test_rules.py
  test_scanner.py
  test_server.py
  test_integration.py
```

## 测试

```powershell
pip install pytest fastapi-testclient
pytest tests/ -v
```

## 说明

- 去重判断基于 `标题 + 歌手`，标签缺失时退回文件名
- 内置算法未做声纹级别比对，标签完全相同的不同版本可能被归为同组
- AI 算法可更准确地区分版本变体，但需要网络和 API 费用
- 建议执行前先预览结果，确认无误后再去重
- 重复文件移动到备份目录，不会直接删除
