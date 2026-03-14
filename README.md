# 音乐去重助手

本项目聚焦 HiFi 播放器 / SD 卡听歌场景，旨在解决“专辑与单曲混存后产生大量重复歌曲”的实际问题。这些重复文件不仅占用存储空间，也会影响日常听歌体验。为此，我们开发了智能音乐去重助手：支持多种常见音频格式，支持多规则组合去重（如信息完整度优先、码率更高优先、带封面优先），并自动推荐保留版本；重复歌曲可安全移动到本地备份目录，在可回退的前提下释放空间并优化曲库体验。

## 功能

- 扫描 Windows 盘符或任意音乐目录
- UI 中勾选并调整去重规则优先级
- 识别重复歌曲并展示保留建议
- 支持识别“歌名-歌手 / 歌手-歌名”倒置命名
- 将重复文件移动到本地备份目录，释放 SD 卡空间
- 导出去重报告 JSON

## 当前支持

- 音频格式扫描: `mp3` `flac` `wav` `aac` `m4a` `ogg` `wma`
- 元数据解析:
  - `mp3`: 读取 `ID3v2 / ID3v1` 的标题、歌手、专辑、封面信息，码率读取 MP3 帧头
  - `flac`: 读取 `Vorbis Comment` 的标题、歌手、专辑、封面信息，码率按文件大小与时长估算

说明:

- 去重判断优先基于 `标题 + 歌手`
- 若标签缺失，则退回到 `文件名`
- 对 VBR MP3，码率可能是近似值
- 当前未做声纹级别比对，因此不同版本但标签完全相同的歌曲仍可能被归到同组，执行前建议先预览结果

## 运行

```powershell
python main.py
```

也可以使用:

```powershell
python -m pip install -e .
python -m music_deduper
```

## 使用流程

1. 插入 SD 卡。
2. 打开程序并选择盘符，或手动选择音乐目录。
3. 在左侧勾选规则并调整优先级。
4. 点击“开始扫描”。
5. 查看右侧推荐的“保留 / 移走”结果。
6. 取消“仅预览”后点击“执行去重”。

## 项目结构

```text
main.py
src/music_deduper/
  audio_metadata.py
  dedupe.py
  main.py
  models.py
  scanner.py
  ui.py
tests/
```

## 测试

```powershell
$env:PYTHONPATH = ".\src"
python -m unittest discover -s tests -p "test_*.py"
```
