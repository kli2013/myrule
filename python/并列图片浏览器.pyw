import os
import random
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import re
import json

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    class TkinterDnD:
        class Tk(tk.Tk):
            pass
    DND_FILES = None


def get_save_dir():
    """
    获取保存目录，优先级：
    1. 命令行参数 --save-dir
    2. 环境变量 IMAGE_BROWSER_SAVE_DIR
    3. 配置文件 ImageBrowser.json 中的 "save_dir" 字段
    4. 默认路径：用户图片目录/SavedBatches
    同时，若配置文件不存在，自动创建默认配置。
    """
    # 1. 命令行参数
    for i, arg in enumerate(sys.argv):
        if arg == "--save-dir" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]

    # 2. 环境变量
    env_dir = os.environ.get("IMAGE_BROWSER_SAVE_DIR")
    if env_dir:
        return env_dir

    # 3. 配置文件
    # 确定程序所在目录（打包后为 exe 目录，否则为脚本目录）
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "ImageBrowser.json")

    default_save_dir = os.path.join(os.path.expanduser("~"), "Pictures", "SavedBatches")
    default_config = {"save_dir": default_save_dir}

    # 确保配置文件存在，若不存在则创建默认配置
    if not os.path.exists(config_path):
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
        except Exception:
            # 若无法写入（如权限不足），则忽略，继续使用默认路径
            return default_save_dir

    # 读取配置文件
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            save_dir = config.get("save_dir", default_save_dir)
            if save_dir:
                return save_dir
            else:
                # 如果 save_dir 为空字符串，使用默认值，并修正配置文件
                config["save_dir"] = default_save_dir
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                return default_save_dir
    except (json.JSONDecodeError, KeyError):
        # 配置文件损坏，覆盖写入默认配置
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
        except:
            pass
        return default_save_dir


