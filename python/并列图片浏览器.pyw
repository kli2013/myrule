import os
import random
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import re
import ctypes

# 尝试导入 tkinterdnd2（窗口内拖拽）
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    class TkinterDnD:
        class Tk(tk.Tk):
            pass
    DND_FILES = None

class ImageBrowser:
    def __init__(self, root):
        self.root = root
        self.root.title("图片并排浏览 - 无边框整合版")
        self.root.geometry("1200x700")

        # ---------- 窗口居中 ----------
        self.root.withdraw()  # 隐藏窗口
        self.root.update_idletasks()  # 确保尺寸计算完成
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = 1200
        window_height = 700
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.deiconify()  # 显示窗口

        # 移除系统标题栏
        self.root.overrideredirect(True)

        # ---------- 数据 ----------
        self.folder = ""
        self.image_paths = []
        self.batches = []
        self.shuffled_batch_order = []
        self.batch_index = 0
        self.mode = "sequential"
        self.selected_images = []
        self.cols = 3

        # ---------- 尺寸缓存 ----------
        self.last_width = 0
        self.last_height = 0

        # ---------- 全屏状态 ----------
        self.fullscreen = False
        self.maximized = False
        self.normal_geometry = None
        self._switching = False
        self.was_maximized = False  # 记录进入全屏前是否最大化
        self.original_geometry = None


        # ---------- 顶部容器（标题栏 + 控制栏） ----------
        self.top_bar = tk.Frame(root, bg="#2c2c2c")
        self.top_bar.pack_forget()
        self.top_visible = False
        self.auto_hide_timer = None


        # ----- 自定义标题栏 -----
        self.title_bar = tk.Frame(self.top_bar, bg="#E2E2E2", relief='flat', bd=0)
        self.title_bar.pack(side=tk.TOP, fill=tk.X)
        
        self.title_label = tk.Label(self.title_bar, text="图片并排浏览", bg="#E2E2E2", fg="black", font=("Microsoft YaHei", 10))
        self.title_label.pack(side=tk.LEFT, padx=10, pady=5)
        
        # 按钮样式（基础）
        btn_bg = "#E2E2E2"
        btn_fg = "black"
        btn_hover_minmax = "#CBCBCB"
        btn_hover_close = "#E81123"
        btn_hover_fg_close = "white"
        
        # 关闭按钮
        btn_close = tk.Button(self.title_bar, text="✕", command=self.on_close,
                              bg=btn_bg, fg=btn_fg, relief='flat', width=3, bd=0)
        btn_close.pack(side=tk.RIGHT, padx=2)
        
        # 最大化按钮
        btn_max = tk.Button(self.title_bar, text="□", command=self.maximize_window,
                            bg=btn_bg, fg=btn_fg, relief='flat', width=3, bd=0)
        btn_max.pack(side=tk.RIGHT, padx=2)
        
        # 最小化按钮
        btn_min = tk.Button(self.title_bar, text="─", command=self.minimize_window,
                            bg=btn_bg, fg=btn_fg, relief='flat', width=3, bd=0)
        btn_min.pack(side=tk.RIGHT, padx=2)
        
        # 悬停效果绑定
        def on_enter(event, btn, bg):
            btn.config(bg=bg)
        def on_leave(event, btn):
            btn.config(bg=btn_bg)
        
        # 最小化和最大化悬停
        btn_min.bind("<Enter>", lambda e: on_enter(e, btn_min, btn_hover_minmax))
        btn_min.bind("<Leave>", lambda e: on_leave(e, btn_min))
        btn_max.bind("<Enter>", lambda e: on_enter(e, btn_max, btn_hover_minmax))
        btn_max.bind("<Leave>", lambda e: on_leave(e, btn_max))
        
        # 关闭按钮悬停（特殊颜色和文字颜色）
        def on_enter_close(event):
            btn_close.config(bg=btn_hover_close, fg=btn_hover_fg_close)
        def on_leave_close(event):
            btn_close.config(bg=btn_bg, fg=btn_fg)
        btn_close.bind("<Enter>", on_enter_close)
        btn_close.bind("<Leave>", on_leave_close)

        # 拖拽移动
        self.title_bar.bind("<ButtonPress-1>", self.start_move)
        self.title_bar.bind("<B1-Motion>", self.on_move)
        self.title_label.bind("<ButtonPress-1>", self.start_move)
        self.title_label.bind("<B1-Motion>", self.on_move)

        # 双击标题栏切换全屏
        self.title_bar.bind("<Double-Button-1>", self.toggle_fullscreen)
        self.title_label.bind("<Double-Button-1>", self.toggle_fullscreen)



        # ----- 控制栏（菜单） -----
        self.control_frame = tk.Frame(self.top_bar, bg="#f0f0f0")
        self.control_frame.pack(side=tk.TOP, fill=tk.X)

        # 控制栏内容（与之前相同）
        btn_select = tk.Button(self.control_frame, text="📂 选择", command=self.select_folder)
        btn_select.pack(side=tk.LEFT, padx=2)

        self.recursive_var = tk.BooleanVar(value=False)
        chk_recursive = tk.Checkbutton(self.control_frame, text="包含子文件夹", variable=self.recursive_var)
        chk_recursive.pack(side=tk.LEFT, padx=2)

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

        self.status_label = tk.Label(self.control_frame, text="", font=("", 9), anchor="e")
        self.status_label.pack(side=tk.RIGHT, padx=10)

        # ---------- 图片显示 ----------
        self.image_frame = tk.Frame(root, bg="black")
        self.image_frame.pack(expand=True, fill=tk.BOTH, padx=0, pady=0)
        self.image_label = tk.Label(self.image_frame, bg="black")
        self.image_label.pack(expand=True, fill=tk.BOTH)

        # 图片区拖拽窗口
        self.image_label.bind("<ButtonPress-1>", self.start_move)
        self.image_label.bind("<B1-Motion>", self.on_move)
        self.image_label.bind("<Double-Button-1>", self.toggle_maximize)

        # ---------- 事件绑定 ----------
        self.root.bind("<Configure>", self.on_resize)
        self.root.bind("<Key>", self.on_key_press)
        self.root.bind_all("<Escape>", self.toggle_fullscreen)
        self.root.bind_all("<Return>", self.toggle_fullscreen)

        self.root.bind_all("<Alt-Key-f>", self.toggle_fullscreen)
        self.root.bind_all("<Alt-Key-F>", self.toggle_fullscreen)

        # Alt 快捷键
        self.root.bind("<Alt-Key-1>", lambda e: self.set_mode_by_value("sequential") or "break")
        self.root.bind("<Alt-Key-2>", lambda e: self.set_mode_by_value("shuffle") or "break")
        self.root.bind("<Alt-Key-3>", lambda e: self.set_mode_by_value("random") or "break")
        self.root.bind("<Alt-Key-q>", lambda e: self.on_close() or "break")
        self.root.bind("<Alt-Key-Q>", lambda e: self.on_close() or "break")

        
        # Alt+4 切换自动播放
        self.root.bind("<Alt-Key-4>", lambda e: chk_auto.invoke() or "break")

        # Ctrl+数字
        for i in range(1, 10):
            self.root.bind(f"<Control-Key-{i}>", lambda e, sec=i: self.set_interval(sec) or "break")

        # 鼠标移动检测（显示顶部栏）
        self.root.bind('<Motion>', self.on_mouse_move)

        # ---------- 窗口内拖拽 ----------
        if DND_AVAILABLE:
            try:
                self.root.drop_target_register(DND_FILES)
                self.root.dnd_bind('<<Drop>>', self.on_drop)
            except Exception as e:
                print("窗口内拖拽初始化失败:", e)

        # ---------- 变量 ----------
        self.photo_image = None
        self.resize_job = None
        self.auto_timer = None
        self.auto_interval = 2.0

        # ---------- 处理命令行参数 ----------
        self.root.after(100, self.process_command_line)

    # ---------- 窗口移动 ----------
    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def on_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    # ---------- 窗口控制 ----------
    def minimize_window(self):
        self.root.iconify()

    def toggle_maximize(self, event=None):
        if self.fullscreen:
            self.toggle_fullscreen()
            self.root.after(50, self._do_maximize)
            return
        self.maximize_window()


    def maximize_window(self):
        """标准最大化（保留任务栏）"""
        if self.fullscreen:
            self.toggle_fullscreen()
            self.root.after(50, self._do_maximize)
            return
    
        if self.maximized:
            # 还原到普通窗口
            if self.original_geometry:
                self.root.geometry(self.original_geometry)
            else:
                self.root.geometry("1200x700")
            self.maximized = False
        else:
            # 保存当前普通几何（未最大化）
            self.original_geometry = self.root.geometry()
            self._do_maximize()
    
    def _do_maximize(self):
        """执行最大化（获取工作区尺寸）"""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            rect = ctypes.wintypes.RECT()
            user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
            work_w = rect.right - rect.left
            work_h = rect.bottom - rect.top
        except:
            work_w = self.root.winfo_screenwidth()
            work_h = self.root.winfo_screenheight() - 30
        self.root.geometry(f"{work_w}x{work_h}+0+0")
        self.maximized = True
    
    def toggle_fullscreen(self, event=None):
        if not self.fullscreen:
            # 进入全屏前保存普通几何（非最大化）
            if self.maximized:
                # 如果当前是最大化，则使用之前保存的原始几何（普通窗口尺寸）
                if not self.original_geometry:
                    # 如果没有保存过，则先还原到默认尺寸再保存（防止丢失）
                    self.root.geometry("1200x700")
                    self.root.update()
                    self.original_geometry = self.root.geometry()
            else:
                # 当前是普通窗口，直接保存
                self.original_geometry = self.root.geometry()
            # 保存是否最大化状态
            self.was_maximized = self.maximized
    
        self.fullscreen = not self.fullscreen
        self._switching = True
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
            self.resize_job = None
    
        if self.fullscreen:
            self.root.geometry("+0+0")
            self.root.update()
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            self.root.geometry(f"{screen_w}x{screen_h}+0+0")
            self.root.attributes('-topmost', True)
            self.maximized = False
        else:
            self.root.attributes('-topmost', False)
            if self.was_maximized:
                self._do_maximize()
            else:
                if self.original_geometry:
                    self.root.geometry(self.original_geometry)
                else:
                    self.root.geometry("1200x700")
            self.was_maximized = False
    
        self.last_width = 0
        self.last_height = 0
        self.root.after(100, self._finish_switch)

    def _finish_switch(self):
        self._switching = False
        self._update_display(force=True)

    # ---------- 顶部栏显示/隐藏 ----------
    def on_mouse_move(self, event):
        threshold = 50
        if event.y <= threshold:
            if not self.top_visible:
                self.show_top_bar()
        else:
            if self.top_visible:
                self.schedule_hide_top_bar()

    def show_top_bar(self):
        if self.top_visible:
            return
        self.top_bar.place(x=0, y=0, relwidth=1.0)
        self.top_bar.lift()  # 确保浮在所有控件之上
        self.top_visible = True
        if self.auto_hide_timer:
            self.root.after_cancel(self.auto_hide_timer)
            self.auto_hide_timer = None

    def schedule_hide_top_bar(self):
        if self.auto_hide_timer:
            self.root.after_cancel(self.auto_hide_timer)
        self.auto_hide_timer = self.root.after(500, self.hide_top_bar)

    def hide_top_bar(self):
        if self.top_visible:
            self.top_bar.place_forget()
            self.top_visible = False
            self.auto_hide_timer = None

    # ---------- 处理拖拽到exe ----------
    def process_command_line(self):
        if len(sys.argv) > 1:
            first_arg = sys.argv[1]
            if os.path.isdir(first_arg):
                # 直接加载文件夹
                self.load_folder(first_arg)
            elif os.path.isfile(first_arg) and first_arg.lower().endswith(('.jpg','.jpeg','.png','.bmp','.gif','.tiff','.webp')):
                # 单个图片：加载其所在文件夹，并以该图片为起点
                folder = os.path.dirname(first_arg)
                self.load_folder(folder, start_image=first_arg)

    # ---------- 核心加载 ----------
    def load_folder(self, folder, start_image=None):
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
        # 确定起始批次索引
        if start_image:
            # 使用 os.path.samefile 进行路径比较（忽略大小写和斜杠差异）
            start_abs = os.path.abspath(start_image)
            try:
                # 在 self.image_paths 中查找匹配的路径
                idx = next(i for i, p in enumerate(self.image_paths) if os.path.samefile(p, start_abs))
                self.batch_index = idx // self.cols
            except (StopIteration, OSError):
                # 如果匹配失败，从第一批开始
                self.batch_index = 0
        else:
            self.batch_index = 0
        # 强制设为顺序模式（文件夹按顺序排列）
        self.mode = "sequential"
        self.mode_var.set("sequential")
        self._apply_mode()
        self.status_label.config(text=f"共 {len(self.image_paths)} 张，{len(self.batches)} 批")
        self._update_display(force=True)

    # ---------- 窗口内拖拽 ----------
    def on_drop(self, event):
        raw = event.data
        if not raw:
            return
        paths = re.findall(r'\{[^}]*\}|"[^"]*"|\S+', raw)
        paths = [p.strip('{}"') for p in paths]
    
        # 检查是否有文件夹
        folders = [p for p in paths if os.path.isdir(p)]
        if folders:
            self.load_folder(folders[0])
            return
    
        # 收集所有图片文件
        images = [p for p in paths if os.path.isfile(p) and p.lower().endswith(('.jpg','.jpeg','.png','.bmp','.gif','.tiff','.webp'))]
        if not images:
            return
    
        # 只取第一张图片，加载其所在文件夹，并以该图片为起点
        first_image = images[0]
        folder = os.path.dirname(first_image)
        self.load_folder(folder, start_image=first_image)

    # ---------- 选择文件夹 ----------
    def select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        self.load_folder(folder)

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
        if not self.selected_images:
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
        self.resize_job = self.root.after(80, lambda: self._update_display(force=False))

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

    # ---------- 间隔设置 ----------
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

    # ---------- 退出 ----------
    def on_close(self):
        self._stop_auto_timer()
        self.root.destroy()

if __name__ == "__main__":
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
        print("提示: tkinterdnd2 未安装，窗口内拖拽不可用。")
    app = ImageBrowser(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
