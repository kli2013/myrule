import os
import random
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import re

# 尝试导入 tkinterdnd2，若失败则禁用拖拽
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    # 定义占位类，保持代码统一
    class TkinterDnD:
        class Tk(tk.Tk):
            pass
    DND_FILES = None

class ImageBrowser:
    def __init__(self, root):
        self.root = root
        self.root.title("图片并排浏览")
        self.root.geometry("1200x700")

        # ---------- 数据 ----------
        self.folder = ""
        self.image_paths = []
        self.batches = []
        self.shuffled_batch_order = []
        self.batch_index = 0
        self.mode = "sequential"
        self.selected_images = []
        self.cols = 3  # 默认列数

        # ---------- 尺寸缓存 ----------
        self.last_width = 0
        self.last_height = 0

        # ---------- 全屏状态 ----------
        self.fullscreen = False
        self._switching = False

        # ---------- 控制栏 ----------
        self.control_frame = tk.Frame(root)
        self.control_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        # 选择按钮
        btn_select = tk.Button(self.control_frame, text="📂 选择", command=self.select_folder)
        btn_select.pack(side=tk.LEFT, padx=2)

        # 递归复选框
        self.recursive_var = tk.BooleanVar(value=False)
        chk_recursive = tk.Checkbutton(self.control_frame, text="包含子文件夹", variable=self.recursive_var)
        chk_recursive.pack(side=tk.LEFT, padx=2)

        # 模式单选
        self.mode_var = tk.StringVar(value="sequential")
        tk.Radiobutton(self.control_frame, text="顺序", variable=self.mode_var,
                       value="sequential", command=self.set_mode).pack(side=tk.LEFT, padx=2)
        tk.Radiobutton(self.control_frame, text="乱序", variable=self.mode_var,
                       value="shuffle", command=self.set_mode).pack(side=tk.LEFT, padx=2)
        tk.Radiobutton(self.control_frame, text="随机", variable=self.mode_var,
                       value="random", command=self.set_mode).pack(side=tk.LEFT, padx=2)

        tk.Label(self.control_frame, text="|").pack(side=tk.LEFT, padx=2)

        tk.Button(self.control_frame, text="◀上一批", command=self.prev_batch, width=7).pack(side=tk.LEFT, padx=2)
        tk.Button(self.control_frame, text="▶下一批", command=self.next_batch, width=7).pack(side=tk.LEFT, padx=2)
        tk.Button(self.control_frame, text="🎲摇一摇", command=self.random_pick, width=7).pack(side=tk.LEFT, padx=2)

        tk.Label(self.control_frame, text="|").pack(side=tk.LEFT, padx=2)

        self.auto_play_var = tk.BooleanVar(value=False)
        chk_auto = tk.Checkbutton(self.control_frame, text="自动播放", variable=self.auto_play_var,
                                  command=self.toggle_auto_play)
        chk_auto.pack(side=tk.LEFT, padx=2)

        tk.Label(self.control_frame, text="间隔(s):").pack(side=tk.LEFT, padx=2)
        self.interval_var = tk.StringVar(value="2.0")
        spin_interval = ttk.Spinbox(self.control_frame, from_=0.5, to=10.0, increment=0.5,
                                    textvariable=self.interval_var, width=5)
        spin_interval.pack(side=tk.LEFT, padx=2)

        # 算法下拉
        self.algo_display = {
            "快速": Image.NEAREST,
            "双线性": Image.BILINEAR,
            "三线性": Image.BICUBIC,
            "最佳": Image.LANCZOS,
        }
        tk.Label(self.control_frame, text="算法:").pack(side=tk.LEFT, padx=2)
        self.algo_var = tk.StringVar(value="最佳")
        algo_combo = ttk.Combobox(self.control_frame, textvariable=self.algo_var,
                                  values=list(self.algo_display.keys()),
                                  state="readonly", width=8)
        algo_combo.pack(side=tk.LEFT, padx=2)
        algo_combo.bind("<<ComboboxSelected>>", self.on_algo_change)

        # 列数
        tk.Label(self.control_frame, text="列数:").pack(side=tk.LEFT, padx=2)
        self.cols_var = tk.StringVar(value="3")
        cols_spin = ttk.Spinbox(self.control_frame, from_=2, to=6, increment=1,
                                 textvariable=self.cols_var, width=4, state="readonly")
        cols_spin.pack(side=tk.LEFT, padx=2)
        cols_spin.bind("<<Increment>>", lambda e: self.root.after(10, self.on_cols_change))
        cols_spin.bind("<<Decrement>>", lambda e: self.root.after(10, self.on_cols_change))
        cols_spin.bind("<FocusOut>", lambda e: self.on_cols_change())

        self.status_label = tk.Label(self.control_frame, text="", font=("Arial", 9), anchor="e")
        self.status_label.pack(side=tk.RIGHT, padx=10)

        # ---------- 图片显示 ----------
        self.image_frame = tk.Frame(root, bg="black")
        self.image_frame.pack(expand=True, fill=tk.BOTH, padx=0, pady=0)
        self.image_label = tk.Label(self.image_frame, bg="black")
        self.image_label.pack(expand=True, fill=tk.BOTH)

        # ---------- 事件绑定 ----------
        self.root.bind("<Configure>", self.on_resize)
        self.root.bind("<Key>", self.on_key_press)
        self.root.bind("<Return>", self.toggle_fullscreen)
        self.root.bind("<Escape>", self.toggle_fullscreen)      # Esc 退出全屏

        # Alt 快捷键切换模式
        self.root.bind("<Alt-Key-1>", lambda e: self.set_mode_by_value("sequential") or "break")
        self.root.bind("<Alt-Key-2>", lambda e: self.set_mode_by_value("shuffle") or "break")
        self.root.bind("<Alt-Key-3>", lambda e: self.set_mode_by_value("random") or "break")
        self.root.bind("<Alt-Key-q>", lambda e: self.on_close() or "break")
        self.root.bind("<Alt-Key-Q>", lambda e: self.on_close() or "break")

        # Alt+4 切换自动播放
        self.root.bind("<Alt-Key-4>", lambda e: chk_auto.invoke() or "break")

        # Ctrl+1~9 设置间隔
        for i in range(1, 10):
            self.root.bind(f"<Control-Key-{i}>", lambda e, sec=i: self.set_interval(sec) or "break")

        # 强制取消置顶
        self.root.attributes('-topmost', False)

        # ---------- 拖拽支持（若可用） ----------
        if DND_AVAILABLE:
            try:
                self.root.drop_target_register(DND_FILES)
                self.root.dnd_bind('<<Drop>>', self.on_drop)
            except Exception as e:
                print("拖拽初始化失败:", e)

        # ---------- 变量 ----------
        self.photo_image = None
        self.resize_job = None
        self.auto_timer = None
        self.auto_interval = 2.0

    # ---------- 拖放回调 ----------
    def on_drop(self, event):
        """处理拖拽文件/文件夹"""
        raw = event.data
        if not raw:
            return
        # 解析路径（Windows 可能用花括号或空格分隔）
        # 使用正则提取所有路径
        paths = re.findall(r'\{[^}]*\}|"[^"]*"|\S+', raw)
        paths = [p.strip('{}"') for p in paths]
        folder = None
        # 优先查找文件夹
        for p in paths:
            if os.path.isdir(p):
                folder = p
                break
        # 若没有文件夹，从第一个图片文件获取所在目录
        if folder is None:
            for p in paths:
                if os.path.isfile(p) and p.lower().endswith(('.jpg','.jpeg','.png','.bmp','.gif','.tiff','.webp')):
                    folder = os.path.dirname(p)
                    break
        if folder and os.path.isdir(folder):
            self.folder = folder
            self.image_paths = self._get_image_files(folder, self.recursive_var.get())
            if len(self.image_paths) < self.cols:
                messagebox.showerror("错误", f"文件夹内图片少于 {self.cols} 张")
                self.image_paths = []
                self.status_label.config(text=f"图片不足 {self.cols} 张")
                return
            self.image_paths.sort()
            self._build_batches()
            self.batch_index = 0
            self.mode = self.mode_var.get()
            self._apply_mode()
            self.status_label.config(text=f"共 {len(self.image_paths)} 张，{len(self.batches)} 批")
            self._update_display(force=True)

    # ---------- 列数变化 ----------
    def on_cols_change(self):
        try:
            cols = int(self.cols_var.get())
            if cols < 2:
                cols = 2
            elif cols > 6:
                cols = 6
            self.cols_var.set(str(cols))
        except ValueError:
            cols = 3
            self.cols_var.set("3")
        self.cols = cols
        if self.image_paths:
            self._build_batches()
            self.batch_index = 0
            self._apply_mode()
            self._update_display(force=True)
        self.root.focus_set()

    # ---------- 设置间隔 ----------
    def set_interval(self, seconds):
        self.interval_var.set(str(seconds))
        if self.auto_play_var.get():
            self._stop_auto_timer()
            self._start_auto_timer()

    # ---------- 算法切换 ----------
    def on_algo_change(self, event):
        self._update_display(force=True)

    # ---------- 模式切换快捷键 ----------
    def set_mode_by_value(self, mode_value):
        self.mode_var.set(mode_value)
        self.root.update_idletasks()
        self.set_mode()

    # ---------- 全屏切换 ----------
    def toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self._switching = True
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
            self.resize_job = None
        self.root.attributes('-fullscreen', self.fullscreen)
        if self.fullscreen:
            self.control_frame.pack_forget()
        else:
            self.control_frame.pack_forget()
            self.image_frame.pack_forget()
            self.control_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
            self.image_frame.pack(expand=True, fill=tk.BOTH, padx=0, pady=0)
        self.last_width = 0
        self.last_height = 0
        self.root.after(100, self._finish_switch)

    def _finish_switch(self):
        self._switching = False
        self.root.attributes('-topmost', False)
        self._update_display(force=True)

    # ---------- 选择文件夹 ----------
    def select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        self.folder = folder
        self.image_paths = self._get_image_files(folder, self.recursive_var.get())
        self.cols = int(self.cols_var.get())
        if len(self.image_paths) < self.cols:
            messagebox.showerror("错误", f"文件夹内图片少于 {self.cols} 张")
            self.image_paths = []
            self.status_label.config(text=f"图片不足 {self.cols} 张")
            return
        self.image_paths.sort()
        self._build_batches()
        self.batch_index = 0
        self.mode = self.mode_var.get()
        self._apply_mode()
        self.status_label.config(text=f"共 {len(self.image_paths)} 张，{len(self.batches)} 批")
        self._update_display(force=True)

    def _get_image_files(self, folder, recursive=False):
        exts = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp')
        files = []
        if recursive:
            for root, dirs, filenames in os.walk(folder):
                for f in filenames:
                    if f.lower().endswith(exts):
                        files.append(os.path.join(root, f))
        else:
            for f in os.listdir(folder):
                if f.lower().endswith(exts):
                    files.append(os.path.join(folder, f))
        return files

    # ---------- 构建批次 ----------
    def _build_batches(self):
        self.cols = int(self.cols_var.get())
        self.batches = []
        for i in range(0, len(self.image_paths), self.cols):
            self.batches.append(self.image_paths[i:i+self.cols])
        self.shuffled_batch_order = list(range(len(self.batches)))
        random.shuffle(self.shuffled_batch_order)

    # ---------- 模式切换 ----------
    def set_mode(self):
        self.mode = self.mode_var.get()
        self._apply_mode()
        self.last_width = 0
        self.last_height = 0
        self._update_display(force=True)
        self.root.update_idletasks()

    def _apply_mode(self):
        if not self.batches:
            return
        if self.mode == "sequential":
            if self.batch_index >= len(self.batches):
                self.batch_index = 0
            self.selected_images = self.batches[self.batch_index]
            self.status_label.config(text=f"顺序模式 [{self.batch_index+1}/{len(self.batches)}]")
        elif self.mode == "shuffle":
            if self.batch_index >= len(self.shuffled_batch_order):
                self.batch_index = 0
            real_idx = self.shuffled_batch_order[self.batch_index]
            self.selected_images = self.batches[real_idx]
            self.status_label.config(text=f"乱序模式 [{self.batch_index+1}/{len(self.batches)}]")
        else:
            self._random_pick_internal()

    # ---------- 翻页 ----------
    def next_batch(self):
        if self.mode == "random":
            self.random_pick()
            return
        if not self.batches:
            return
        if self.mode == "sequential":
            self.batch_index = (self.batch_index + 1) % len(self.batches)
        elif self.mode == "shuffle":
            self.batch_index = (self.batch_index + 1) % len(self.shuffled_batch_order)
        self._apply_mode()
        self._update_display(force=True)

    def prev_batch(self):
        if self.mode == "random":
            self.random_pick()
            return
        if not self.batches:
            return
        if self.mode == "sequential":
            self.batch_index = (self.batch_index - 1) % len(self.batches)
        elif self.mode == "shuffle":
            self.batch_index = (self.batch_index - 1) % len(self.shuffled_batch_order)
        self._apply_mode()
        self._update_display(force=True)

    # ---------- 随机抽取 ----------
    def random_pick(self):
        if not self.image_paths or len(self.image_paths) < self.cols:
            return
        self._random_pick_internal()
        self._update_display(force=True)

    def _random_pick_internal(self):
        self.selected_images = random.sample(self.image_paths, self.cols)
        self.status_label.config(text=f"随机模式 [抽取{self.cols}张]")

    # ---------- 核心显示 ----------
    def _update_display(self, force=False):
        if not self.selected_images or len(self.selected_images) != self.cols:
            return

        width = self.image_frame.winfo_width()
        height = self.image_frame.winfo_height()
        if width < 10 or height < 10:
            width, height = 1000, 700

        if not force and width == self.last_width and height == self.last_height:
            return

        self.last_width = width
        self.last_height = height

        resample = self.algo_display.get(self.algo_var.get(), Image.NEAREST)

        imgs = []
        ratios = []
        try:
            for path in self.selected_images:
                img = Image.open(path)
                imgs.append(img)
                ratios.append(img.width / img.height)
        except Exception as e:
            print(f"加载失败: {e}")
            return

        sum_ratios = sum(ratios)
        if sum_ratios <= 0:
            return
        H = min(height, width / sum_ratios)
        if H < 10:
            H = 10

        resized = []
        for img, ratio in zip(imgs, ratios):
            new_w = int(ratio * H)
            new_h = int(H)
            resized.append(img.resize((new_w, new_h), resample))

        total_w = sum(r.width for r in resized)
        total_h = max(r.height for r in resized)
        combined = Image.new('RGB', (total_w, total_h), color=(0, 0, 0))
        x = 0
        for r in resized:
            combined.paste(r, (x, 0))
            x += r.width

        final_img = Image.new('RGB', (width, height), color=(0, 0, 0))
        x_offset = (width - total_w) // 2
        y_offset = (height - total_h) // 2
        final_img.paste(combined, (x_offset, y_offset))

        self.photo_image = ImageTk.PhotoImage(final_img)
        self.image_label.config(image=self.photo_image)
        self.image_label.image = self.photo_image

    # ---------- 窗口缩放防抖 ----------
    def on_resize(self, event):
        if self._switching:
            return
        if not self.selected_images:
            return
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(500, lambda: self._update_display(force=False))

    # ---------- 键盘快捷键 ----------
    def on_key_press(self, event):
        key = event.char.lower()
        if key == 'a':
            self.prev_batch()
            return "break"
        elif key == 'd':
            self.next_batch()
            return "break"
        elif key == 'r':
            self.random_pick()
            return "break"

    # ---------- 自动播放 ----------
    def toggle_auto_play(self):
        if self.auto_play_var.get():
            try:
                self.auto_interval = float(self.interval_var.get())
                if self.auto_interval < 0.1:
                    self.auto_interval = 0.5
            except ValueError:
                self.auto_interval = 2.0
                self.interval_var.set("2.0")
            self._start_auto_timer()
        else:
            self._stop_auto_timer()

    def _start_auto_timer(self):
        if self.auto_timer:
            self.root.after_cancel(self.auto_timer)
        try:
            interval = float(self.interval_var.get())
            if interval < 0.1:
                interval = 0.5
        except ValueError:
            interval = 2.0
            self.interval_var.set("2.0")
        self._auto_switch()
        self.auto_timer = self.root.after(int(interval * 1000), self._start_auto_timer)

    def _stop_auto_timer(self):
        if self.auto_timer:
            self.root.after_cancel(self.auto_timer)
            self.auto_timer = None

    def _auto_switch(self):
        if self.image_paths and len(self.image_paths) >= self.cols:
            if self.mode == "random":
                self.random_pick()
            else:
                self.next_batch()

    # ---------- 退出 ----------
    def on_close(self):
        self._stop_auto_timer()
        self.root.destroy()

if __name__ == "__main__":
    # 使用 TkinterDnD 或普通 Tk
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
        print("提示: tkinterdnd2 未安装，拖拽功能不可用。")
    app = ImageBrowser(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()