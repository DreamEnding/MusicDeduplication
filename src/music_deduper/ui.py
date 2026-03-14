from __future__ import annotations

import ctypes
from datetime import datetime
from pathlib import Path
import json
import os
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .dedupe import default_backup_dir, default_rule_states, find_duplicate_groups, human_size
from .models import AudioTrack, DuplicateGroup
from .scanner import list_available_roots, scan_audio_files


class MusicDeduperApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("音乐去重助手")
        self._configure_window()

        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.scan_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.tracks: list[AudioTrack] = []
        self.groups: list[DuplicateGroup] = []
        self.rule_states = default_rule_states()
        self.rule_vars: list[tk.BooleanVar] = []

        self.selected_root = tk.StringVar()
        self.status_var = tk.StringVar(value="等待扫描")
        self.summary_var = tk.StringVar(value="插入 SD 卡后选择盘符，开始扫描。")
        self.backup_dir_var = tk.StringVar(value=str(default_backup_dir()))
        self.only_preview_var = tk.BooleanVar(value=False)
        self.track_count_var = tk.StringVar(value="0")
        self.group_count_var = tk.StringVar(value="0")
        self.reclaim_var = tk.StringVar(value="0 B")
        self.duplicate_count_var = tk.StringVar(value="0")
        self.rule_summary_var = tk.StringVar(value="")

        self._build_style()
        self._build_layout()
        self._refresh_rule_summary()
        self._load_roots()
        self.after(150, self._poll_queue)

    def _configure_window(self) -> None:
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(f"{screen_width}x{screen_height}+0+0")
        self.minsize(max(1180, int(screen_width * 0.72)), max(780, int(screen_height * 0.72)))
        if os.name == "nt":
            try:
                self.state("zoomed")
            except tk.TclError:
                pass

    def _build_style(self) -> None:
        self.configure(bg="#f4efe6")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background="#f4efe6")
        style.configure("Panel.TFrame", background="#fbf7f1")
        style.configure("Sidebar.TFrame", background="#f6efe3")
        style.configure("Banner.TFrame", background="#19323c")
        style.configure("Stats.TFrame", background="#ffffff")
        style.configure("Header.TLabel", background="#19323c", foreground="#f6f0dd", font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("BannerText.TLabel", background="#19323c", foreground="#d1e3dc", font=("Microsoft YaHei UI", 10))
        style.configure("PanelTitle.TLabel", background="#fbf7f1", foreground="#1f3a45", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Body.TLabel", background="#fbf7f1", foreground="#48606a", font=("Microsoft YaHei UI", 10))
        style.configure("SidebarText.TLabel", background="#f6efe3", foreground="#4b5f66", font=("Microsoft YaHei UI", 10))
        style.configure("StatValue.TLabel", background="#ffffff", foreground="#17303a", font=("Segoe UI Semibold", 20, "bold"))
        style.configure("StatCaption.TLabel", background="#ffffff", foreground="#6c7f85", font=("Microsoft YaHei UI", 9))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(14, 8), foreground="#ffffff", background="#1d7a64", borderwidth=0)
        style.map("Primary.TButton", background=[("active", "#16624f")])
        style.configure("Secondary.TButton", font=("Microsoft YaHei UI", 10), padding=(12, 7), background="#e9ddd0", foreground="#294149", borderwidth=0)
        style.map("Secondary.TButton", background=[("active", "#d8c6b4")])
        style.configure("Treeview", rowheight=28, font=("Consolas", 10), fieldbackground="#ffffff", background="#ffffff", bordercolor="#d9d0c4")
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), background="#efe5d8", foreground="#284047")
        style.map("Treeview", background=[("selected", "#dbece4")], foreground=[("selected", "#17333b")])
        style.configure("TNotebook", background="#fbf7f1", borderwidth=0)
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 10, "bold"), padding=(12, 8), background="#e7dccf")
        style.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", "#18343c")])
        style.configure("TCombobox", padding=6)
        style.configure("TEntry", padding=6)
        style.configure("TCheckbutton", background="#f6efe3", foreground="#3b4d55", font=("Microsoft YaHei UI", 10))
        style.map("TCheckbutton", background=[("active", "#f6efe3")])

    def _build_layout(self) -> None:
        outer = ttk.Frame(self, padding=18, style="App.TFrame")
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(2, weight=1)
        outer.columnconfigure(0, weight=1)

        banner = ttk.Frame(outer, padding=(22, 18), style="Banner.TFrame")
        banner.grid(row=0, column=0, sticky="ew")
        banner.columnconfigure(0, weight=1)
        banner.columnconfigure(1, weight=0)

        left_banner = ttk.Frame(banner, style="Banner.TFrame")
        left_banner.grid(row=0, column=0, sticky="w")
        ttk.Label(left_banner, text="HiFi 随身听音乐去重", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            left_banner,
            text="支持按信息完整度、码率、封面等规则保留最佳文件，并识别歌名与歌手倒置的文件命名。",
            style="BannerText.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        action_bar = ttk.Frame(banner, style="Banner.TFrame")
        action_bar.grid(row=0, column=1, sticky="e")
        ttk.Button(action_bar, text="刷新盘符", style="Secondary.TButton", command=self._load_roots).pack(side="left", padx=(0, 8))
        ttk.Button(action_bar, text="开始扫描", style="Primary.TButton", command=self.start_scan).pack(side="left", padx=(0, 8))
        ttk.Button(action_bar, text="停止扫描", style="Secondary.TButton", command=self.stop_scan).pack(side="left")

        stats = ttk.Frame(outer, style="App.TFrame")
        stats.grid(row=1, column=0, sticky="ew", pady=(14, 14))
        for index in range(4):
            stats.columnconfigure(index, weight=1)
        self._build_stat_card(stats, 0, "已识别音频", self.track_count_var)
        self._build_stat_card(stats, 1, "重复分组", self.group_count_var)
        self._build_stat_card(stats, 2, "待清理文件", self.duplicate_count_var)
        self._build_stat_card(stats, 3, "预计释放空间", self.reclaim_var)

        body = ttk.PanedWindow(outer, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew")

        sidebar = ttk.Frame(body, padding=16, style="Sidebar.TFrame")
        content = ttk.Frame(body, padding=16, style="Panel.TFrame")
        body.add(sidebar, weight=2)
        body.add(content, weight=5)

        self._build_sidebar(sidebar)
        self._build_content(content)

    def _build_stat_card(self, parent: ttk.Frame, column: int, title: str, value_var: tk.StringVar) -> None:
        card = ttk.Frame(parent, padding=(18, 14), style="Stats.TFrame")
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 10, 0))
        ttk.Label(card, textvariable=value_var, style="StatValue.TLabel").pack(anchor="w")
        ttk.Label(card, text=title, style="StatCaption.TLabel").pack(anchor="w", pady=(4, 0))

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        source_card = ttk.Frame(parent, padding=14, style="Sidebar.TFrame")
        source_card.grid(row=0, column=0, sticky="ew")
        source_card.columnconfigure(1, weight=1)
        ttk.Label(source_card, text="扫描来源", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(source_card, text="选择 SD 卡盘符或音乐目录", style="SidebarText.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 10))
        ttk.Label(source_card, text="盘符", style="SidebarText.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 8))
        self.root_combo = ttk.Combobox(source_card, textvariable=self.selected_root, state="readonly")
        self.root_combo.grid(row=2, column=1, sticky="ew")
        ttk.Button(source_card, text="文件夹", style="Secondary.TButton", command=self._choose_folder).grid(row=2, column=2, padx=(8, 0))

        rule_card = ttk.Frame(parent, padding=14, style="Sidebar.TFrame")
        rule_card.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        ttk.Label(rule_card, text="保留规则优先级", style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Label(rule_card, text="勾选启用，顺序越靠上优先级越高。", style="SidebarText.TLabel").pack(anchor="w", pady=(4, 10))
        self.rule_rows = ttk.Frame(rule_card, style="Sidebar.TFrame")
        self.rule_rows.pack(fill="x")
        self._render_rule_rows()

        setting_card = ttk.Frame(parent, padding=14, style="Sidebar.TFrame")
        setting_card.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(setting_card, text="执行设置", style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Checkbutton(setting_card, text="仅预览，不移动重复文件", variable=self.only_preview_var).pack(anchor="w", pady=(8, 8))
        ttk.Label(setting_card, text="备份目录", style="SidebarText.TLabel").pack(anchor="w")
        ttk.Entry(setting_card, textvariable=self.backup_dir_var).pack(fill="x", pady=(6, 6))
        ttk.Button(setting_card, text="选择备份目录", style="Secondary.TButton", command=self._choose_backup_dir).pack(anchor="w")

        parent.rowconfigure(1, weight=1)

    def _build_content(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(3, weight=1)
        parent.columnconfigure(0, weight=1)

        status_card = ttk.Frame(parent, padding=14, style="Panel.TFrame")
        status_card.grid(row=0, column=0, sticky="ew")
        status_card.columnconfigure(0, weight=1)
        ttk.Label(status_card, textvariable=self.status_var, style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(status_card, textvariable=self.summary_var, style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

        toolbar = ttk.Frame(parent, style="Panel.TFrame")
        toolbar.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        ttk.Button(toolbar, text="按当前规则重新排序", style="Secondary.TButton", command=self.recompute_groups).pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="导出报告", style="Secondary.TButton", command=self.export_report).pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="执行去重", style="Primary.TButton", command=self.execute_dedupe).pack(side="left")

        hint = ttk.Frame(parent, padding=(14, 10), style="Panel.TFrame")
        hint.grid(row=2, column=0, sticky="ew")
        ttk.Label(hint, textvariable=self.rule_summary_var, style="Body.TLabel", wraplength=980, justify="left").pack(anchor="w")

        notebook = ttk.Notebook(parent)
        notebook.grid(row=3, column=0, sticky="nsew", pady=(12, 0))

        result_tab = ttk.Frame(notebook, padding=10, style="Panel.TFrame")
        log_tab = ttk.Frame(notebook, padding=10, style="Panel.TFrame")
        notebook.add(result_tab, text="重复结果")
        notebook.add(log_tab, text="扫描日志")

        result_tab.rowconfigure(0, weight=1)
        result_tab.columnconfigure(0, weight=1)
        columns = ("action", "title", "artist", "album", "bitrate", "cover", "meta", "size", "path")
        self.tree = ttk.Treeview(result_tab, columns=columns, show="tree headings")
        self.tree.heading("#0", text="重复组")
        self.tree.heading("action", text="建议")
        self.tree.heading("title", text="标题")
        self.tree.heading("artist", text="歌手")
        self.tree.heading("album", text="专辑")
        self.tree.heading("bitrate", text="kbps")
        self.tree.heading("cover", text="封面")
        self.tree.heading("meta", text="信息")
        self.tree.heading("size", text="大小")
        self.tree.heading("path", text="相对路径")
        self.tree.column("#0", width=210, anchor="w")
        self.tree.column("action", width=90, anchor="center")
        self.tree.column("title", width=210, anchor="w")
        self.tree.column("artist", width=120, anchor="w")
        self.tree.column("album", width=130, anchor="w")
        self.tree.column("bitrate", width=70, anchor="center")
        self.tree.column("cover", width=60, anchor="center")
        self.tree.column("meta", width=70, anchor="center")
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("path", width=420, anchor="w")
        self.tree.tag_configure("keep", background="#edf7f1", foreground="#1b5a43")
        self.tree.tag_configure("duplicate", background="#fff1e4", foreground="#8a4a12")
        self.tree.tag_configure("group", background="#f6f0e7", foreground="#26424a")
        self.tree.grid(row=0, column=0, sticky="nsew")
        result_scroll = ttk.Scrollbar(result_tab, orient="vertical", command=self.tree.yview)
        result_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=result_scroll.set)

        log_tab.rowconfigure(0, weight=1)
        log_tab.columnconfigure(0, weight=1)
        self.log = tk.Text(log_tab, wrap="word", bg="#fdfcf9", relief="flat", font=("Consolas", 10), foreground="#42565d")
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_tab, orient="vertical", command=self.log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)

    def _render_rule_rows(self) -> None:
        for child in self.rule_rows.winfo_children():
            child.destroy()

        self.rule_vars = []
        for index, state in enumerate(self.rule_states):
            row = ttk.Frame(self.rule_rows, padding=(10, 8), style="Sidebar.TFrame")
            row.pack(fill="x", pady=4)
            enabled_var = tk.BooleanVar(value=state.enabled)
            self.rule_vars.append(enabled_var)
            enabled_var.trace_add("write", lambda *_args, idx=index, var=enabled_var: self._toggle_rule(idx, var.get()))
            ttk.Checkbutton(row, variable=enabled_var).grid(row=0, column=0, rowspan=2, sticky="nw")
            ttk.Label(row, text=f"{index + 1}. {state.label}", style="PanelTitle.TLabel").grid(row=0, column=1, sticky="w")
            ttk.Label(row, text=state.description, style="SidebarText.TLabel").grid(row=1, column=1, sticky="w", pady=(3, 0))
            ttk.Button(row, text="上移", style="Secondary.TButton", command=lambda idx=index: self._move_rule(idx, -1)).grid(row=0, column=2, rowspan=2, padx=(8, 4))
            ttk.Button(row, text="下移", style="Secondary.TButton", command=lambda idx=index: self._move_rule(idx, 1)).grid(row=0, column=3, rowspan=2)
            row.columnconfigure(1, weight=1)

    def _load_roots(self) -> None:
        roots = list_available_roots()
        self.root_combo["values"] = roots
        if roots and not self.selected_root.get():
            self.selected_root.set(roots[0])
        self._append_log("已刷新可扫描盘符。")

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="选择音乐目录")
        if selected:
            self.selected_root.set(selected)

    def _choose_backup_dir(self) -> None:
        selected = filedialog.askdirectory(title="选择备份目录")
        if selected:
            self.backup_dir_var.set(selected)

    def _toggle_rule(self, index: int, enabled: bool) -> None:
        self.rule_states[index].enabled = enabled
        self._refresh_rule_summary()
        if self.tracks:
            self.recompute_groups()

    def _move_rule(self, index: int, direction: int) -> None:
        new_index = index + direction
        if not 0 <= new_index < len(self.rule_states):
            return
        self.rule_states[index], self.rule_states[new_index] = self.rule_states[new_index], self.rule_states[index]
        self._render_rule_rows()
        self._refresh_rule_summary()
        if self.tracks:
            self.recompute_groups()

    def _refresh_rule_summary(self) -> None:
        enabled_rules = [state.label for state in self.rule_states if state.enabled]
        if enabled_rules:
            rule_order = " > ".join(enabled_rules)
        else:
            rule_order = "未勾选时将回退到默认规则：信息更完整优先 > 码率更高优先 > 带封面优先"
        self.rule_summary_var.set(
            "判重逻辑：优先使用标题 + 歌手，标签不足时回退到文件名；已支持“菊花台-周杰伦”和“周杰伦-菊花台”这类倒置命名识别。"
            f" 当前保留优先级：{rule_order}。结果区中绿色为建议保留，橙色为建议移走，执行去重时文件会移动到备份目录。"
        )

    def start_scan(self) -> None:
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showinfo("扫描中", "当前已有扫描任务在运行。")
            return
        selected = self.selected_root.get().strip()
        if not selected:
            messagebox.showwarning("未选择目录", "请先选择 SD 卡盘符或音乐目录。")
            return

        root = Path(selected)
        if not root.exists():
            messagebox.showerror("路径不存在", f"无法访问 {root}")
            return

        self.stop_event = threading.Event()
        self.status_var.set("正在扫描")
        self.summary_var.set(f"扫描目录: {root}")
        self.tracks = []
        self.groups = []
        self._update_stats()
        self._clear_tree()
        self._append_log(f"开始扫描: {root}")
        self.scan_thread = threading.Thread(target=self._scan_worker, args=(root,), daemon=True)
        self.scan_thread.start()

    def stop_scan(self) -> None:
        if self.scan_thread and self.scan_thread.is_alive():
            self.stop_event.set()
            self._append_log("已请求停止扫描。")

    def _scan_worker(self, root: Path) -> None:
        try:
            tracks = scan_audio_files(root, progress=lambda message: self.queue.put(("log", message)), stop_event=self.stop_event)
            self.queue.put(("scan_complete", tracks))
        except Exception as exc:  # pragma: no cover
            self.queue.put(("error", str(exc)))

    def recompute_groups(self) -> None:
        if not self.tracks:
            self.groups = []
            self._clear_tree()
            self._update_stats()
            self.summary_var.set("尚未开始扫描")
            return
        self.groups = find_duplicate_groups(self.tracks, self.rule_states)
        self._refresh_tree()
        self._update_stats()
        duplicate_count = sum(len(group.duplicate_tracks) for group in self.groups)
        reclaimable = sum(group.reclaimable_bytes for group in self.groups)
        self.summary_var.set(
            f"音频总数 {len(self.tracks)} 首，发现 {len(self.groups)} 组重复，建议移走 {duplicate_count} 首，可释放 {human_size(reclaimable)}。"
        )
        self.status_var.set("扫描完成，已生成保留建议")
        self._append_log("已根据当前规则更新保留建议。")

    def _update_stats(self) -> None:
        duplicate_count = sum(len(group.duplicate_tracks) for group in self.groups)
        reclaimable = sum(group.reclaimable_bytes for group in self.groups)
        self.track_count_var.set(str(len(self.tracks)))
        self.group_count_var.set(str(len(self.groups)))
        self.duplicate_count_var.set(str(duplicate_count))
        self.reclaim_var.set(human_size(reclaimable))

    def export_report(self) -> None:
        if not self.groups:
            messagebox.showinfo("暂无结果", "请先完成扫描。")
            return
        reports_dir = Path.cwd() / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / f"dedupe_report_{datetime.now():%Y%m%d_%H%M%S}.json"
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "scan_root": self.selected_root.get(),
            "rules": [{"label": state.label, "enabled": state.enabled} for state in self.rule_states],
            "groups": [
                {
                    "key": group.key,
                    "keep": group.keep_track.relative_path,
                    "duplicates": [track.relative_path for track in group.duplicate_tracks],
                    "reclaimable_bytes": group.reclaimable_bytes,
                }
                for group in self.groups
            ],
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._append_log(f"已导出报告: {report_path}")
        messagebox.showinfo("导出完成", f"报告已保存到\n{report_path}")

    def execute_dedupe(self) -> None:
        if not self.groups:
            messagebox.showinfo("暂无可执行项", "请先完成扫描并生成建议。")
            return
        duplicate_count = sum(len(group.duplicate_tracks) for group in self.groups)
        if duplicate_count == 0:
            messagebox.showinfo("无需处理", "没有重复文件需要清理。")
            return
        if self.only_preview_var.get():
            messagebox.showinfo("预览模式", "当前勾选了“仅预览”，不会执行移动。")
            return

        if not messagebox.askyesno("确认去重", f"将把 {duplicate_count} 首重复文件移到备份目录，是否继续？"):
            return

        backup_root = Path(self.backup_dir_var.get()).expanduser()
        try:
            backup_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("备份目录不可用", str(exc))
            return

        moved = 0
        timestamp_root = backup_root / f"backup_{datetime.now():%Y%m%d_%H%M%S}"
        timestamp_root.mkdir(parents=True, exist_ok=True)

        for group in self.groups:
            for track in group.duplicate_tracks:
                destination = timestamp_root / track.relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                final_destination = self._dedupe_destination(destination)
                shutil.move(str(track.path), str(final_destination))
                moved += 1
                self._append_log(f"已移动重复文件: {track.relative_path} -> {final_destination}")

        self.status_var.set("去重完成")
        self._append_log(f"去重执行完成，共移动 {moved} 首文件。")
        messagebox.showinfo("去重完成", f"已移动 {moved} 首重复文件到\n{timestamp_root}")
        self.tracks = [track for track in self.tracks if track.path.exists()]
        self.recompute_groups()

    def _dedupe_destination(self, destination: Path) -> Path:
        if not destination.exists():
            return destination
        index = 1
        while True:
            candidate = destination.with_stem(f"{destination.stem}_{index}")
            if not candidate.exists():
                return candidate
            index += 1

    def _refresh_tree(self) -> None:
        self._clear_tree()
        for index, group in enumerate(self.groups, start=1):
            parent_id = self.tree.insert(
                "",
                "end",
                text=f"重复组 {index}",
                values=(
                    f"保留 1 / 移走 {len(group.duplicate_tracks)}",
                    group.keep_track.display_title,
                    group.keep_track.display_artist,
                    group.keep_track.display_album,
                    group.keep_track.bitrate_kbps or "-",
                    "是" if group.keep_track.has_cover else "否",
                    group.keep_track.metadata_filled_count,
                    human_size(group.reclaimable_bytes),
                    group.key,
                ),
                open=index <= 10,
                tags=("group",),
            )
            for track in group.tracks:
                is_keep = track.path == group.keep_track.path
                self.tree.insert(
                    parent_id,
                    "end",
                    text="保留" if is_keep else "重复",
                    values=(
                        "保留" if is_keep else "移走",
                        track.display_title,
                        track.display_artist,
                        track.display_album,
                        track.bitrate_kbps or "-",
                        "是" if track.has_cover else "否",
                        track.metadata_filled_count,
                        human_size(track.size_bytes),
                        track.relative_path,
                    ),
                    tags=(("keep",) if is_keep else ("duplicate",)),
                )

    def _clear_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _append_log(self, message: str) -> None:
        self.log.insert("end", f"[{datetime.now():%H:%M:%S}] {message}\n")
        self.log.see("end")

    def _poll_queue(self) -> None:
        try:
            while True:
                event, payload = self.queue.get_nowait()
                if event == "log":
                    self._append_log(str(payload))
                elif event == "scan_complete":
                    self.tracks = payload
                    self.recompute_groups()
                elif event == "error":
                    self.status_var.set("扫描失败")
                    self._append_log(f"错误: {payload}")
                    messagebox.showerror("执行失败", str(payload))
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)



def launch_app() -> None:
    configure_dpi_awareness()
    app = MusicDeduperApp()
    app.mainloop()



def configure_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
