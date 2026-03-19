#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from youtube_multi_token_manager import (
    collect_all_channels,
    disable_channel,
    export_chinese_report,
    get_default_paths,
    list_channels,
    save_authorized_channel,
)


class YouTubeManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("YouTube 多频道收益采集工具")
        self.root.geometry("1120x720")
        self.root.minsize(980, 620)

        defaults = get_default_paths()
        # 如果是打包后的程序，显示友好的路径名称
        if getattr(sys, 'frozen', False):
            self.client_secrets_var = tk.StringVar(value="[内置] client_secrets.json")
            self.token_dir_var = tk.StringVar(value="[内置] tokens")
            self.registry_var = tk.StringVar(value="[内置] authorized_channels.xlsx")
        else:
            self.client_secrets_var = tk.StringVar(value=str(defaults["client_secrets"]))
            self.token_dir_var = tk.StringVar(value=str(defaults["token_dir"]))
            self.registry_var = tk.StringVar(value=str(defaults["registry"]))
        self.output_var = tk.StringVar(value=str(defaults["desktop_output"]))
        self.alias_var = tk.StringVar()
        self.port_var = tk.StringVar(value="8768")
        self.status_var = tk.StringVar(value="就绪")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.filter_channels())
        self.full_registry = pd.DataFrame()  # 存储完整的频道列表

        self.tree: ttk.Treeview
        self.log_text: tk.Text
        self.progress_bar: ttk.Progressbar

        self._build_ui()
        self.refresh_registry()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)

        top = ttk.LabelFrame(container, text="配置")
        top.pack(fill="x")

        self._add_path_row(top, "OAuth 凭证", self.client_secrets_var, 0, file_mode=True)
        self._add_path_row(top, "Token 目录", self.token_dir_var, 1, dir_mode=True)
        self._add_path_row(top, "注册表", self.registry_var, 2, file_mode=True, save_mode=True)
        self._add_path_row(top, "输出文件", self.output_var, 3, file_mode=True, save_mode=True)

        action_frame = ttk.LabelFrame(container, text="操作")
        action_frame.pack(fill="x", pady=(10, 0))

        ttk.Label(action_frame, text="频道别名").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        ttk.Entry(action_frame, textvariable=self.alias_var, width=24).grid(row=0, column=1, padx=8, pady=8, sticky="w")
        ttk.Label(action_frame, text="授权端口").grid(row=0, column=2, padx=8, pady=8, sticky="w")
        ttk.Entry(action_frame, textvariable=self.port_var, width=10).grid(row=0, column=3, padx=8, pady=8, sticky="w")

        ttk.Button(action_frame, text="授权当前频道", command=self.authorize_channel).grid(row=0, column=4, padx=8, pady=8)
        ttk.Button(action_frame, text="刷新频道列表", command=self.refresh_registry).grid(row=0, column=5, padx=8, pady=8)
        ttk.Button(action_frame, text="批量采集数据", command=self.collect_data).grid(row=0, column=6, padx=8, pady=8)
        ttk.Button(action_frame, text="生成中文报表", command=self.export_chinese).grid(row=0, column=7, padx=8, pady=8)

        ttk.Button(action_frame, text="删除选中频道", command=self.disable_selected).grid(row=1, column=4, padx=8, pady=8)
        ttk.Button(action_frame, text="清理已停用频道", command=self.cleanup_disabled).grid(row=1, column=5, padx=8, pady=8)
        ttk.Button(action_frame, text="打开输出文件", command=self.open_output).grid(row=1, column=6, padx=8, pady=8)
        ttk.Button(action_frame, text="打开注册表", command=self.open_registry).grid(row=1, column=7, padx=8, pady=8)

        # 搜索框放在操作和列表之间
        search_frame = ttk.Frame(container)
        search_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(search_frame, text="🔍 搜索频道:").pack(side="left", padx=(0, 8))
        ttk.Entry(search_frame, textvariable=self.search_var, width=60).pack(side="left", fill="x", expand=True)

        table_frame = ttk.LabelFrame(container, text="已授权频道")
        table_frame.pack(fill="both", expand=True, pady=(10, 0))

        columns = ("channel_title", "channel_id", "alias", "status", "updated_at")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        headers = {
            "channel_title": "频道名称",
            "channel_id": "频道ID",
            "alias": "别名",
            "status": "状态",
            "updated_at": "更新时间",
        }
        widths = {
            "channel_title": 260,
            "channel_id": 220,
            "alias": 180,
            "status": 100,
            "updated_at": 180,
        }
        for column in columns:
            self.tree.heading(column, text=headers[column])
            self.tree.column(column, width=widths[column], anchor="w")

        scrollbar_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar_x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(container, text="日志")
        log_frame.pack(fill="both", expand=False, pady=(10, 0))
        self.log_text = tk.Text(log_frame, height=6, wrap="word")
        self.log_text.pack(fill="both", expand=True)

        bottom = ttk.Frame(container)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left")
        self.progress_bar = ttk.Progressbar(bottom, mode="determinate", length=300)
        self.progress_bar.pack(side="right", padx=(10, 0))

    def _add_path_row(
        self,
        parent: ttk.LabelFrame,
        label: str,
        variable: tk.StringVar,
        row: int,
        file_mode: bool = False,
        dir_mode: bool = False,
        save_mode: bool = False,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, padx=8, pady=6, sticky="w")
        ttk.Entry(parent, textvariable=variable, width=100).grid(row=row, column=1, padx=8, pady=6, sticky="ew")
        ttk.Button(
            parent,
            text="浏览",
            command=lambda: self._browse(variable, file_mode=file_mode, dir_mode=dir_mode, save_mode=save_mode),
        ).grid(row=row, column=2, padx=8, pady=6)
        parent.columnconfigure(1, weight=1)

    def _browse(self, variable: tk.StringVar, file_mode: bool, dir_mode: bool, save_mode: bool) -> None:
        current = variable.get().strip()
        initial_dir = str(Path(current).parent) if current else os.path.expanduser("~")
        if dir_mode:
            value = filedialog.askdirectory(initialdir=initial_dir)
        elif save_mode:
            value = filedialog.asksaveasfilename(initialdir=initial_dir, defaultextension=".xlsx")
        else:
            value = filedialog.askopenfilename(initialdir=initial_dir)
        if value:
            variable.set(value)

    def _get_path_or_default(self, var: tk.StringVar, default_key: str) -> Path:
        value = var.get().strip()
        if value.startswith("[内置]") or not value:
            return get_default_paths()[default_key]
        return Path(value)

    def log(self, message: str) -> None:
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.status_var.set(message)

    def run_async(self, target, start_message: str) -> None:
        self.log(start_message)

        def runner() -> None:
            try:
                target()
            except Exception as exc:
                error_text = f"{type(exc).__name__}: {exc}"
                self.root.after(0, lambda: self.log(error_text))
                self.root.after(0, lambda: messagebox.showerror("出错了", error_text))
                self.root.after(0, lambda: self.log(traceback.format_exc()))

        threading.Thread(target=runner, daemon=True).start()

    def authorize_channel(self) -> None:
        def job() -> None:
            alias = self.alias_var.get().strip() or None
            port = int(self.port_var.get().strip() or "8768")
            row = save_authorized_channel(
                client_secrets=self._get_path_or_default(self.client_secrets_var, "client_secrets"),
                token_dir=self._get_path_or_default(self.token_dir_var, "token_dir"),
                registry_path=self._get_path_or_default(self.registry_var, "registry"),
                alias=alias,
                force_reauth=True,
                port=port,
            )
            self.root.after(0, self.refresh_registry)
            self.root.after(0, lambda: self.log(f"授权成功：{row['channel_title']}"))

        self.run_async(job, "正在启动浏览器授权...")

    def refresh_registry(self) -> None:
        try:
            self.full_registry = list_channels(self._get_path_or_default(self.registry_var, "registry"))
        except Exception as exc:
            self.log(f"读取注册表失败：{exc}")
            return

        if self.full_registry.empty:
            for item in self.tree.get_children():
                self.tree.delete(item)
            self.log("当前还没有已授权频道。")
            return

        self.filter_channels()
        self.log(f"已加载 {len(self.full_registry)} 个频道。")

    def filter_channels(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        if self.full_registry.empty:
            return

        search_text = self.search_var.get().strip().lower()
        df = self.full_registry

        if search_text:
            df = df[
                df["channel_title"].astype(str).str.lower().str.contains(search_text, na=False) |
                df["alias"].astype(str).str.lower().str.contains(search_text, na=False) |
                df["channel_id"].astype(str).str.lower().str.contains(search_text, na=False)
            ]

        for _, row in df.iterrows():
            status = row.get("status", "")
            item_id = self.tree.insert(
                "",
                "end",
                values=(
                    row.get("channel_title", ""),
                    row.get("channel_id", ""),
                    row.get("alias", ""),
                    status,
                    row.get("updated_at", ""),
                ),
            )
            if status == "已停用":
                self.tree.item(item_id, tags=("disabled",))

        self.tree.tag_configure("disabled", foreground="gray")

    def collect_data(self) -> None:
        def job() -> None:
            def update_progress(current, total):
                progress = (current / total) * 100
                self.root.after(0, lambda: self.progress_bar.config(value=progress))
                self.root.after(0, lambda: self.status_var.set(f"采集中 {current}/{total}"))

            self.root.after(0, lambda: self.progress_bar.config(value=0))

            result = collect_all_channels(
                client_secrets=self._get_path_or_default(self.client_secrets_var, "client_secrets"),
                token_dir=self._get_path_or_default(self.token_dir_var, "token_dir"),
                registry_path=self._get_path_or_default(self.registry_var, "registry"),
                output_path=Path(self.output_var.get().strip()),
                progress_callback=update_progress,
            )
            success_count = int((result["status"] == "成功").sum()) if not result.empty else 0
            failed_count = len(result) - success_count

            self.root.after(0, lambda: self.progress_bar.config(value=0))
            self.root.after(0, lambda: self.log(f"采集完成：成功 {success_count} / 总计 {len(result)}"))

            # 显示失败频道列表
            if failed_count > 0:
                failed_rows = result[result["status"] != "成功"]
                failed_list = []
                for _, row in failed_rows.iterrows():
                    channel = row.get("channel_title", "") or row.get("alias", "") or "未知频道"
                    status = row.get("status", "未知错误")
                    failed_list.append(f"• {channel} ({status})")

                failed_msg = f"采集完成！\n\n成功：{success_count}\n失败：{failed_count}\n\n失败的频道：\n" + "\n".join(failed_list[:10])
                if len(failed_list) > 10:
                    failed_msg += f"\n... 还有 {len(failed_list) - 10} 个"

                self.root.after(0, lambda: messagebox.showwarning("采集完成", failed_msg))
            else:
                self.root.after(0, lambda: messagebox.showinfo("采集完成", f"全部成功！\n已输出到：\n{Path(self.output_var.get().strip())}"))

        self.run_async(job, "正在批量采集数据...")

    def export_chinese(self) -> None:
        def job() -> None:
            output_path = Path(self.output_var.get().strip())
            chinese_path = output_path.with_name(output_path.stem + "_cn.xlsx")
            export_chinese_report(output_path, chinese_path)
            self.root.after(0, lambda: self.log(f"中文报表已生成：{chinese_path}"))
            self.root.after(0, lambda: messagebox.showinfo("完成", f"中文报表已生成：\n{chinese_path}"))

        self.run_async(job, "正在生成中文报表...")

    def disable_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中一个频道。")
            return

        item = selected[0]
        values = self.tree.item(item, "values")
        identifier = str(values[1]).strip() or str(values[0]).strip()
        if not identifier:
            messagebox.showwarning("提示", "无法识别选中频道。")
            return

        if not messagebox.askyesno("确认", "确定要停用这个频道吗？"):
            return

        def job() -> None:
            defaults = get_default_paths()
            result = disable_channel(
                registry_path=self._get_path_or_default(self.registry_var, "registry"),
                identifier=identifier,
                move_token=False,
                inactive_dir=defaults["inactive_dir"],
            )
            self.root.after(0, self.refresh_registry)
            self.root.after(0, lambda: self.log(f"已删除：{result['channel_title']}"))

        self.run_async(job, "正在删除频道...")

    def cleanup_disabled(self) -> None:
        if not messagebox.askyesno("确认", "确定要清理所有已停用的频道吗？\n这将从注册表中永久删除这些记录。"):
            return

        def job() -> None:
            registry_path = self._get_path_or_default(self.registry_var, "registry")
            df = list_channels(registry_path)
            disabled = df[df["status"] == "已停用"]

            if disabled.empty:
                self.root.after(0, lambda: self.log("没有已停用的频道需要清理"))
                self.root.after(0, lambda: messagebox.showinfo("提示", "没有已停用的频道"))
                return

            # 删除已停用的记录
            active = df[df["status"] != "已停用"]
            from youtube_multi_token_manager import write_table
            write_table(registry_path, active)

            count = len(disabled)
            self.root.after(0, self.refresh_registry)
            self.root.after(0, lambda: self.log(f"已清理 {count} 个已停用频道"))
            self.root.after(0, lambda: messagebox.showinfo("完成", f"已清理 {count} 个已停用频道"))

        self.run_async(job, "正在清理已停用频道...")

    def open_output(self) -> None:
        path = Path(self.output_var.get().strip())
        if not path.exists():
            messagebox.showwarning("提示", "输出文件还不存在，请先采集。")
            return
        webbrowser.open(path.as_uri())

    def open_registry(self) -> None:
        path = Path(self.registry_var.get().strip())
        if not path.exists():
            messagebox.showwarning("提示", "注册表还不存在。")
            return
        webbrowser.open(path.as_uri())


def main() -> None:
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    YouTubeManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
