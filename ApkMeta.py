import os
import csv
import hashlib
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ----------------- APK & HASH 逻辑 -----------------


try:
    from androguard.core.apk import APK
except ImportError:
    # 如果直接 import 就报错，先弹个窗再抛异常
    root_tmp = tk.Tk()
    root_tmp.withdraw()
    messagebox.showerror("错误", "未安装 androguard\n\n请先运行：\npip install androguard")
    root_tmp.destroy()
    raise


def calc_hashes(filepath: str):
    """计算文件的 MD5 / SHA1 / SHA256"""
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()

    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)

    return md5.hexdigest(), sha1.hexdigest(), sha256.hexdigest()


def parse_single_apk(apk_path: str) -> dict:
    """解析单个 APK，返回一个 dict，字段名与表格列对应"""
    apk = APK(apk_path)

    package_name = apk.get_package() or ""
    app_name = apk.get_app_name() or ""
    version_name = apk.get_androidversion_name() or ""
    version_code = apk.get_androidversion_code() or ""

    md5, sha1, sha256 = calc_hashes(apk_path)

    return {
        "文件名": os.path.basename(apk_path),
        "文件路径": apk_path,
        "包名": package_name,
        "应用名": app_name,
        "版本名称": version_name,
        "版本号": str(version_code) if version_code is not None else "",
        "MD5": md5,
        "SHA1": sha1,
        "SHA256": sha256,
    }


# ----------------- GUI 逻辑 -----------------


class ApkGuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ApkMeta  APK元信息快速查看工具")

        # 尝试用稍微好看一点的主题
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # 启动时尽量最大化（Windows）
        try:
            self.root.state("zoomed")
        except Exception:
            # 其他平台就给个稍微大一点的默认尺寸
            self.root.geometry("1200x700")

        # 允许缩放
        self.root.minsize(900, 500)

        # 用于批量解析的队列
        self._batch_files = None
        self._batch_index = 0

        self._build_ui()
        self._build_context_menu()

    # ---------- UI 构建 ----------

    def _build_ui(self):
        # 顶部按钮区域
        top_frame = ttk.Frame(self.root)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        btn_file = ttk.Button(
            top_frame, text="选择单个 APK", width=16, command=self.browse_file
        )
        btn_dir = ttk.Button(
            top_frame, text="选择文件夹（批量）", width=18, command=self.browse_folder
        )
        btn_export = ttk.Button(
            top_frame, text="导出 CSV", width=14, command=self.export_csv
        )

        btn_file.pack(side=tk.LEFT, padx=5)
        btn_dir.pack(side=tk.LEFT, padx=5)
        btn_export.pack(side=tk.LEFT, padx=5)

        # 表格 + 滚动条区域
        table_frame = ttk.Frame(self.root)
        table_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        # 滚动条
        self.scrollbar_y = ttk.Scrollbar(table_frame, orient=tk.VERTICAL)
        self.scrollbar_x = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL)

        # 表格
        self.table_columns = [
            "文件名",
            "文件路径",
            "包名",
            "应用名",
            "版本名称",
            "版本号",
            "MD5",
            "SHA1",
            "SHA256",
        ]

        self.tree = ttk.Treeview(
            table_frame,
            columns=self.table_columns,
            show="headings",
            yscrollcommand=self.scrollbar_y.set,
            xscrollcommand=self.scrollbar_x.set,
        )

        self.scrollbar_y.config(command=self.tree.yview)
        self.scrollbar_x.config(command=self.tree.xview)

        self.scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 设置表头 & 列宽
        for col in self.table_columns:
            self.tree.heading(col, text=col)
            # 简单按照内容大致区分列宽
            base_width = 120
            if col in ("文件名", "应用名", "包名", "版本名称"):
                base_width = 180
            elif col == "文件路径":
                base_width = 260
            elif col in ("MD5", "SHA1", "SHA256"):
                base_width = 260
            self.tree.column(col, width=base_width, anchor="w", stretch=False)

        # 事件绑定：双击复制单元格
        self.tree.bind("<Double-1>", self.on_double_click)
        # 右键弹菜单
        self.tree.bind("<Button-3>", self.on_right_click)

        # 底部状态栏
        self.status_var = tk.StringVar(value="准备就绪")
        status_bar = ttk.Label(
            self.root,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor="w",
            padding=(5, 2),
        )
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _build_context_menu(self):
        # 右键菜单
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="复制该单元格", command=self.copy_current_cell)
        self.menu.add_command(label="复制整行", command=self.copy_current_row)

        # 用于记录右键时定位的 cell
        self._rclick_row = None
        self._rclick_col = None

    # ---------- 交互逻辑 ----------

    def on_double_click(self, event):
        """双击单元格：复制内容"""
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not row_id or not col_id:
            return

        col_index = int(col_id.replace("#", "")) - 1
        values = self.tree.item(row_id, "values")
        if col_index < 0 or col_index >= len(values):
            return

        value = str(values[col_index])
        self._copy_to_clipboard(value)
        col_name = self.table_columns[col_index]
        self.status_var.set(f"已复制：[{col_name}] {value}")

    def on_right_click(self, event):
        """右键弹出菜单，并记录当前 cell"""
        # 在 Windows 上右键不会自动选中行，这里手动处理
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)

        if not row_id or not col_id:
            return

        self.tree.selection_set(row_id)
        self.tree.focus(row_id)

        self._rclick_row = row_id
        self._rclick_col = col_id

        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _copy_to_clipboard(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def copy_current_cell(self):
        """右键菜单：复制当前单元格"""
        row_id = self._rclick_row or self.tree.focus()
        col_id = self._rclick_col
        if not row_id or not col_id:
            return

        col_index = int(col_id.replace("#", "")) - 1
        values = self.tree.item(row_id, "values")
        if col_index < 0 or col_index >= len(values):
            return

        value = str(values[col_index])
        self._copy_to_clipboard(value)
        col_name = self.table_columns[col_index]
        self.status_var.set(f"已复制单元格：[{col_name}] {value}")

    def copy_current_row(self):
        """右键菜单：复制整行（以 Tab 分隔）"""
        row_id = self._rclick_row or self.tree.focus()
        if not row_id:
            return

        values = self.tree.item(row_id, "values")
        text = "\t".join(str(v) for v in values)
        self._copy_to_clipboard(text)
        self.status_var.set("已复制整行")

    # ---------- 文件选择 & 解析 ----------

    def browse_file(self):
        """选择单个 APK 解析"""
        apk_path = filedialog.askopenfilename(
            title="选择 APK 文件",
            filetypes=[("APK 文件", "*.apk"), ("所有文件", "*.*")],
        )
        if not apk_path:
            return

        try:
            data = parse_single_apk(apk_path)
        except Exception as e:
            messagebox.showerror("错误", f"解析 APK 失败：\n{apk_path}\n\n{e}")
            return

        self._insert_row(data)
        self.status_var.set(f"解析完成：{apk_path}")

    def browse_folder(self):
        """选择文件夹，批量解析 APK（使用 after 分批处理，避免界面卡死）"""
        folder = filedialog.askdirectory(title="选择包含 APK 的文件夹")
        if not folder:
            return

        apk_files = []
        for root_dir, _, files in os.walk(folder):
            for name in files:
                if name.lower().endswith(".apk"):
                    apk_files.append(os.path.join(root_dir, name))

        if not apk_files:
            messagebox.showinfo("提示", "该目录下未找到 APK 文件")
            return

        # 清空旧数据
        self.tree.delete(*self.tree.get_children())

        self._batch_files = apk_files
        self._batch_index = 0

        total = len(apk_files)
        self.status_var.set(f"开始解析，共 {total} 个 APK...")

        # 启动异步批量解析
        self._process_next_apk_in_batch()

    def _process_next_apk_in_batch(self):
        """通过 root.after 分批解析，避免卡死"""
        if not self._batch_files:
            return

        total = len(self._batch_files)
        if self._batch_index >= total:
            self.status_var.set(f"解析完成，共解析 {total} 个 APK")
            # 清理引用
            self._batch_files = None
            self._batch_index = 0
            return

        apk_path = self._batch_files[self._batch_index]

        try:
            data = parse_single_apk(apk_path)
            self._insert_row(data)
        except Exception as e:
            # 遇到坏包就跳过
            print(f"解析失败：{apk_path} -> {e}")

        self._batch_index += 1
        self.status_var.set(
            f"正在解析 {self._batch_index}/{total}：{apk_path}"
        )

        # 关键：给事件循环一点空隙
        self.root.after(10, self._process_next_apk_in_batch)

    # ---------- 表格 & 导出 ----------

    def _insert_row(self, data_dict: dict):
        values = [data_dict.get(col, "") for col in self.table_columns]
        self.tree.insert("", "end", values=values)

    def export_csv(self):
        """导出当前表格内容为 CSV"""
        if not self.tree.get_children():
            messagebox.showinfo("提示", "没有数据可以导出")
            return

        export_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
            title="保存为 CSV 文件",
        )
        if not export_path:
            return

        try:
            # 使用 UTF-8 BOM，方便 Excel 识别中文
            with open(export_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(self.table_columns)
                for item_id in self.tree.get_children():
                    values = self.tree.item(item_id, "values")
                    writer.writerow(values)

            self.status_var.set(f"CSV 已导出：{export_path}")
            messagebox.showinfo("成功", f"导出成功：\n{export_path}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败：{e}")


def main():
    root = tk.Tk()
    app = ApkGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
