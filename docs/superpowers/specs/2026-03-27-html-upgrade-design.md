# Music Deduplication HTML 升级设计文档

## 概述

将当前 tkinter 桌面应用升级为本地 Web 应用：FastAPI 后端 + 纯 HTML/CSS/JS 前端。保持单机工具定位，用户 `pip install -e .` 后一条命令启动浏览器访问。

## 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端框架 | FastAPI | 轻量、自带 API 文档、自动 reload |
| ASGI 服务器 | Uvicorn | FastAPI 标配 |
| 音频解析 | mutagen | 成熟库，替换手写解析，覆盖 7 种格式 |
| 前端 | 纯 HTML/CSS/JS | 工具类项目无需框架，零构建步骤 |
| 部署形态 | 本地单进程 | FastAPI 同时提供 API 和静态文件服务 |

## 项目结构

```
MusicDeduplication/
├── main.py                      # 入口：启动 FastAPI + 自动打开浏览器
├── pyproject.toml               # 新增 fastapi, uvicorn, mutagen 依赖
├── src/
│   └── music_deduper/
│       ├── __init__.py
│       ├── __main__.py
│       ├── models.py            # 扩展字段（year, genre, track_number, format_info, duration_seconds）
│       ├── audio_metadata.py    # 重写：用 mutagen 替换手写解析，接口不变
│       ├── scanner.py           # 微调：适配新 audio_metadata
│       ├── dedupe.py            # 微调：适配新字段，规则逻辑不变
│       ├── ui.py                # 保留（tkinter 版仍可用）
│       ├── server.py            # 新增：FastAPI 路由层
│       └── static/              # 新增：前端文件
│           ├── index.html
│           ├── style.css
│           └── app.js
└── tests/
    └── test_rules.py            # 适配新接口
```

## 后端 API 设计

### 端点

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/roots` | 获取可用盘符列表 |
| `POST` | `/api/scan` | 启动扫描，返回 task_id |
| `GET` | `/api/scan/{task_id}/status` | 轮询扫描进度和结果 |
| `POST` | `/api/scan/{task_id}/stop` | 停止扫描 |
| `GET` | `/api/groups` | 获取重复分组结果，支持筛选参数 |
| `GET` | `/api/groups/{group_id}` | 获取单组详细对比信息 |
| `PUT` | `/api/groups/{group_id}/keep` | 手动切换保留哪首 |
| `POST` | `/api/execute` | 执行去重（移动文件到备份目录） |
| `GET` | `/api/export` | 导出 JSON 报告 |

### 扫描流程

`POST /api/scan` 接收 `{"path": "D:\\Music"}`，后端创建子线程执行扫描，返回 `{"task_id": "xxx"}`。前端每秒轮询 `GET /api/scan/{task_id}/status`，扫描完成后 status 包含完整分组结果。

### 筛选参数

`GET /api/groups?search=菊花台&artist=周杰伦&album=依然范特西`，返回分组列表 + 聚合统计。

### 执行去重

`POST /api/execute` 接收 `{"group_ids": [...], "backup_dir": "..."}`，返回成功/失败列表。

## 后端升级

### mutagen 替换手写解析

- 接口不变：`read_audio_track(path: Path, root: Path) -> AudioTrack`
- 内部调用 mutagen 解析所有 7 种格式：MP3, FLAC, WAV, AAC/M4A, OGG, WMA
- 新增提取字段：year, genre, track_number, duration_seconds（全部格式）

### AudioTrack 模型扩展

新增字段：
- `duration_seconds: float | None` — 所有格式都提取
- `year: int | None` — 发行年份
- `genre: str` — 流派
- `track_number: int | None` — 轨道号
- `format_info: str` — 格式描述（如 "MP3 CBR", "FLAC"）

### 筛选与统计

`GET /api/groups` 返回聚合统计：
```json
{
  "stats": {
    "artists": [{"name": "周杰伦", "duplicate_count": 12, "reclaimable_bytes": 156000000}],
    "total_duplicates": 56,
    "total_reclaimable": 230000000
  },
  "groups": [...]
}
```

### 依赖

pyproject.toml 新增：`fastapi>=0.110`, `uvicorn>=0.27`, `mutagen>=1.47`

## 前端设计

### 视觉风格：极简中性风

- 纯白底 `#ffffff`，文字黑灰 `#111827` / `#6b7280`，几乎无彩色
- 圆角卡片 + 细边框 `#e5e7eb`，类似 Apple / Notion 风格
- 保留状态用浅绿 `#dcfce7` / `#166534`，移走状态用浅黄 `#fef3c7` / `#92400e`

### 布局：左侧边栏 + 右侧内容区

左侧边栏（固定宽度）：
1. 扫描目录选择（盘符下拉 + 文件夹按钮）
2. 保留规则列表（勾选 + 上下移动优先级）
3. 执行设置（仅预览开关 + 备份目录）
4. 扫描/停止按钮

右侧内容区：
1. 统计卡片行（已识别音频、重复分组、待清理文件、预计释放空间）
2. 工具栏（搜索框 + 歌手筛选下拉 + 重新排序 + 导出报告）
3. 重复结果列表（可展开折叠的分组列表）
4. 底部操作栏（执行去重按钮）
5. 扫描日志（可折叠面板）

### 重复组展开对比视图

展开单个重复组时，显示并排对比：

```
          保留               vs          重复
─────────────────────          ─────────────────────
标题    菊花台                    菊花台
歌手    周杰伦                    周杰伦
专辑    依然范特西                  -
码率    320 kbps        >        128 kbps
大小    5.2 MB          >        2.1 MB
封面    ✅                        ❌
时长    4:32                      4:31
格式    MP3                       MP3
元数据  3/3                       0/3
路径    album/菊花台.mp3           mix/周杰伦-菊花台.mp3
```

### 关键交互

- 搜索：按歌名/歌手模糊搜索，实时过滤
- 筛选：按歌手下拉筛选，按专辑下拉筛选
- 手动切换保留：每组可点击切换保留对象，实时更新统计
- 扫描进度：顶部进度条 + 已扫描数量，每秒刷新
- 执行确认：内联模态框确认，非 alert
- 执行去重后自动刷新结果

## 启动方式

```powershell
python main.py
# 或
python -m music_deduper
```

启动后自动打开浏览器访问 `http://localhost:8000`。FastAPI 自带 API 文档页面 `http://localhost:8000/docs`。
