import os
import json
import copy
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, Toplevel, simpledialog

# 尝试导入拖拽库
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    # 创建虚拟的 TkinterDnD.Tk 类，使其继承自 tk.Tk
    class TkinterDnD:
        class Tk(tk.Tk):
            pass
    DND_FILES = None

from PIL import Image, ImageTk
from concurrent.futures import ThreadPoolExecutor

class ImageConverter(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        # 根据拖拽库可用性设置窗口标题
        if DND_AVAILABLE:
            self.title("图片批量转换器 (支持拖拽)")
        else:
            self.title("图片批量转换器 (拖拽不可用，请使用按钮)")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.preset_file = os.path.join(script_dir, "picpresets.json")
        
        # 加载配置（扁平结构）
        self.load_settings_and_presets()
        
        # 窗口大小
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width - self.window_width) // 2
        y = (screen_height - self.window_height) // 2
        self.geometry(f"{self.window_width}x{self.window_height}+{x}+{y}")
        self.resizable(True, True)
        
        self.tasks = []
        self.history = []          # 撤销历史
        self.history_index = -1
        self.output_dir = tk.StringVar(value=self.default_output_dir)
        self.converting = False
        self.executor = None
        self.futures = []
        self.total_tasks = 0

        self.create_widgets()
        self.load_presets_list()
        self.save_current_state_to_history()

        # 右键菜单
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="编辑当前任务", command=self.edit_selected_task)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="移除当前任务", command=self.remove_selected)

        self.bind_all("<Button-1>", self.on_click_outside, add=True)

        # 拖拽初始化（仅当库可用时）
        if DND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.on_drop)
        else:
            messagebox.showwarning("提示", "未安装 tkinterdnd2 库，拖拽添加功能不可用。\n可使用按钮添加图片或文件夹。")

        self.processed_indices = set()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ========== 配置加载/保存（扁平结构：settings + 预设） ==========
    def load_settings_and_presets(self):
        """加载配置文件：顶层包含 settings 对象和各个预设"""
        default_settings = {
            "window_width": 1200,
            "window_height": 760,
            "default_output_dir": os.getcwd(),
            "thread_count": min(8, os.cpu_count() or 4),
            "keep_exif": False,
        }
        self.presets = {}

        if not os.path.exists(self.preset_file):
            # 新文件，使用默认值
            self.window_width = default_settings["window_width"]
            self.window_height = default_settings["window_height"]
            self.default_output_dir = default_settings["default_output_dir"]
            self.default_threads = default_settings["thread_count"]
            self.keep_exif = default_settings["keep_exif"]
            return

        try:
            with open(self.preset_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("配置文件格式错误")
            
            # 读取 settings 对象
            settings = data.get("settings", {})
            self.window_width = settings.get("window_width", default_settings["window_width"])
            self.window_height = settings.get("window_height", default_settings["window_height"])
            self.default_output_dir = settings.get("default_output_dir", default_settings["default_output_dir"])
            self.default_threads = settings.get("thread_count", default_settings["thread_count"])
            self.keep_exif = settings.get("keep_exif", default_settings["keep_exif"])
            
            # 其余所有键（除了 "settings"）都视为预设
            self.presets = {k: v for k, v in data.items() if k != "settings"}
            
        except Exception as e:
            print(f"加载配置失败: {e}，使用默认值")
            self.window_width = default_settings["window_width"]
            self.window_height = default_settings["window_height"]
            self.default_output_dir = default_settings["default_output_dir"]
            self.default_threads = default_settings["thread_count"]
            self.keep_exif = default_settings["keep_exif"]
            self.presets = {}

    def save_settings_and_presets(self):
        """保存配置：将全局设置放入 settings 对象，预设放在顶层"""
        data = {
            "settings": {
                "window_width": self.winfo_width(),
                "window_height": self.winfo_height(),
                "default_output_dir": self.output_dir.get(),
                "thread_count": self.thread_count_var.get(),
                "keep_exif": self.keep_exif_var.get(),
            }
        }
        # 添加所有预设
        for name, preset in self.presets.items():
            if name != "settings":
                data[name] = preset
        
        try:
            with open(self.preset_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def on_closing(self):
        self.save_settings_and_presets()
        if self.executor:
            self.executor.shutdown(wait=False)
        self.destroy()

    # ========== 撤销功能 ==========
    def save_current_state_to_history(self):
        snapshot = copy.deepcopy(self.tasks)
        self.history = self.history[:self.history_index+1]
        self.history.append(snapshot)
        self.history_index += 1
        if len(self.history) > 30:
            self.history.pop(0)
            self.history_index -= 1

    def undo(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法撤销")
            return
        if self.history_index > 0:
            self.history_index -= 1
            self.tasks = copy.deepcopy(self.history[self.history_index])
            self.refresh_task_listbox()
            self.preview_canvas.delete("all")
            messagebox.showinfo("撤销", "已恢复到上一次状态")
        else:
            messagebox.showinfo("提示", "没有更早的状态")

    def refresh_task_listbox(self):
        self.task_listbox.delete(0, tk.END)
        for task in self.tasks:
            self.task_listbox.insert(tk.END, self.get_task_display_text(task))

    # ========== 递归设置控件状态 ==========
    def set_widgets_state(self, widget, state):
        try:
            if isinstance(widget, (ttk.Button, ttk.Combobox, ttk.Entry, ttk.Checkbutton,
                                   ttk.Radiobutton, ttk.Scale, ttk.Spinbox)):
                if isinstance(widget, ttk.Combobox):
                    widget.config(state='disabled' if state == tk.DISABLED else 'readonly')
                else:
                    widget.config(state=state)
        except:
            pass
        for child in widget.winfo_children():
            self.set_widgets_state(child, state)

    def enable_task_edit_buttons(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.edit_btn.config(state=state)
        self.remove_btn.config(state=state)
        self.clear_btn.config(state=state)
        self.undo_btn.config(state=state)
        self.add_files_btn.config(state=state)
        self.add_folder_btn.config(state=state)
        self.set_widgets_state(self.template_frame, state)
        self.browse_btn.config(state=state)
        self.load_preset_btn.config(state=state)
        self.save_preset_btn.config(state=state)
        # 拖拽注册/解注册（仅当库可用时）
        if DND_AVAILABLE:
            if enabled:
                self.drop_target_register(DND_FILES)
                self.dnd_bind('<<Drop>>', self.on_drop)
            else:
                try:
                    self.drop_target_unregister()
                    self.dnd_unbind('<<Drop>>')
                except:
                    pass
        if enabled:
            self.task_listbox.bind("<Button-3>", self.show_context_menu)
        else:
            self.task_listbox.unbind("<Button-3>")

    def on_click_outside(self, event):
        try:
            self.context_menu.unpost()
        except:
            pass

    # ========== 表达式计算 ==========
    def eval_crop_expr(self, expr, width, height):
        if not isinstance(expr, str):
            expr = str(expr)
        allowed = {'iw': width, 'ih': height}
        try:
            code = expr.strip()
            for k, v in allowed.items():
                code = code.replace(k, str(v))
            result = eval(code, {"__builtins__": {}}, {})
            return max(0, int(round(result)))
        except:
            return 0

    # ========== 界面构建 ==========
    def create_widgets(self):
        left_frame = ttk.Frame(self)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
    
        right_frame = ttk.Frame(self, width=350, height=400)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=5, pady=5)
        right_frame.pack_propagate(False)
    
        # ========== 输入与输出（一行布局） ==========
        io_frame = ttk.LabelFrame(left_frame, text="输入与输出")
        io_frame.pack(fill=tk.X, pady=5)
    
        io_row = ttk.Frame(io_frame)
        io_row.pack(fill=tk.X, padx=5, pady=5)
    
        # 添加图片按钮（支持多选）
        self.add_files_btn = ttk.Button(io_row, text="添加图片", command=self.add_files)
        self.add_files_btn.pack(side=tk.LEFT, padx=2)
    
        # 遍历文件夹按钮（递归）
        self.add_folder_btn = ttk.Button(io_row, text="遍历文件夹", command=self.add_folders)
        self.add_folder_btn.pack(side=tk.LEFT, padx=2)
    
        ttk.Label(io_row, text="输出目录:").pack(side=tk.LEFT, padx=(10,2))
    
        self.output_dir_entry = ttk.Entry(io_row, textvariable=self.output_dir, width=40)
        self.output_dir_entry.pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
    
        self.browse_btn = ttk.Button(io_row, text="浏览", command=self.select_output_dir)
        self.browse_btn.pack(side=tk.LEFT, padx=2)
    
        # ========== 当前模板框架 ==========
        self.template_frame = ttk.LabelFrame(left_frame, text="当前模板（新任务将使用此设置）")
        self.template_frame.pack(fill=tk.X, pady=5)
    
        # 第一行：格式、质量、旋转
        row1 = ttk.Frame(self.template_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="格式:").pack(side=tk.LEFT, padx=2)
        self.format_var = tk.StringVar(value="JPEG")
        format_combo = ttk.Combobox(row1, textvariable=self.format_var,
                                    values=["JPEG", "PNG", "WEBP"], state="readonly", width=6)
        format_combo.pack(side=tk.LEFT, padx=2)
        format_combo.bind("<<ComboboxSelected>>", self.update_template_preview)
    
        ttk.Label(row1, text="质量:").pack(side=tk.LEFT, padx=(10,2))
        self.quality_var = tk.IntVar(value=85)
        quality_scale = ttk.Scale(row1, from_=1, to=100, variable=self.quality_var,
                                  orient=tk.HORIZONTAL, length=100)
        quality_scale.pack(side=tk.LEFT, padx=2)
        self.quality_label = ttk.Label(row1, text="85", width=3)
        self.quality_label.pack(side=tk.LEFT, padx=2)
        self.quality_var.trace_add("write", lambda *a: self.quality_label.config(text=str(self.quality_var.get())))
    
        ttk.Label(row1, text="旋转:").pack(side=tk.LEFT, padx=(10,2))
        self.rotation_var = tk.StringVar(value="0°")
        rot_frame = ttk.Frame(row1)
        rot_frame.pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(rot_frame, text="无", variable=self.rotation_var, value="0°",
                        command=self.update_template_preview).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(rot_frame, text="左90", variable=self.rotation_var, value="90°",
                        command=self.update_template_preview).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(rot_frame, text="右90", variable=self.rotation_var, value="-90°",
                        command=self.update_template_preview).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(rot_frame, text="180", variable=self.rotation_var, value="180°",
                        command=self.update_template_preview).pack(side=tk.LEFT, padx=2)
    
        self.h_flip_var = tk.BooleanVar(value=False)
        self.v_flip_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="水平翻转", variable=self.h_flip_var, command=self.update_template_preview).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(row1, text="垂直翻转", variable=self.v_flip_var, command=self.update_template_preview).pack(side=tk.LEFT, padx=5)
    
        # 第二行：尺寸调整 + 保留EXIF
        row2 = ttk.Frame(self.template_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="尺寸调整:").pack(side=tk.LEFT, padx=2)
        self.resize_mode_var = tk.StringVar(value="无调整")
        mode_combo = ttk.Combobox(row2, textvariable=self.resize_mode_var,
                                  values=["无调整", "精确 (WxH)", "限制长边", "限制短边"],
                                  state="readonly", width=12)
        mode_combo.pack(side=tk.LEFT, padx=2)
        mode_combo.bind("<<ComboboxSelected>>", self.on_resize_mode_changed)   # 统一回调
    
        # 宽/长边/短边 标签（动态变化）
        self.width_label = ttk.Label(row2, text="宽:")
        self.width_label.pack(side=tk.LEFT, padx=(10,2))
        self.resize_width_var = tk.IntVar(value=800)
        self.resize_width_spinbox = ttk.Spinbox(row2, from_=1, to=9999, textvariable=self.resize_width_var, width=6)
        self.resize_width_spinbox.pack(side=tk.LEFT, padx=2)
    
        # 高度标签和输入框（在限制长边/短边模式下禁用）

        ttk.Label(row2, text="高:").pack(side=tk.LEFT, padx=(5,2))
        self.resize_height_var = tk.IntVar(value=600)
        self.resize_height_spinbox = ttk.Spinbox(row2, from_=1, to=9999, textvariable=self.resize_height_var, width=6)
        self.resize_height_spinbox.pack(side=tk.LEFT, padx=2)
    
        # 保留EXIF
        ttk.Label(row2, text="保留EXIF:").pack(side=tk.LEFT, padx=(20, 2))
        self.keep_exif_var = tk.BooleanVar(value=self.keep_exif)
        ttk.Checkbutton(row2, variable=self.keep_exif_var).pack(side=tk.LEFT)
    
        # 第三行：裁剪设置
        row3 = ttk.Frame(self.template_frame)
        row3.pack(fill=tk.X, pady=2)
        self.crop_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row3, text="启用裁剪", variable=self.crop_enabled_var,
                        command=self.update_template_preview).pack(side=tk.LEFT, padx=2)
        ttk.Label(row3, text="x:").pack(side=tk.LEFT, padx=(5,0))
        self.crop_x_var = tk.StringVar(value="0")
        ttk.Entry(row3, textvariable=self.crop_x_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(row3, text="y:").pack(side=tk.LEFT)
        self.crop_y_var = tk.StringVar(value="0")
        ttk.Entry(row3, textvariable=self.crop_y_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(row3, text="w:").pack(side=tk.LEFT)
        self.crop_w_var = tk.StringVar(value="iw")
        ttk.Entry(row3, textvariable=self.crop_w_var, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(row3, text="h:").pack(side=tk.LEFT)
        self.crop_h_var = tk.StringVar(value="ih")
        ttk.Entry(row3, textvariable=self.crop_h_var, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(row3, text="(支持 iw, ih, 四则运算)", foreground="gray").pack(side=tk.LEFT, padx=5)
    
        # 第四行：输出名称模板 + 重名处理 + 预设
        row4 = ttk.Frame(self.template_frame)
        row4.pack(fill=tk.X, pady=5)
        ttk.Label(row4, text="输出名称模板:").pack(side=tk.LEFT, padx=2)
        self.name_template_var = tk.StringVar(value="{Filename}")
        template_combo = ttk.Combobox(row4, textvariable=self.name_template_var,
                                      values=["{Filename}", "{Folder name}{Filename}"],
                                      state="readonly", width=22)
        template_combo.pack(side=tk.LEFT, padx=2)
        template_combo.bind("<<ComboboxSelected>>", self.update_template_preview)
    
        ttk.Label(row4, text="重名处理:").pack(side=tk.LEFT, padx=(10,2))
        self.duplicate_mode = tk.StringVar(value="覆盖")
        dup_combo = ttk.Combobox(row4, textvariable=self.duplicate_mode,
                                 values=["覆盖", "自动重命名"], state="readonly", width=10)
        dup_combo.pack(side=tk.LEFT, padx=2)
    
        ttk.Label(row4, text="预设:").pack(side=tk.LEFT, padx=(10,2))
        self.preset_combo = ttk.Combobox(row4, state="readonly", width=18)
        self.preset_combo.pack(side=tk.LEFT, padx=2)
        self.preset_combo.bind("<<ComboboxSelected>>", self.on_preset_selected)
    
        self.load_preset_btn = ttk.Button(row4, text="加载预设", command=self.load_preset)
        self.load_preset_btn.pack(side=tk.LEFT, padx=2)
        self.save_preset_btn = ttk.Button(row4, text="保存预设", command=self.save_preset)
        self.save_preset_btn.pack(side=tk.LEFT, padx=2)
    
        # 模板预览文字
        self.template_preview_label = ttk.Label(self.template_frame, text="", relief="sunken")
        self.template_preview_label.pack(fill=tk.X, pady=5)
        self.update_template_preview()
    
        # 任务列表
        list_frame = ttk.LabelFrame(left_frame, text="转换任务（右键可编辑）")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
    
        self.task_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=12)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.task_listbox.yview)
        self.task_listbox.configure(yscrollcommand=scrollbar.set)
        self.task_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
        self.task_listbox.bind("<Button-3>", self.show_context_menu)
        self.task_listbox.bind("<<ListboxSelect>>", self.on_task_select)
    
        # 进度条
        progress_frame = ttk.Frame(left_frame)
        progress_frame.pack(fill=tk.X, pady=5)
        self.progress_var = tk.IntVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.progress_label = ttk.Label(progress_frame, text="就绪")
        self.progress_label.pack(side=tk.RIGHT, padx=5)
    
        # 操作按钮
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, pady=5)
    
        self.start_btn = ttk.Button(btn_frame, text="开始转换", command=self.start_convert)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.undo_btn = ttk.Button(btn_frame, text="撤销", command=self.undo)
        self.undo_btn.pack(side=tk.LEFT, padx=5)
        self.edit_btn = ttk.Button(btn_frame, text="编辑任务", command=self.edit_selected_task)
        self.edit_btn.pack(side=tk.LEFT, padx=5)
        self.remove_btn = ttk.Button(btn_frame, text="移除", command=self.remove_selected)
        self.remove_btn.pack(side=tk.LEFT, padx=5)
        self.clear_btn = ttk.Button(btn_frame, text="清空所有", command=self.clear_tasks)
        self.clear_btn.pack(side=tk.LEFT, padx=5)
    
        ttk.Label(btn_frame, text="线程数:").pack(side=tk.LEFT, padx=(10,2))
        cpu_count = os.cpu_count() or 4
        self.thread_count_var = tk.IntVar(value=self.default_threads)
        thread_spin = ttk.Spinbox(btn_frame, from_=1, to=cpu_count, textvariable=self.thread_count_var, width=5)
        thread_spin.pack(side=tk.LEFT, padx=2)
        ttk.Label(btn_frame, text=f"(最大{cpu_count})").pack(side=tk.LEFT, padx=2)
    
        # 右侧预览
        ttk.Label(right_frame, text="预览（点击任务查看效果）", font=("Arial", 10, "bold")).pack(pady=5)
        self.preview_canvas = tk.Canvas(right_frame, bg='gray', relief=tk.SUNKEN)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.current_preview_img = None
    
        # 初始化时根据当前模式调整一次界面状态
        self.on_resize_mode_changed()


    def _apply_resize_mode_ui(self, mode, width_label, height_spinbox):
        """根据尺寸调整模式更新标签文本和高度输入框状态"""
        if mode == "限制长边":
            width_label.config(text="长边:")
            height_spinbox.config(state=tk.DISABLED)
        elif mode == "限制短边":
            width_label.config(text="短边:")
            height_spinbox.config(state=tk.DISABLED)
        else:  # "无调整" 或 "精确 (WxH)"
            width_label.config(text="宽:")
            height_spinbox.config(state=tk.NORMAL)
    
    def on_resize_mode_changed(self, event=None):
        mode = self.resize_mode_var.get()
        self._apply_resize_mode_ui(mode, self.width_label, self.resize_height_spinbox)
        self.update_template_preview()



    # ========== 新增：添加图片/文件夹的方法 ==========
    def add_files(self):
        """通过文件对话框添加图片文件"""
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法添加新任务")
            return
        file_paths = filedialog.askopenfilenames(
            title="选择图片文件",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp"), ("所有文件", "*.*")]
        )
        if not file_paths:
            return
        self._add_image_paths(file_paths)

    def add_folders(self):
        """通过文件夹对话框添加文件夹（递归查找图片）"""
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法添加新任务")
            return
        folder = filedialog.askdirectory(title="选择包含图片的文件夹")
        if not folder:
            return
        # 递归查找图片文件
        image_files = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in ['.jpg','.jpeg','.png','.webp','.bmp']:
                    image_files.append(os.path.join(root, f))
        if not image_files:
            messagebox.showinfo("提示", "所选文件夹中没有找到支持的图片")
            return
        self._add_image_paths(image_files)

    def _add_image_paths(self, paths):
        """统一添加图片路径列表到任务列表，使用当前模板参数"""
        current = {
            'format': self.format_var.get(),
            'quality': self.quality_var.get(),
            'rotation': self.rotation_var.get(),
            'h_flip': self.h_flip_var.get(),
            'v_flip': self.v_flip_var.get(),
            'resize_mode': self.resize_mode_var.get(),
            'resize_w': self.resize_width_var.get(),
            'resize_h': self.resize_height_var.get(),
            'name_template': self.name_template_var.get(),
            'crop_enabled': self.crop_enabled_var.get(),
            'crop_x': self.crop_x_var.get(),
            'crop_y': self.crop_y_var.get(),
            'crop_w': self.crop_w_var.get(),
            'crop_h': self.crop_h_var.get(),
            'duplicate_mode': self.duplicate_mode.get(),
            'keep_exif': self.keep_exif_var.get()
        }
        added = 0
        for fp in paths:
            task = {'path': fp, **current}
            self.tasks.append(task)
            self.task_listbox.insert(tk.END, self.get_task_display_text(task))
            added += 1
        if added > 0:
            self.save_current_state_to_history()

    # ========== 右键菜单 ==========
    def show_context_menu(self, event):
        index = self.task_listbox.nearest(event.y)
        if index >= 0:
            if index not in self.task_listbox.curselection():
                self.task_listbox.selection_clear(0, tk.END)
                self.task_listbox.selection_set(index)
                self.task_listbox.activate(index)
                self.on_task_select(None)
        self.context_menu.post(event.x_root, event.y_root)

    def edit_selected_task(self):
        selection = self.task_listbox.curselection()
        if not selection:
            messagebox.showinfo("提示", "请先选中一个任务")
            return
        idx = selection[0]
        if idx < 0 or idx >= len(self.tasks):
            return
        self.edit_task_dialog(idx, self.tasks[idx])

    # ========== 辅助函数 ==========
    def get_task_display_text(self, task):
        filename = os.path.basename(task['path'])
        out_name = self.build_output_name(task['name_template'], task['path'])
        ext = {'JPEG':'.jpg', 'PNG':'.png', 'WEBP':'.webp'}[task['format']]
        out_full = out_name + ext
        rot = task['rotation']
        rot_display = {"0°":"无", "90°":"左90", "-90°":"右90", "180°":"180"}.get(rot, rot)
        flip = ""
        if task['h_flip'] and task['v_flip']:
            flip = "HV"
        elif task['h_flip']:
            flip = "H"
        elif task['v_flip']:
            flip = "V"
        else:
            flip = "无"
        mode = task['resize_mode']
        if mode == "精确 (WxH)":
            size = f"{task['resize_w']}x{task['resize_h']}"
        elif mode == "限制长边":
            size = f"长边{task['resize_w']}"
        elif mode == "限制短边":
            size = f"短边{task['resize_w']}"
        else:
            size = "原尺寸"
        crop_str = ""
        if task.get('crop_enabled', False):
            crop_str = f" 裁剪:{task['crop_x']},{task['crop_y']},{task['crop_w']},{task['crop_h']}"
        param_str = f"[{task['format']} Q{task['quality']} {rot_display} {flip} {size}{crop_str}]"
        return f"{filename} → {out_full} {param_str}"

    def select_output_dir(self):
        d = filedialog.askdirectory(initialdir=self.output_dir.get())
        if d:
            self.output_dir.set(d)
            self.save_settings_and_presets()

    def update_template_preview(self, event=None):
        fmt = self.format_var.get()
        qual = self.quality_var.get()
        rot = self.rotation_var.get()
        flip = []
        if self.h_flip_var.get(): flip.append("水平")
        if self.v_flip_var.get(): flip.append("垂直")
        flip_str = " | ".join(flip) if flip else "无翻转"
        mode = self.resize_mode_var.get()
        size_info = ""
        if mode == "精确 (WxH)":
            size_info = f" | 尺寸: {self.resize_width_var.get()}x{self.resize_height_var.get()} (精确)"
        elif mode == "限制长边":
            size_info = f" | 长边: {self.resize_width_var.get()}px"
        elif mode == "限制短边":
            size_info = f" | 短边: {self.resize_width_var.get()}px"
        else:
            size_info = " | 不调整尺寸"
        crop_info = ""
        if self.crop_enabled_var.get():
            crop_info = f" | 裁剪: x={self.crop_x_var.get()} y={self.crop_y_var.get()} w={self.crop_w_var.get()} h={self.crop_h_var.get()}"
        template = self.name_template_var.get()
        example_out = "image"
        if template == "{Folder name}{Filename}":
            example_out = "folderimage"
        self.template_preview_label.config(
            text=f"模板: {fmt} | Q{qual} | {rot} | {flip_str}{size_info}{crop_info} | 输出示例: {example_out}.{fmt.lower()}"
        )

    def apply_resize(self, img, mode, param_w, param_h):
        if mode == "无调整":
            return img
        orig_w, orig_h = img.size
        if mode == "精确 (WxH)":
            new_w, new_h = param_w, param_h
        elif mode == "限制长边":
            max_side = param_w
            if orig_w >= orig_h:
                new_w = max_side
                new_h = max(1, int(orig_h * (max_side / orig_w)))
            else:
                new_h = max_side
                new_w = max(1, int(orig_w * (max_side / orig_h)))
        elif mode == "限制短边":
            min_side = param_w
            if orig_w <= orig_h:
                new_w = min_side
                new_h = max(1, int(orig_h * (min_side / orig_w)))
            else:
                new_h = min_side
                new_w = max(1, int(orig_w * (min_side / orig_h)))
        else:
            return img
        if new_w <= 0 or new_h <= 0:
            return img
        return img.resize((new_w, new_h), Image.LANCZOS)

    def build_output_name(self, template, file_path):
        dirname = os.path.dirname(file_path)
        folder_name = os.path.basename(dirname)
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        if template == "{Filename}":
            return base_name
        elif template == "{Folder name}{Filename}":
            return folder_name + base_name
        else:
            return base_name

    # ========== 拖放文件夹支持 ==========
    def on_drop(self, event):
        if not DND_AVAILABLE:
            return
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法添加新任务")
            return
        files = self._parse_dropped_files(event.data)
        image_files = []
        for fp in files:
            fp = fp.strip('{}')
            if os.path.isdir(fp):
                for root, dirs, filenames in os.walk(fp):
                    for f in filenames:
                        if os.path.splitext(f)[1].lower() in ['.jpg','.jpeg','.png','.webp','.bmp']:
                            image_files.append(os.path.join(root, f))
            elif os.path.isfile(fp) and os.path.splitext(fp)[1].lower() in ['.jpg','.jpeg','.png','.webp','.bmp']:
                image_files.append(fp)
        if not image_files:
            messagebox.showinfo("提示", "未检测到支持的图片")
            return
        self._add_image_paths(image_files)

    def _parse_dropped_files(self, data):
        data = data.strip()
        if not data:
            return []
        if data.startswith('{') and data.endswith('}'):
            return [p.strip() for p in data[1:-1].split('} {')]
        return data.split()

    def on_task_select(self, event):
        sel = self.task_listbox.curselection()
        if len(sel) == 1:
            self.preview_image(self.tasks[sel[0]])

    # ========== 预览（内存泄漏修复） ==========
    def preview_image(self, task):
        if self.current_preview_img:
            del self.current_preview_img
        self.current_preview_img = None
        try:
            img = Image.open(task['path'])
            angle = int(task['rotation'].rstrip('°'))
            if angle != 0:
                img = img.rotate(angle, expand=True, resample=Image.NEAREST)
            if task['h_flip']:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            if task['v_flip']:
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
            if task['resize_mode'] != "无调整":
                img = self.apply_resize(img, task['resize_mode'], task['resize_w'], task['resize_h'])
            if task.get('crop_enabled', False):
                w_cur, h_cur = img.size
                x = self.eval_crop_expr(task['crop_x'], w_cur, h_cur)
                y = self.eval_crop_expr(task['crop_y'], w_cur, h_cur)
                w = self.eval_crop_expr(task['crop_w'], w_cur, h_cur)
                h = self.eval_crop_expr(task['crop_h'], w_cur, h_cur)
                x = max(0, min(x, w_cur-1))
                y = max(0, min(y, h_cur-1))
                w = min(w, w_cur - x)
                h = min(h, h_cur - y)
                if w > 0 and h > 0:
                    img = img.crop((x, y, x+w, y+h))
            cw = max(1, self.preview_canvas.winfo_width())
            ch = max(1, self.preview_canvas.winfo_height())
            img.thumbnail((cw, ch), Image.NEAREST)
            photo = ImageTk.PhotoImage(img)
            self.current_preview_img = photo
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(cw//2, ch//2, image=photo, anchor=tk.CENTER)
        except Exception as e:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(10, 10, anchor=tk.NW, text=f"预览失败: {e}", fill="red")

    # ========== 编辑任务对话框 ==========
    def edit_task_dialog(self, idx, task):
        dlg = Toplevel(self)
        dlg.title("编辑任务参数")
        dlg.transient(self)
        dlg.grab_set()
        dlg.lift()
        dlg.focus_force()
        dlg.geometry("540x280")
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - dlg.winfo_width()) // 2
        y = self.winfo_y() + (self.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")

        # 第一行：格式+质量
        row1 = ttk.Frame(dlg)
        row1.pack(fill=tk.X, pady=5, padx=10)
        ttk.Label(row1, text="目标格式:").pack(side=tk.LEFT, padx=5)
        fmt_var = tk.StringVar(value=task['format'])
        fmt_combo = ttk.Combobox(row1, textvariable=fmt_var, values=["JPEG","PNG","WEBP"], state="readonly", width=8)
        fmt_combo.pack(side=tk.LEFT, padx=5)
        ttk.Label(row1, text="质量:").pack(side=tk.LEFT, padx=(15,5))
        qual_var = tk.IntVar(value=task['quality'])
        qual_scale = ttk.Scale(row1, from_=1, to=100, variable=qual_var, orient=tk.HORIZONTAL, length=150)
        qual_scale.pack(side=tk.LEFT, padx=5)
        qual_label = ttk.Label(row1, text=str(task['quality']), width=3)
        qual_label.pack(side=tk.LEFT)
        qual_var.trace_add("write", lambda *a: qual_label.config(text=str(qual_var.get())))

        # 第二行：旋转+翻转
        row2 = ttk.Frame(dlg)
        row2.pack(fill=tk.X, pady=5, padx=10)
        ttk.Label(row2, text="旋转:").pack(side=tk.LEFT, padx=5)
        rot_var = tk.StringVar(value=task['rotation'])
        rot_frame = ttk.Frame(row2)
        rot_frame.pack(side=tk.LEFT)
        for text, val in [("无", "0°"), ("左90", "90°"), ("右90", "-90°"), ("180", "180°")]:
            ttk.Radiobutton(rot_frame, text=text, variable=rot_var, value=val).pack(side=tk.LEFT, padx=2)
        ttk.Label(row2, text="翻转:").pack(side=tk.LEFT, padx=(20,5))
        h_var = tk.BooleanVar(value=task['h_flip'])
        v_var = tk.BooleanVar(value=task['v_flip'])
        ttk.Checkbutton(row2, text="水平", variable=h_var).pack(side=tk.LEFT, padx=3)
        ttk.Checkbutton(row2, text="垂直", variable=v_var).pack(side=tk.LEFT, padx=3)

        # 第三行：尺寸调整
        row3 = ttk.Frame(dlg)
        row3.pack(fill=tk.X, pady=5, padx=10)
        ttk.Label(row3, text="尺寸调整模式:").pack(side=tk.LEFT, padx=5)
        mode_var = tk.StringVar(value=task['resize_mode'])
        mode_combo = ttk.Combobox(row3, textvariable=mode_var,
                                  values=["无调整", "精确 (WxH)", "限制长边", "限制短边"],
                                  state="readonly", width=14)
        mode_combo.pack(side=tk.LEFT, padx=5)
        
        width_label_edit = ttk.Label(row3, text="宽:")
        width_label_edit.pack(side=tk.LEFT, padx=(5,2))
        w_var = tk.IntVar(value=task['resize_w'])
        w_spin = ttk.Spinbox(row3, from_=1, to=9999, textvariable=w_var, width=6)
        w_spin.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(row3, text="高:").pack(side=tk.LEFT, padx=(5,2))
        h_var2 = tk.IntVar(value=task['resize_h'])
        h_spin = ttk.Spinbox(row3, from_=1, to=9999, textvariable=h_var2, width=6)
        h_spin.pack(side=tk.LEFT, padx=2)
        
        # 绑定模式切换事件，复用公共函数
        def update_edit_ui(*args):
            self._apply_resize_mode_ui(mode_var.get(), width_label_edit, h_spin)
        
        mode_combo.bind("<<ComboboxSelected>>", update_edit_ui)
        # 初始化界面（根据当前任务模式）
        update_edit_ui()

        # 第四行：裁剪
        row4 = ttk.Frame(dlg)
        row4.pack(fill=tk.X, pady=5, padx=10)
        crop_enabled_var = tk.BooleanVar(value=task.get('crop_enabled', False))
        ttk.Checkbutton(row4, text="启用裁剪", variable=crop_enabled_var).pack(side=tk.LEFT, padx=2)
        ttk.Label(row4, text="x:").pack(side=tk.LEFT, padx=(5,0))
        crop_x_var = tk.StringVar(value=task.get('crop_x', '0'))
        ttk.Entry(row4, textvariable=crop_x_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(row4, text="y:").pack(side=tk.LEFT)
        crop_y_var = tk.StringVar(value=task.get('crop_y', '0'))
        ttk.Entry(row4, textvariable=crop_y_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(row4, text="w:").pack(side=tk.LEFT)
        crop_w_var = tk.StringVar(value=task.get('crop_w', 'iw'))
        ttk.Entry(row4, textvariable=crop_w_var, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(row4, text="h:").pack(side=tk.LEFT)
        crop_h_var = tk.StringVar(value=task.get('crop_h', 'ih'))
        ttk.Entry(row4, textvariable=crop_h_var, width=6).pack(side=tk.LEFT, padx=2)

        # 第五行：输出名称模板 + 重名处理 + EXIF
        row5 = ttk.Frame(dlg)
        row5.pack(fill=tk.X, pady=5, padx=10)
        ttk.Label(row5, text="输出名称模板:").pack(side=tk.LEFT, padx=5)
        name_var = tk.StringVar(value=task['name_template'])
        name_combo = ttk.Combobox(row5, textvariable=name_var,
                                  values=["{Filename}", "{Folder name}{Filename}"],
                                  state="readonly", width=20)
        name_combo.pack(side=tk.LEFT, padx=5)
        ttk.Label(row5, text="重名处理:").pack(side=tk.LEFT, padx=(10,2))
        dup_var = tk.StringVar(value=task.get('duplicate_mode', self.duplicate_mode.get()))
        dup_combo = ttk.Combobox(row5, textvariable=dup_var,
                                 values=["覆盖", "自动重命名"], state="readonly", width=10)
        dup_combo.pack(side=tk.LEFT, padx=2)
        keep_exif_var = tk.BooleanVar(value=task.get('keep_exif', self.keep_exif_var.get()))
        ttk.Checkbutton(row5, text="保留EXIF", variable=keep_exif_var).pack(side=tk.LEFT, padx=5)

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=15)
        def save():
            task.update({
                'format': fmt_var.get(),
                'quality': qual_var.get(),
                'rotation': rot_var.get(),
                'h_flip': h_var.get(),
                'v_flip': v_var.get(),
                'resize_mode': mode_var.get(),
                'resize_w': w_var.get(),
                'resize_h': h_var2.get(),
                'name_template': name_var.get(),
                'crop_enabled': crop_enabled_var.get(),
                'crop_x': crop_x_var.get(),
                'crop_y': crop_y_var.get(),
                'crop_w': crop_w_var.get(),
                'crop_h': crop_h_var.get(),
                'duplicate_mode': dup_var.get(),
                'keep_exif': keep_exif_var.get()
            })
            new_display = self.get_task_display_text(task)
            self.task_listbox.delete(idx)
            self.task_listbox.insert(idx, new_display)
            self.preview_image(task)
            dlg.destroy()
        ttk.Button(btn_frame, text="保存", command=save).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=10)

    # ========== 任务管理 ==========
    def remove_selected(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法删除任务")
            return
        for i in reversed(self.task_listbox.curselection()):
            del self.tasks[i]
            self.task_listbox.delete(i)
        self.preview_canvas.delete("all")
        self.save_current_state_to_history()

    def clear_tasks(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法清空列表")
            return
        self.tasks.clear()
        self.task_listbox.delete(0, tk.END)
        self.preview_canvas.delete("all")
        self.progress_var.set(0)
        self.progress_label.config(text="就绪")
        self.save_current_state_to_history()

    # ========== 预设功能 ==========
    def load_presets_list(self):
        names = list(self.presets.keys())
        self.preset_combo['values'] = names
        if names:
            self.preset_combo.set(names[0])
        else:
            self.preset_combo.set('')

    def on_preset_selected(self, event=None):
        pass

    def save_preset(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法保存预设")
            return
        name = simpledialog.askstring("保存预设", "请输入预设名称:", parent=self)
        if not name:
            return
        if name in self.presets:
            if not messagebox.askyesno("确认覆盖", f"预设 '{name}' 已存在，是否覆盖？"):
                return
        preset_data = {
            'output_dir': self.output_dir.get(),
            'format': self.format_var.get(),
            'quality': self.quality_var.get(),
            'rotation': self.rotation_var.get(),
            'h_flip': self.h_flip_var.get(),
            'v_flip': self.v_flip_var.get(),
            'resize_mode': self.resize_mode_var.get(),
            'resize_w': self.resize_width_var.get(),
            'resize_h': self.resize_height_var.get(),
            'name_template': self.name_template_var.get(),
            'crop_enabled': self.crop_enabled_var.get(),
            'crop_x': self.crop_x_var.get(),
            'crop_y': self.crop_y_var.get(),
            'crop_w': self.crop_w_var.get(),
            'crop_h': self.crop_h_var.get(),
            'keep_exif': self.keep_exif_var.get()
        }
        self.presets[name] = preset_data
        self.save_settings_and_presets()
        self.preset_combo['values'] = list(self.presets.keys())
        self.preset_combo.set(name)
        messagebox.showinfo("成功", f"预设 '{name}' 已保存")

    def load_preset(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法加载预设")
            return
        name = self.preset_combo.get()
        if not name:
            messagebox.showwarning("警告", "请先选择一个预设")
            return
        if name not in self.presets:
            messagebox.showerror("错误", f"预设 '{name}' 不存在")
            return
        p = self.presets[name]
        self.output_dir.set(p.get('output_dir', os.getcwd()))
        self.format_var.set(p.get('format', 'JPEG'))
        self.quality_var.set(p.get('quality', 85))
        self.rotation_var.set(p.get('rotation', '0°'))
        self.h_flip_var.set(p.get('h_flip', False))
        self.v_flip_var.set(p.get('v_flip', False))
        self.resize_mode_var.set(p.get('resize_mode', '无调整'))
        self.resize_width_var.set(p.get('resize_w', 800))
        self.resize_height_var.set(p.get('resize_h', 600))
        self.name_template_var.set(p.get('name_template', '{Filename}'))
        self.crop_enabled_var.set(p.get('crop_enabled', False))
        self.crop_x_var.set(p.get('crop_x', '0'))
        self.crop_y_var.set(p.get('crop_y', '0'))
        self.crop_w_var.set(p.get('crop_w', 'iw'))
        self.crop_h_var.set(p.get('crop_h', 'ih'))
        self.keep_exif_var.set(p.get('keep_exif', False))
        self.update_template_preview()
        messagebox.showinfo("成功", f"预设 '{name}' 已加载")

    # ========== 多线程转换 ==========
    def start_convert(self):
        if self.converting:
            messagebox.showwarning("警告", "转换正在进行中，请稍后")
            return
        if not self.tasks:
            messagebox.showwarning("警告", "任务列表为空")
            return
        if len(self.tasks) > 50:
            if not messagebox.askyesno("确认", f"共有 {len(self.tasks)} 个任务，是否继续？"):
                return

        out_dir = self.output_dir.get()
        os.makedirs(out_dir, exist_ok=True)

        self.start_btn.config(state=tk.DISABLED)
        self.converting = True
        self.enable_task_edit_buttons(False)

        self.total_tasks = len(self.tasks)
        self.progress_bar['maximum'] = self.total_tasks
        self.progress_var.set(0)
        self.progress_label.config(text=f"0 / {self.total_tasks}")

        tasks_list = self.tasks.copy()
        max_workers = self.thread_count_var.get()
        if max_workers < 1:
            max_workers = 1

        if self.executor:
            self.executor.shutdown(wait=False)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        self.futures = []
        for idx, task in enumerate(tasks_list):
            future = self.executor.submit(self._convert_single, task, out_dir, idx)
            self.futures.append((future, idx))

        self.processed_indices.clear()
        self.after(100, self._poll_futures)

    def _poll_futures(self):
        if not self.futures:
            self._on_convert_finished()
            return

        remaining = []
        for future, idx in self.futures:
            if future.done():
                try:
                    idx, success, error = future.result()
                    self._update_task_item(idx, success, error)
                    self.progress_var.set(self.progress_var.get() + 1)
                    self.progress_label.config(text=f"{self.progress_var.get()} / {self.total_tasks}")
                except Exception as e:
                    self._update_task_item(idx, False, str(e))
            else:
                remaining.append((future, idx))
        self.futures = remaining
        self.after(100, self._poll_futures)

    def _update_task_item(self, idx, success, error):
        if idx in self.processed_indices:
            return
        self.processed_indices.add(idx)
        current_text = self.task_listbox.get(idx)
        if success:
            if " ✓" not in current_text:
                new_text = current_text + " ✓"
                self.task_listbox.delete(idx)
                self.task_listbox.insert(idx, new_text)
                self.task_listbox.itemconfig(idx, fg='green')
        else:
            if " ✗" not in current_text:
                new_text = current_text + f" ✗ {error}"
                self.task_listbox.delete(idx)
                self.task_listbox.insert(idx, new_text)
                self.task_listbox.itemconfig(idx, fg='red')

    def _on_convert_finished(self):
        self.converting = False
        self.start_btn.config(state=tk.NORMAL)
        self.enable_task_edit_buttons(True)
        if self.executor:
            self.executor.shutdown(wait=False)
        success_count = sum(1 for i in range(len(self.tasks)) if " ✓" in self.task_listbox.get(i))
        messagebox.showinfo("完成", f"转换完成\n成功: {success_count}\n失败: {len(self.tasks)-success_count}\n输出目录: {self.output_dir.get()}")
        self.progress_label.config(text="完成")

    # ========== 转换单张图片（线程安全保存） ==========
    def _convert_single(self, task, out_dir, idx):
        src = task['path']
        fmt = task['format']
        qual = task['quality']
        angle = int(task['rotation'].rstrip('°'))
        h_flip = task['h_flip']
        v_flip = task['v_flip']
        mode = task['resize_mode']
        w = task['resize_w']
        h = task['resize_h']
        name_tmpl = task['name_template']
        crop_enabled = task.get('crop_enabled', False)
        crop_x = task.get('crop_x', '0')
        crop_y = task.get('crop_y', '0')
        crop_w = task.get('crop_w', 'iw')
        crop_h = task.get('crop_h', 'ih')
        dup_mode = task.get('duplicate_mode', self.duplicate_mode.get())
        keep_exif = task.get('keep_exif', self.keep_exif_var.get())

        out_name = self.build_output_name(name_tmpl, src)
        ext_map = {'JPEG':'.jpg', 'PNG':'.png', 'WEBP':'.webp'}
        base_out = os.path.join(out_dir, out_name + ext_map[fmt])

        out_path = self._get_unique_filename(base_out, dup_mode)

        try:
            img = Image.open(src)
            if angle != 0:
                img = img.rotate(angle, expand=True, resample=Image.BICUBIC)
            if h_flip:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            if v_flip:
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
            if mode != "无调整":
                img = self.apply_resize(img, mode, w, h)
            if crop_enabled:
                w_cur, h_cur = img.size
                x = self.eval_crop_expr(crop_x, w_cur, h_cur)
                y = self.eval_crop_expr(crop_y, w_cur, h_cur)
                w_crop = self.eval_crop_expr(crop_w, w_cur, h_cur)
                h_crop = self.eval_crop_expr(crop_h, w_cur, h_cur)
                x = max(0, min(x, w_cur-1))
                y = max(0, min(y, h_cur-1))
                w_crop = min(w_crop, w_cur - x)
                h_crop = min(h_crop, h_cur - y)
                if w_crop > 0 and h_crop > 0:
                    img = img.crop((x, y, x+w_crop, y+h_crop))

            exif = None
            if keep_exif and hasattr(img, 'info') and 'exif' in img.info:
                exif = img.info['exif']

            save_kwargs = {}
            if fmt == 'JPEG':
                if img.mode in ('RGBA','LA','P'):
                    img = img.convert('RGB')
                save_kwargs = {'quality': qual, 'optimize': True}
                if exif:
                    save_kwargs['exif'] = exif
                img.save(out_path, 'JPEG', **save_kwargs)
            elif fmt == 'PNG':
                comp = max(0, min(9, int((100 - qual) / 11.1)))
                save_kwargs = {'compress_level': comp}
                img.save(out_path, 'PNG', **save_kwargs)
            elif fmt == 'WEBP':
                save_kwargs = {'quality': qual, 'lossless': False}
                if exif:
                    save_kwargs['exif'] = exif
                img.save(out_path, 'WEBP', **save_kwargs)
            return (idx, True, None)
        except Exception as e:
            return (idx, False, str(e))

    def _get_unique_filename(self, base_path, dup_mode):
        if dup_mode == "覆盖":
            return base_path
        dir_name = os.path.dirname(base_path)
        base_name = os.path.basename(base_path)
        name, ext = os.path.splitext(base_name)
        counter = 1
        candidate = base_path
        while True:
            try:
                fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return candidate
            except FileExistsError:
                candidate = os.path.join(dir_name, f"{name}_{counter}{ext}")
                counter += 1
            except OSError:
                candidate = os.path.join(dir_name, f"{name}_{counter}{ext}")
                counter += 1

if __name__ == "__main__":
    app = ImageConverter()
    app.mainloop()