class ImageBrowser:
    def __init__(self, root):
        self.root = root
        self.root.title("图片并排浏览")
        self.root.geometry("1200x700")

        # ---------- 窗口状态变量 ----------
        self.fullscreen = False
        self._switching = False
        self.normal_geometry = None   # 保存普通窗口几何（含位置）
        self.was_maximized = False    # 进入全屏前是否最大化
        
        self.save_dir = get_save_dir()   # 读取路径
        self.root.bind("<Alt-Key-s>", self.save_current_image)   # 绑定快捷键

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

        # ---------- 控制栏 ----------
        self.control_frame = tk.Frame(root, bg="#f0f0f0")
        self.control_frame.place(x=0, y=0, relwidth=1.0)
        self.control_frame.place_forget()
        self.control_visible = False
        self.auto_hide_timer = None

        # 构建控制栏内容
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

        # 图片区交互
        self.image_label.bind("<ButtonPress-1>", self.start_move)
        self.image_label.bind("<B1-Motion>", self.on_move)
        self.image_label.bind("<Double-Button-1>", self.toggle_maximize)
        self.image_label.bind("<MouseWheel>", self.on_mouse_wheel)

        # ---------- 事件绑定 ----------
        self.root.bind("<Configure>", self.on_resize)
        self.root.bind("<Key>", self.on_key_press)

        self.root.bind_all("<Escape>", self.toggle_fullscreen)
        self.root.bind_all("<Return>", self.toggle_fullscreen)
        self.root.bind_all("<Alt-Key-f>", self.toggle_fullscreen)
        self.root.bind_all("<Alt-Key-F>", self.toggle_fullscreen)

        self.root.bind("<Alt-Key-1>", lambda e: self.set_mode_by_value("sequential") or "break")
        self.root.bind("<Alt-Key-2>", lambda e: self.set_mode_by_value("shuffle") or "break")
        self.root.bind("<Alt-Key-3>", lambda e: self.set_mode_by_value("random") or "break")
        self.root.bind("<Alt-Key-q>", lambda e: self.on_close() or "break")
        self.root.bind("<Alt-Key-Q>", lambda e: self.on_close() or "break")
        self.root.bind("<Alt-Key-4>", lambda e: chk_auto.invoke() or "break")

        for i in range(1, 10):
            self.root.bind(f"<Control-Key-{i}>", lambda e, sec=i: self.set_interval(sec) or "break")

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

        # ---------- 处理命令行 ----------
        self.root.after(100, self.process_command_line)

        # ---------- 窗口居中初始化 ----------
        self.root.withdraw()
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = 1200
        h = 700
        x = (sw - w) // 2
        y = (sh - h) // 2
        geom = f"{w}x{h}+{x}+{y}"
        self.root.geometry(geom)
        self.normal_geometry = geom  # 保存初始普通几何
        self.root.deiconify()

    # ---------- 窗口拖拽移动 ----------
    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def on_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")
        # 如果是普通窗口，更新普通几何
        if not self.fullscreen and self.root.state() == 'normal':
            self.normal_geometry = self.root.geometry()

    # ---------- 双击切换最大化/普通 ----------
    def toggle_maximize(self, event=None):
        if self.fullscreen:
            return
        if self.root.state() == 'zoomed':
            # 从最大化切换到普通：恢复普通几何
            self.root.state('normal')
            if self.normal_geometry:
                self.root.geometry(self.normal_geometry)
            else:
                self.root.geometry("1200x700")
        else:
            # 从普通切换到最大化：保存普通几何
            self.normal_geometry = self.root.geometry()
            self.root.state('zoomed')

    # ---------- 滚轮切换 ----------
    def on_mouse_wheel(self, event):
        if event.delta > 0:
            self.prev_batch()
        else:
            self.next_batch()
        return "break"

    # ---------- 全屏切换（修复最大化→全屏后普通几何丢失） ----------
    def toggle_fullscreen(self, event=None):
        if not self.fullscreen:
            # --- 进入全屏前：强制保存普通几何信息 ---
            # 1. 记录当前是否处于最大化状态
            self.was_maximized = (self.root.state() == 'zoomed')
            
            # 2. 关键修复：无论是否最大化，都获取当前的普通几何状态
            # 如果当前是最大化，先临时恢复普通状态以获取准确的几何数据
            if self.was_maximized:
                self.root.state('normal')
                # 强制更新以确保 geometry() 获取的是最新数据
                self.root.update_idletasks()
            
            # 3. 保存普通几何（位置和大小）
            self.normal_geometry = self.root.geometry()
            
            # 4. 如果刚才为了获取数据而取消了最大化，现在重新最大化（保持界面一致）
            if self.was_maximized:
                self.root.state('zoomed')
                
            # 5. 进入全屏
            self.fullscreen = True
            self._switching = True
            if self.resize_job:
                self.root.after_cancel(self.resize_job)
                self.resize_job = None
                
            self.root.attributes('-fullscreen', True)
            self.control_frame.place_forget()
            self.control_visible = False
            if self.auto_hide_timer:
                self.root.after_cancel(self.auto_hide_timer)
                self.auto_hide_timer = None
                
        else:
            # --- 退出全屏：恢复状态 ---
            self.fullscreen = False
            self._switching = True
            if self.resize_job:
                self.root.after_cancel(self.resize_job)
                self.resize_job = None
                
            self.root.attributes('-fullscreen', False)
            
            # 根据进入全屏前的状态进行恢复
            if self.was_maximized:
                # 如果之前是最大化，先恢复普通状态再最大化
                self.root.state('normal')
                if self.normal_geometry:
                    self.root.geometry(self.normal_geometry)
                else:
                    self.root.geometry("1200x700")
                # 延迟最大化以确保位置正确
                self.root.after(10, lambda: self.root.state('zoomed'))
            else:
                # 如果之前是普通状态，直接恢复几何
                if self.normal_geometry:
                    self.root.geometry(self.normal_geometry)
                else:
                    self.root.geometry("1200x700")
            
            self.was_maximized = False
            self.last_width = 0
            self.last_height = 0
            self.root.after(100, self._finish_switch)

    def _finish_switch(self):
        self._switching = False
        self._update_display(force=True)

    # ---------- 窗口缩放防抖（强制刷新） ----------
    def on_resize(self, event):
        if self._switching:
            return
        if not self.selected_images:
            return
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(80, lambda: self._update_display(force=True))

    # ---------- 鼠标悬停显示控制栏 ----------
    def on_mouse_move(self, event):
        threshold = 60
        if event.y <= threshold:
            if not self.control_visible:
                self.show_control()
        else:
            if self.control_visible:
                self.schedule_hide_control()

    def show_control(self):
        if self.control_visible:
            return
        self.control_frame.place(x=0, y=0, relwidth=1.0)
        self.control_frame.lift()
        self.control_visible = True
        if self.auto_hide_timer:
            self.root.after_cancel(self.auto_hide_timer)
            self.auto_hide_timer = None

    def schedule_hide_control(self):
        if self.auto_hide_timer:
            self.root.after_cancel(self.auto_hide_timer)
        self.auto_hide_timer = self.root.after(80, self.hide_control)

    def hide_control(self):
        if self.control_visible:
            self.control_frame.place_forget()
            self.control_visible = False
            self.auto_hide_timer = None

    # ---------- 处理命令行 ----------
    def process_command_line(self):
        if len(sys.argv) > 1:
            first_arg = sys.argv[1]
            if os.path.isdir(first_arg):
                self.load_folder(first_arg)
            elif os.path.isfile(first_arg) and first_arg.lower().endswith(('.jpg','.jpeg','.png','.bmp','.gif','.tiff','.webp')):
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
        
        # ----- 以 start_image 为基准循环移位 -----
        if start_image:
            start_abs = os.path.abspath(start_image)
            try:
                # 查找 start_image 在排序后列表中的索引
                idx = next(i for i, p in enumerate(self.image_paths) if os.path.samefile(p, start_abs))
                # 循环移位：将 idx 之前的部分移到末尾
                self.image_paths = self.image_paths[idx:] + self.image_paths[:idx]
                # 因为列表已重排，第一批的第一张就是 start_image
                self.batch_index = 0
            except (StopIteration, OSError):
                # 若未找到，则从第一批开始
                self.batch_index = 0
        else:
            self.batch_index = 0
   
        self._build_batches()

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
        folders = [p for p in paths if os.path.isdir(p)]
        if folders:
            self.load_folder(folders[0])
            return
        images = [p for p in paths if os.path.isfile(p) and p.lower().endswith(('.jpg','.jpeg','.png','.bmp','.gif','.tiff','.webp'))]
        if images:
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


    def save_current_image(self, event=None):
        """保存当前批次图片的原始拼接图（高度统一），静默保存"""
        if not self.selected_images:
            return "break"
    
        # 确定保存目录（若全局路径为空，则使用默认路径）
        save_dir = self.save_dir
        if not save_dir:
            # 默认保存在“用户图片”目录下的 SavedBatches 子文件夹
            save_dir = os.path.join(os.path.expanduser("~"), "Pictures", "SavedBatches")
    
        # 确保目录存在，不存在则创建
        if not os.path.exists(save_dir):
            try:
                os.makedirs(save_dir)
            except Exception:
                # 创建失败则静默退出
                return "break"
    
        try:
            import time
            from PIL import Image
    
            # 1. 加载当前批次所有图片（原始尺寸）
            imgs = []
            for path in self.selected_images:
                img = Image.open(path)
                if img.mode == 'RGBA':
                    img = img.convert('RGB')
                imgs.append(img)
    
            # 2. 计算目标高度（最高者）
            max_h = max(img.height for img in imgs)
    
            # 3. 等比缩放到统一高度
            resized = []
            for img in imgs:
                ratio = max_h / img.height
                new_w = int(img.width * ratio)
                resized_img = img.resize((new_w, max_h), Image.LANCZOS)
                resized.append(resized_img)
    
            # 4. 拼接
            total_w = sum(img.width for img in resized)
            combined = Image.new('RGB', (total_w, max_h), color=(0, 0, 0))
            x = 0
            for img in resized:
                combined.paste(img, (x, 0))
                x += img.width
    
            # 5. 保存
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"拼接_{timestamp}.jpg"
            save_path = os.path.join(save_dir, filename)
            combined.save(save_path, "JPEG", quality=90)
    
        except Exception:
            # 静默失败（可取消注释下一行调试）
            # import traceback; traceback.print_exc()
            pass
    
        return "break"


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
