# 音乐去重助手

一个面向 HiFi 随身听 / SD 卡场景的桌面端音乐去重工具。用户选择盘符后，可以按“信息更完整优先”“码率更高优先”“带封面优先”等规则自动推荐保留文件，并把重复歌曲移动到本地备份目录。

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
