import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import os
import re
import ast

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

# ---------- 提示类 ----------
class ToolTip:
    def __init__(self, widget, text, offset_x=15, offset_y=15, wraplength=400):
        self.widget = widget
        self.text = text
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.wraplength = wraplength
        self.tip_window = None
        widget.bind('<Enter>', self.show_tip)
        widget.bind('<Leave>', self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window:
            self.hide_tip()
        mouse_x = self.widget.winfo_pointerx()
        mouse_y = self.widget.winfo_pointery()
        ideal_x = mouse_x + self.offset_x
        ideal_y = mouse_y + self.offset_y
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{ideal_x}+{ideal_y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         wraplength=self.wraplength)
        label.pack()
        tw.update_idletasks()
        win_width = tw.winfo_width()
        win_height = tw.winfo_height()
        screen_width = tw.winfo_screenwidth()
        screen_height = tw.winfo_screenheight()
        x = max(0, min(ideal_x, screen_width - win_width))
        y = max(0, min(ideal_y, screen_height - win_height))
        if x <= mouse_x <= x + win_width and y <= mouse_y <= y + win_height:
            dx = 10 if ideal_x < screen_width // 2 else -10
            dy = 10 if ideal_y < screen_height // 2 else -10
            x = max(0, min(ideal_x + dx, screen_width - win_width))
            y = max(0, min(ideal_y + dy, screen_height - win_height))
        tw.wm_geometry(f"+{x}+{y}")

    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

# ---------- 主程序 ----------
class App:
    def __init__(self, master):
        self.master = master
        master.title("图片切割程序")
        self.preview_window = None   # 预览子窗口的引用
        self.preview_button = None   # 稍后创建
        self.original_img = None     # 原始 PIL Image
        self.scale_factor = 1.0      # 仅在子窗口内使用，但保留
        self.img_pos = (0, 0, 0, 0)  # 子窗口中图片的位置和尺寸

        # ----- 左侧控件区域 -----
        # 第一行：切割图片
        tk.Label(master, text="切割的图片:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.entry1 = tk.Entry(master, width=50)
        self.entry1.grid(row=0, column=1, padx=5, pady=5)
        tk.Button(master, text="选择文件", command=self.select_file).grid(row=0, column=2, padx=5, pady=5)

        # 第二行：保存路径
        tk.Label(master, text="保存的路径:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.entry2 = tk.Entry(master, width=50)
        self.entry2.grid(row=1, column=1, padx=5, pady=5)
        tk.Button(master, text="选择文件夹", command=self.select_folder).grid(row=1, column=2, padx=5, pady=5)

        master.columnconfigure(0, weight=0)  # 标签列，不扩展
        master.columnconfigure(1, weight=1)  # 输入框列，可扩展
        master.columnconfigure(2, weight=0)  # 按钮列，不扩展

        # 切割模式选择
        mode_frame = tk.Frame(master)
        mode_frame.grid(row=2, column=0, columnspan=3, sticky="w", padx=5, pady=5)
        tk.Label(mode_frame, text="切割模式:").pack(side=tk.LEFT)
        self.cut_mode = tk.StringVar(value="grid")
        
        rb_grid = tk.Radiobutton(mode_frame, text="标准网格模式", variable=self.cut_mode,
                                 value="grid", command=self.on_mode_changed)
        rb_grid.pack(side=tk.LEFT, padx=10)
        
        rb_smart = tk.Radiobutton(mode_frame, text="智能数字模式", variable=self.cut_mode,
                                  value="smart", command=self.on_mode_changed)
        rb_smart.pack(side=tk.LEFT, padx=10)
        ToolTip(rb_smart, 
                text="【智能数字模式】格式说明\n"
                     "\n"
                     "一、块数指定（两种方式）：\n"
                     "  • 紧凑数字串：每位数字表示一列的块数（只支持1-9）\n"
                     "    例：123 → 三列，每列内部的块数分别为 1块、2块、3块\n"
                     "  • 逗号分隔多位数：每个数可以是任意正整数\n"
                     "    例：22,22,22,22 → 四列，每列内部均有 22 块\n"
                     "    ※ 紧凑数字串的长度（或逗号分隔的个数）即为该方向切割的总份数（列数/行数）\n"
                     "\n"
                     "二、比例可选项（可选，不写则列宽均匀分配）：\n"
                     "  • 紧凑比例：数字串长度须与列数相同，每位数字×10%为宽度比例\n"
                     "    例：123:118 → 三列宽度比 10%:10%:80%\n"
                     "  • 逗号比例：数字串个数须与列数相同，数值直接作为比例（自动归一化）\n"
                     "    例：123:10,10,80 或 22,22,22:33.3,33.3,33.4\n"
                     "\n"
                     "三、内部块如何分割？\n"
                     "   每列指定了块数后，该列会从上到下平均切成这么多块（高度相等）。\n"
                     "   如果选择垂直方向，则每行从左到右平均切成指定数量的块（宽度相等）。\n"
                     "\n"
                     "四、示例说明：\n"
                     "  水平方向（列切割）：\n"
                     "    22,22,22 → 三列等宽，每列内部再平均切成22块（共66张小图）\n"
                     "    22,22,22:10,10,80 → 三列宽度比10%:10%:80%，每列内各22块均分高度\n"
                     "  垂直方向（行切割）：\n"
                     "    3,5 → 两行高度相等，第一行切成3块，第二行切成5块（共8张小图）\n"
                     "\n"
                     "注意：紧凑数字串与紧凑比例中的每位数字只能是0-9。\n"
                     "逗号分隔的块数或比例支持整数或小数。",
                wraplength=500)
        
        rb_advanced = tk.Radiobutton(mode_frame, text="高级嵌套模式", variable=self.cut_mode,
                                     value="advanced", command=self.on_mode_changed)
        rb_advanced.pack(side=tk.LEFT, padx=10)
        ToolTip(rb_advanced, 
                text="【高级嵌套模式】详细说明\n"
                     "\n"
                     "基本格式（组间宽度/高度相等）\n"
                     "   [[块数1, [比例列表1]], [块数2, [比例列表2]], ...]\n"
                     "   示例（水平三列，每列等宽）：\n"
                     "     [[1,[100]], [2,[30,70]], [3,[20,30,50]]]\n"
                     "   → 第1列：1块（整列100%）\n"
                     "   → 第2列：2块，高度比 30% : 70%\n"
                     "   → 第3列：3块，高度比 20% : 30% : 50%\n"
                     "\n"
                     "自定义组比例（各组宽度/高度不等）\n"
                     "   格式：组比例 | 基本格式\n"
                     "   组比例：用逗号分隔的正数（自动归一化为百分比）\n"
                     "   示例：10,10,80 | [[1,[100]],[2,[30,70]],[3,[20,30,50]]]\n"
                     "   → 三列宽度比 10% : 10% : 80%\n"
                     "   → 内部块分割规则与基本格式相同\n"
                     "\n"
                     "垂直方向同理\n"
                     "如果某组内部只有1块且比例为100%，可以省略精简为[1]。\n\n"
                     "分块不想输出可添加d标记，例如 [3,[20,30,d50]]\n",
                wraplength=450)

        # 自由模式单选按钮
        rb_free = tk.Radiobutton(mode_frame, text="自由模式", variable=self.cut_mode,
                                 value="free", command=self.on_mode_changed)
        rb_free.pack(side=tk.LEFT, padx=10)
        ToolTip(rb_free, 
                text="【自由模式】格式说明\n"
                     "每行定义一个矩形：x, y, width, height\n"
                     "支持逗号或分号分隔多个矩形（同一行内用分号）\n"
                     "示例：\n"
                     "10,10,200,150\n"
                     "250,30,180,200;50,200,300,100\n"
                     "注意：坐标和尺寸为整数像素，不能超出图片边界",
                wraplength=350)

        # 公共方向选择（智能/高级模式共用）
        self.dir_frame = tk.LabelFrame(master, text="切割方向 (仅对智能/高级模式有效)", padx=5, pady=5)
        self.dir_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        dir_inner = tk.Frame(self.dir_frame)
        dir_inner.pack(anchor="w")
        self.direction = tk.StringVar(value="horizontal")
        tk.Radiobutton(dir_inner, text="水平方向", variable=self.direction,
                       value="horizontal", command=self.on_dir_changed).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(dir_inner, text="垂直方向", variable=self.direction,
                       value="vertical", command=self.on_dir_changed).pack(side=tk.LEFT, padx=5)

        # 标准网格模式参数区域
        self.grid_frame = tk.LabelFrame(master, text="标准网格参数", padx=5, pady=5)
        self.grid_frame.grid(row=4, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        tk.Label(self.grid_frame, text="行数:").grid(row=0, column=0, padx=5, pady=2)
        self.rows_entry = tk.Entry(self.grid_frame, width=10)
        self.rows_entry.grid(row=0, column=1, padx=5, pady=2)
        self.rows_entry.insert(0, "2")
        self.rows_entry.bind("<KeyRelease>", self.on_grid_param_changed)
        tk.Label(self.grid_frame, text="列数:").grid(row=0, column=2, padx=5, pady=2)
        self.cols_entry = tk.Entry(self.grid_frame, width=10)
        self.cols_entry.grid(row=0, column=3, padx=5, pady=2)
        self.cols_entry.insert(0, "2")
        self.cols_entry.bind("<KeyRelease>", self.on_grid_param_changed)

        # 智能数字模式参数区域
        self.smart_frame = tk.LabelFrame(master, text="智能数字模式参数", padx=5, pady=5)
        self.smart_frame.grid(row=5, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        tk.Label(self.smart_frame, text="数字串与比例 (例如 123:118 或 123:10,10,80):").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.digit_entry = tk.Entry(self.smart_frame, width=30)
        self.digit_entry.grid(row=0, column=1, padx=5, pady=5)
        self.digit_entry.insert(0, "323")
        self.digit_entry.bind("<KeyRelease>", self.on_smart_param_changed)

        # 高级嵌套模式参数区域
        self.advanced_frame = tk.LabelFrame(master, text="高级嵌套模式参数", padx=5, pady=5)
        self.advanced_frame.grid(row=6, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        self.advanced_text = tk.Text(self.advanced_frame, height=6, width=50, font=("Consolas", 10))
        self.advanced_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.advanced_text.insert("1.0", "[[1,[100]], [2,[30,70]], [3,[20,30,50]]]")
        self.advanced_text.bind("<KeyRelease>", self.on_advanced_param_changed)

        # 自由模式参数区域（新增）
        self.free_frame = tk.LabelFrame(master, text="自由模式参数 (矩形定义)", padx=5, pady=5)
        self.free_frame.grid(row=7, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        self.free_text = tk.Text(self.free_frame, height=8, width=60, font=("Consolas", 10))
        self.free_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.free_text.insert("1.0", "10,10,200,150\n250,30,180,200;50,200,300,100")
        self.free_text.bind("<KeyRelease>", self.on_free_param_changed)

        # 输出格式与质量
        format_frame = tk.Frame(master)
        format_frame.grid(row=8, column=0, columnspan=3, sticky="w", padx=5, pady=5)
        tk.Label(format_frame, text="输出格式:").pack(side=tk.LEFT, padx=2)
        self.format_var = tk.StringVar(value="WEBP")
        self.format_combo = ttk.Combobox(format_frame, textvariable=self.format_var,
                                         values=["PNG", "JPEG", "BMP", "TIFF", "WEBP"],
                                         state="readonly", width=10)
        self.format_combo.pack(side=tk.LEFT, padx=5)
        self.format_combo.bind("<<ComboboxSelected>>", self.on_format_change)

        tk.Label(format_frame, text="质量:").pack(side=tk.LEFT, padx=5)
        self.quality_var = tk.StringVar(value="85")
        self.quality_entry = tk.Entry(format_frame, textvariable=self.quality_var, width=5)
        self.quality_entry.pack(side=tk.LEFT, padx=2)
        self.hint_label = tk.Label(format_frame, text="(JPEG:1-100, PNG:0-9)", fg="gray")
        self.hint_label.pack(side=tk.LEFT, padx=10)

        # 底部按钮（添加预览窗口按钮）
        bottom_frame = tk.Frame(master)
        bottom_frame.grid(row=9, column=0, columnspan=3, pady=10)
        self.preview_btn = tk.Button(bottom_frame, text="打开预览窗口", command=self.toggle_preview_window)
        self.preview_btn.pack(side=tk.LEFT, padx=10)
        tk.Button(bottom_frame, text="开始切割", command=self.start_cutting).pack(side=tk.LEFT, padx=10)
        tk.Button(bottom_frame, text="恢复默认", command=self.reset_parameters).pack(side=tk.LEFT, padx=10)
        tk.Button(bottom_frame, text="退出", command=self.quit_app).pack(side=tk.LEFT, padx=10)

        # 拖拽支持
        if HAS_DND:
            self.entry1.drop_target_register(DND_FILES)
            self.entry1.dnd_bind('<<Drop>>', self.on_drop_to_entry1)
            self.entry2.drop_target_register(DND_FILES)
            self.entry2.dnd_bind('<<Drop>>', self.on_drop_to_entry2)
            self.hint_label.config(text=self.hint_label.cget("text") + "  支持拖拽图片/文件夹")

        # 初始化模式显示
        self.on_mode_changed()
        self.update_dir_frame_visibility()

        # 主窗口关闭时同时关闭预览窗口
        master.protocol("WM_DELETE_WINDOW", self.quit_app)

    def reset_parameters(self):
        """恢复所有切割参数到初始状态（保留图片路径和保存路径）"""
        if not messagebox.askyesno("确认恢复", "确定要将所有切割参数恢复为默认值吗？\n（图片路径和保存路径不会改变）"):
            return
        
        # 1. 切割模式：标准网格模式
        self.cut_mode.set("grid")
        self.on_mode_changed()
        
        # 2. 标准网格参数：2行2列
        self.rows_entry.delete(0, tk.END)
        self.rows_entry.insert(0, "2")
        self.cols_entry.delete(0, tk.END)
        self.cols_entry.insert(0, "2")
        
        # 3. 智能数字模式参数：
        self.digit_entry.delete(0, tk.END)
        self.digit_entry.insert(0, "323")
        
        # 4. 高级嵌套模式参数：重置为默认嵌套结构（不带竖线）
        self.advanced_text.delete("1.0", tk.END)
        self.advanced_text.insert("1.0", "[[1,[100]], [2,[30,70]], [3,[20,30,50]]]")
        
        # 5. 自由模式参数：重置为示例
        self.free_text.delete("1.0", tk.END)
        self.free_text.insert("1.0", "10,10,200,150\n250,30,180,200\n50,200,300,100")
        
        # 6. 切割方向：重置为水平方向
        self.direction.set("horizontal")
        
        # 7. 输出格式：WEBP，质量：85
        self.format_var.set("WEBP")
        self.quality_var.set("85")
        self.on_format_change()
        
        # 8. 强制刷新预览（如果预览窗口已打开且有图片）
        self.refresh_preview()
        
        # 可选：重新调整主窗口大小以适应内容
        self.master.update_idletasks()
        req_width = self.master.winfo_reqwidth()
        req_height = self.master.winfo_reqheight()
        self.master.geometry(f"{req_width}x{req_height}")

    def toggle_preview_window(self):
        """切换预览窗口的打开/关闭状态"""
        if self.preview_window is not None and self.preview_window.winfo_exists():
            self.close_preview_window()
            self.preview_btn.config(text="打开预览窗口")
        else:
            self.open_preview_window()
            self.preview_btn.config(text="关闭预览窗口")

    def resize_preview_window_for_image(self):
        """根据当前图片比例调整已存在的预览窗口大小，并重新放置到主窗口右侧（或右对齐屏幕）"""
        if not self.preview_window or not self.preview_window.winfo_exists():
            return
        if not self.original_img:
            return
    
        img_w, img_h = self.original_img.size
        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()
        max_w = int(screen_w * 0.7)
        max_h = int(screen_h * 0.7)
    
        scale = min(max_w / img_w, max_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        new_w = max(300, new_w)
        new_h = max(200, new_h)
    
        # 获取主窗口位置
        main_x = self.master.winfo_x()
        main_y = self.master.winfo_y()
        main_w = self.master.winfo_width()
    
        # 计算新位置
        if main_x + main_w + new_w + 10 <= screen_w:
            pos_x = main_x + main_w + 10
        else:
            pos_x = screen_w - new_w - 10
        pos_y = main_y
        if pos_y + new_h > screen_h:
            pos_y = max(10, screen_h - new_h - 10)
    
        self.preview_window.geometry(f"{new_w}x{new_h}+{pos_x}+{pos_y}")

    # ---------- 预览子窗口管理 ----------
    def open_preview_window(self):
        if self.preview_window is not None and self.preview_window.winfo_exists():
            self.preview_window.lift()
            self.preview_window.focus_force()
            return
    
        # 获取主窗口位置
        main_x = self.master.winfo_x()
        main_y = self.master.winfo_y()
        main_w = self.master.winfo_width()
        main_h = self.master.winfo_height()
    
        # 根据图片尺寸计算预览窗口的初始大小
        if self.original_img:
            img_w, img_h = self.original_img.size
            screen_w = self.master.winfo_screenwidth()
            screen_h = self.master.winfo_screenheight()
            max_w = int(screen_w * 0.7)
            max_h = int(screen_h * 0.7)
            scale = min(max_w / img_w, max_h / img_h)
            preview_w = int(img_w * scale)
            preview_h = int(img_h * scale)
            preview_w = max(300, preview_w)
            preview_h = max(200, preview_h)
        else:
            preview_w, preview_h = 600, 500
    
        # 初始位置：主窗口右侧，垂直对齐
        pos_x = main_x + main_w + 10
        pos_y = main_y
    
        screen_w = self.master.winfo_screenwidth()
        if pos_x + preview_w > screen_w:
            pos_x = max(10, main_x - preview_w - 10)
    
        screen_h = self.master.winfo_screenheight()
        if pos_y + preview_h > screen_h:
            pos_y = max(10, screen_h - preview_h - 10)
    
        self.preview_window = tk.Toplevel(self.master)
        self.preview_window.title("图片预览")
        self.preview_window.attributes('-toolwindow', 1)
        self.preview_window.geometry(f"{preview_w}x{preview_h}+{pos_x}+{pos_y}")
    
        self.preview_canvas = tk.Canvas(self.preview_window, bg='#f0f0f0')
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        self.preview_canvas.bind("<Configure>", self.on_preview_canvas_resize)
    
        self.preview_window.protocol("WM_DELETE_WINDOW", self.close_preview_window)
    
        if self.original_img:
            self.update_preview_in_subwindow()

        self.preview_btn.config(text="关闭预览窗口")

    def close_preview_window(self):
        if self.preview_window:
            self.preview_window.destroy()
            self.preview_window = None
            self.preview_canvas = None
        self.preview_btn.config(text="打开预览窗口")

    def on_preview_canvas_resize(self, event):
        if self.original_img and self.preview_window and self.preview_canvas:
            self.update_preview_in_subwindow()

    def update_preview_in_subwindow(self):
        """根据当前图片和参数，在子窗口中更新显示（图片自适应画布大小）"""
        if not self.original_img or not self.preview_window or not self.preview_canvas:
            return
        cw = self.preview_canvas.winfo_width()
        ch = self.preview_canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            cw = self.preview_window.winfo_width()
            ch = self.preview_window.winfo_height()
            if cw <= 1 or ch <= 1:
                cw, ch = 600, 500
        img_w, img_h = self.original_img.size
        scale = min(cw / img_w, ch / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        resized = self.original_img.resize((new_w, new_h), Image.Resampling.NEAREST)
        self.preview_photo = ImageTk.PhotoImage(resized)
        x = (cw - new_w) // 2
        y = (ch - new_h) // 2
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(x, y, anchor=tk.NW, image=self.preview_photo, tags="preview_img")
        self.preview_img_pos = (x, y, new_w, new_h)
        mode = self.cut_mode.get()
        if mode == "grid":
            self.draw_grid_lines_sub()
        elif mode == "smart":
            self.draw_smart_lines_sub()
        elif mode == "advanced":
            self.draw_advanced_lines_sub()
        else:
            self.draw_free_lines_sub()

    # ---------- 子窗口绘图函数 ----------
    def draw_grid_lines_sub(self):
        if not self.original_img or not self.preview_canvas:
            return
        self.preview_canvas.delete("cut_line")
        try:
            rows = int(self.rows_entry.get())
            cols = int(self.cols_entry.get())
            if rows <= 0 or cols <= 0:
                return
        except:
            return
        x0, y0, pw, ph = self.preview_img_pos
        col_w = pw / cols
        row_h = ph / rows
        for i in range(1, cols):
            line_x = x0 + i * col_w
            self.preview_canvas.create_line(line_x, y0, line_x, y0+ph, fill="red", width=2, tags="cut_line")
        for i in range(1, rows):
            line_y = y0 + i * row_h
            self.preview_canvas.create_line(x0, line_y, x0+pw, line_y, fill="red", width=2, tags="cut_line")

    def draw_smart_lines_sub(self):
        if not self.original_img or not self.preview_canvas:
            return
        self.preview_canvas.delete("cut_line")
        blocks, ratios = self.parse_smart_pattern()
        if blocks is None:
            return
        direction = self.direction.get()
        x0, y0, pw, ph = self.preview_img_pos
        if direction == "horizontal":
            n = len(blocks)
            if ratios is None:
                col_widths = [pw / n] * n
            else:
                col_widths = [pw * (r / 100.0) for r in ratios]
            cum_x = [x0]
            for i in range(n):
                cum_x.append(cum_x[-1] + col_widths[i])
            for i in range(1, n):
                self.preview_canvas.create_line(cum_x[i], y0, cum_x[i], y0+ph, fill="red", width=2, tags="cut_line")
            for col_idx, blk in enumerate(blocks):
                left = cum_x[col_idx]
                right = cum_x[col_idx+1]
                blk_h = ph / blk
                for b in range(1, blk):
                    line_y = y0 + b * blk_h
                    self.preview_canvas.create_line(left, line_y, right, line_y, fill="blue", width=2, tags="cut_line")
        else:
            n = len(blocks)
            if ratios is None:
                row_heights = [ph / n] * n
            else:
                row_heights = [ph * (r / 100.0) for r in ratios]
            cum_y = [y0]
            for i in range(n):
                cum_y.append(cum_y[-1] + row_heights[i])
            for i in range(1, n):
                self.preview_canvas.create_line(x0, cum_y[i], x0+pw, cum_y[i], fill="red", width=2, tags="cut_line")
            for row_idx, blk in enumerate(blocks):
                top = cum_y[row_idx]
                bottom = cum_y[row_idx+1]
                blk_w = pw / blk
                for b in range(1, blk):
                    line_x = x0 + b * blk_w
                    self.preview_canvas.create_line(line_x, top, line_x, bottom, fill="blue", width=2, tags="cut_line")

    def draw_advanced_lines_sub(self):
        if not self.original_img or not self.preview_canvas:
            return
        self.preview_canvas.delete("cut_line")
        group_ratios, pattern = self.parse_advanced_pattern()
        if pattern is None:
            err_msg = getattr(self, 'advanced_parse_error', "格式错误")
            x0, y0, pw, ph = self.preview_img_pos
            max_width = max(200, pw // 2)
            self.preview_canvas.create_text(
                x0 + 10, y0 + 20, anchor="nw",
                text=f"高级模式解析失败：\n{err_msg}",
                fill="red", font=("", 10), width=max_width, tags="cut_line"
            )
            return
    
        direction = self.direction.get()
        x0, y0, pw, ph = self.preview_img_pos
    
        if direction == "horizontal":
            n = len(pattern)
            if group_ratios is None:
                col_widths = [pw / n] * n
            else:
                col_widths = [pw * (r / 100.0) for r in group_ratios]
            cum_x = [x0]
            for w in col_widths:
                cum_x.append(cum_x[-1] + w)
            # 组间红色竖线
            for i in range(1, n):
                self.preview_canvas.create_line(cum_x[i], y0, cum_x[i], y0+ph, fill="red", width=2, tags="cut_line")
            # 各组内部蓝色分割线
            for col_idx, (blk, ratios) in enumerate(pattern):
                left = cum_x[col_idx]
                right = cum_x[col_idx+1]
                if ratios is None:
                    # 均分内部块高度
                    blk_h = ph / blk
                    for b in range(1, blk):
                        line_y = y0 + b * blk_h
                        self.preview_canvas.create_line(left, line_y, right, line_y, fill="blue", width=2, tags="cut_line")
                else:
                    # 按比例分割内部块高度（ratios 为 [(百分比, flag), ...]）
                    cum_y = y0
                    for b, r in enumerate(ratios):
                        seg_h = ph * (r[0] / 100.0)   # 注意：取 r[0]
                        next_y = cum_y + seg_h
                        if b < blk - 1:
                            self.preview_canvas.create_line(left, next_y, right, next_y, fill="blue", width=2, tags="cut_line")
                        cum_y = next_y
        else:  # vertical
            n = len(pattern)
            if group_ratios is None:
                row_heights = [ph / n] * n
            else:
                row_heights = [ph * (r / 100.0) for r in group_ratios]
            cum_y = [y0]
            for h in row_heights:
                cum_y.append(cum_y[-1] + h)
            # 组间红色横线
            for i in range(1, n):
                self.preview_canvas.create_line(x0, cum_y[i], x0+pw, cum_y[i], fill="red", width=2, tags="cut_line")
            # 各组内部蓝色分割线
            for row_idx, (blk, ratios) in enumerate(pattern):
                top = cum_y[row_idx]
                bottom = cum_y[row_idx+1]
                if ratios is None:
                    # 均分内部块宽度
                    blk_w = pw / blk
                    for b in range(1, blk):
                        line_x = x0 + b * blk_w
                        self.preview_canvas.create_line(line_x, top, line_x, bottom, fill="blue", width=2, tags="cut_line")
                else:
                    # 按比例分割内部块宽度（ratios 为 [(百分比, flag), ...]）
                    cum_x = x0
                    for b, r in enumerate(ratios):
                        seg_w = pw * (r[0] / 100.0)   # 注意：取 r[0]
                        next_x = cum_x + seg_w
                        if b < blk - 1:
                            self.preview_canvas.create_line(next_x, top, next_x, bottom, fill="blue", width=2, tags="cut_line")
                        cum_x = next_x

    def draw_free_lines_sub(self):
        """在预览窗口中绘制自由模式的矩形框"""
        if not self.original_img or not self.preview_canvas:
            return
        self.preview_canvas.delete("cut_line")
        rects = self.parse_free_pattern()
        if rects is None:
            err_msg = getattr(self, 'free_parse_error', "格式错误")
            x0, y0, pw, ph = self.preview_img_pos
            max_width = max(200, pw // 2)
            self.preview_canvas.create_text(
                x0 + 10, y0 + 20, anchor="nw",
                text=f"自由模式解析失败：\n{err_msg}",
                fill="red", font=("", 10), width=max_width, tags="cut_line"
            )
            return
        # 获取原图尺寸和显示缩放比例
        img_w, img_h = self.original_img.size
        x0, y0, pw, ph = self.preview_img_pos
        scale_x = pw / img_w
        scale_y = ph / img_h
        for idx, (x, y, w, h) in enumerate(rects):
            display_x = x0 + x * scale_x
            display_y = y0 + y * scale_y
            display_w = w * scale_x
            display_h = h * scale_y
            self.preview_canvas.create_rectangle(display_x, display_y,
                                                 display_x + display_w, display_y + display_h,
                                                 outline="green", width=2, tags="cut_line")
            self.preview_canvas.create_text(display_x + 5, display_y + 5,
                                            text=str(idx+1), anchor="nw",
                                            fill="green", font=("", 10, "bold"), tags="cut_line")

    # ---------- 事件触发时同时更新子窗口 ----------
    def on_mode_changed(self):
        self.update_dir_frame_visibility()
        if self.cut_mode.get() == "grid":
            self.grid_frame.grid()
            self.smart_frame.grid_remove()
            self.advanced_frame.grid_remove()
            self.free_frame.grid_remove()
        elif self.cut_mode.get() == "smart":
            self.grid_frame.grid_remove()
            self.smart_frame.grid()
            self.advanced_frame.grid_remove()
            self.free_frame.grid_remove()
        elif self.cut_mode.get() == "advanced":
            self.grid_frame.grid_remove()
            self.smart_frame.grid_remove()
            self.advanced_frame.grid()
            self.free_frame.grid_remove()
        else:
            self.grid_frame.grid_remove()
            self.smart_frame.grid_remove()
            self.advanced_frame.grid_remove()
            self.free_frame.grid()
    
        self.refresh_preview()
        self.master.update_idletasks()
        # 直接让窗口自动调整，不计算需求尺寸
        self.master.geometry("")

    def on_dir_changed(self):
        self.refresh_preview()

    def on_grid_param_changed(self, event=None):
        if self.cut_mode.get() == "grid":
            self.refresh_preview()

    def on_smart_param_changed(self, event=None):
        if self.cut_mode.get() == "smart":
            self.refresh_preview()

    def on_advanced_param_changed(self, event=None):
        if self.cut_mode.get() == "advanced":
            self.refresh_preview()

    def on_free_param_changed(self, event=None):
        if self.cut_mode.get() == "free":
            self.refresh_preview()

    def update_dir_frame_visibility(self):
        if self.cut_mode.get() in ("grid", "free"):
            self.dir_frame.grid_remove()
        else:
            self.dir_frame.grid()

    def refresh_preview(self):
        if self.preview_window and self.preview_canvas and self.original_img:
            self.update_preview_in_subwindow()

    # ---------- 图片加载相关 ----------
    def load_preview_image(self, file_path):
        if not file_path or not os.path.isfile(file_path):
            return
        try:
            self.original_img = Image.open(file_path)
            if not (self.preview_window and self.preview_window.winfo_exists()):
                self.open_preview_window()
            else:
                self.resize_preview_window_for_image()
                self.refresh_preview()
        except Exception as e:
            print(f"图片加载失败: {e}")

    # ---------- 解析函数 ----------
    def parse_smart_pattern(self):
        text = self.digit_entry.get().strip()
        if not text:
            return None, None
        if ':' in text:
            parts = text.split(':', 1)
            digits_part = parts[0].strip()
            ratio_part = parts[1].strip()
        else:
            digits_part = text
            ratio_part = ""
        blocks = []
        if ',' in digits_part:
            for token in digits_part.split(','):
                token = token.strip()
                if not token.isdigit():
                    return None, None
                blk = int(token)
                if blk <= 0:
                    return None, None
                blocks.append(blk)
        else:
            for ch in digits_part:
                if not ch.isdigit():
                    return None, None
                blk = int(ch)
                if blk <= 0:
                    return None, None
                blocks.append(blk)
        if not blocks:
            return None, None
        n = len(blocks)
        ratios = None
        if ratio_part:
            if ',' in ratio_part:
                parts_ratio = ratio_part.split(',')
                if len(parts_ratio) == n:
                    try:
                        ratios = [float(p.strip()) for p in parts_ratio]
                    except:
                        ratios = None
            else:
                if len(ratio_part) == n:
                    try:
                        ratios = [int(ch) * 10 for ch in ratio_part]
                    except ValueError:
                        ratios = None
                else:
                    ratios = None
        if ratios is not None:
            total = sum(ratios)
            if total > 0:
                ratios = [r / total * 100 for r in ratios]
            else:
                ratios = None
        return blocks, ratios

    def parse_advanced_pattern(self):
        text = self.advanced_text.get("1.0", tk.END).strip()
        if not text:
            self.advanced_parse_error = "输入为空"
            return None, None
    
        # 自动将无引号的 d数字 转换为 "d数字"，方便用户输入
        text = re.sub(r'\bd(\d+(?:\.\d+)?)\b', r'"d\1"', text)
    
        # 分割组比例和嵌套结构（后续代码不变）
        group_ratios = None
        rest = text
        if '|' in text:
            parts = text.split('|', 1)
            ratio_part = parts[0].strip()
            rest = parts[1].strip()
            if not rest:
                self.advanced_parse_error = "竖线右侧不能为空，请输入嵌套结构"
                return None, None
            try:
                ratio_list = [float(x.strip()) for x in ratio_part.split(',') if x.strip()]
                if any(r <= 0 for r in ratio_list):
                    self.advanced_parse_error = "组比例必须为正数"
                    return None, None
                total = sum(ratio_list)
                group_ratios = [r / total * 100 for r in ratio_list]
            except:
                self.advanced_parse_error = "组比例格式错误，应为逗号分隔的正数，如 10,10,80"
                return None, None
    
        # 解析嵌套结构
        try:
            clean_text = re.sub(r'\s+', '', rest)
            data = ast.literal_eval(clean_text)
        except Exception as e:
            self.advanced_parse_error = f"语法错误：{str(e)}"
            return None, None
    
        # 后续处理不变（已经支持带引号的 "d50"）
        if not isinstance(data, list):
            self.advanced_parse_error = "嵌套结构必须是列表"
            return None, None
    
        result = []
        for idx, item in enumerate(data):
            if isinstance(item, int):
                if item <= 0:
                    self.advanced_parse_error = f"第{idx+1}项块数必须>0"
                    return None, None
                result.append((item, None))
            elif isinstance(item, list):
                if len(item) == 1 and isinstance(item[0], int):
                    blk = item[0]
                    if blk <= 0:
                        self.advanced_parse_error = f"第{idx+1}项块数必须>0"
                        return None, None
                    result.append((blk, None))
                elif len(item) == 2 and isinstance(item[0], int) and isinstance(item[1], list):
                    blk = item[0]
                    raw_ratios = item[1]
                    parsed = []
                    for r in raw_ratios:
                        if isinstance(r, (int, float)):
                            parsed.append((float(r), True))
                        elif isinstance(r, str) and r.startswith('d'):
                            try:
                                val = float(r[1:])
                                parsed.append((val, False))
                            except:
                                self.advanced_parse_error = f"无效的d格式比例: {r}"
                                return None, None
                        else:
                            self.advanced_parse_error = f"比例必须为数字或'd数字'，当前为: {r}"
                            return None, None
                    total = sum(v for v, _ in parsed)
                    if total <= 0:
                        self.advanced_parse_error = "比例总和必须大于0"
                        return None, None
                    norm_ratios = [(v / total * 100, flag) for v, flag in parsed]
                    result.append((blk, norm_ratios))
                else:
                    self.advanced_parse_error = f"第{idx+1}项格式错误"
                    return None, None
            else:
                self.advanced_parse_error = f"第{idx+1}项类型错误"
                return None, None
    
        if group_ratios is not None:
            if len(group_ratios) != len(result):
                self.advanced_parse_error = f"组比例数量({len(group_ratios)})与组数({len(result)})不匹配"
                return None, None
    
        self.advanced_parse_error = None
        return group_ratios, result

    def parse_free_pattern(self):
        """解析自由模式矩形定义，返回列表 [(x,y,w,h), ...]"""
        text = self.free_text.get("1.0", tk.END).strip()
        if not text:
            self.free_parse_error = "输入为空"
            return None
        rects = []
        lines = text.replace('\r', '').split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 支持同一行内用分号分隔多个矩形
            line = line.replace(';', ',')
            parts = [p.strip() for p in line.split(',') if p.strip()]
            if len(parts) == 4:
                try:
                    x = int(parts[0])
                    y = int(parts[1])
                    w = int(parts[2])
                    h = int(parts[3])
                    if w <= 0 or h <= 0:
                        raise ValueError
                    rects.append((x, y, w, h))
                except:
                    self.free_parse_error = f"无效矩形: {line}"
                    return None
            else:
                # 可能是多个矩形连写（如 10,10,100,100,200,200,50,50）
                if len(parts) % 4 == 0:
                    for i in range(0, len(parts), 4):
                        try:
                            x = int(parts[i])
                            y = int(parts[i+1])
                            w = int(parts[i+2])
                            h = int(parts[i+3])
                            if w <= 0 or h <= 0:
                                raise ValueError
                            rects.append((x, y, w, h))
                        except:
                            self.free_parse_error = f"无效矩形: {','.join(parts[i:i+4])}"
                            return None
                else:
                    self.free_parse_error = f"每一行需要4个数字，或总数字个数是4的倍数，当前行有{len(parts)}个"
                    return None
        if not rects:
            self.free_parse_error = "未定义任何矩形"
            return None
        self.free_parse_error = None
        return rects

    # ---------- 文件操作 ----------
    def select_file(self):
        path = filedialog.askopenfilename()
        if path:
            self.entry1.delete(0, tk.END)
            self.entry1.insert(0, path)
            self.load_preview_image(path)

    def on_drop_to_entry1(self, event):
        files = self.master.tk.splitlist(event.data)
        if files and os.path.isfile(files[0]):
            self.entry1.delete(0, tk.END)
            self.entry1.insert(0, files[0])
            self.load_preview_image(files[0])

    def select_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.entry2.delete(0, tk.END)
            self.entry2.insert(0, path)

    def on_drop_to_entry2(self, event):
        items = self.master.tk.splitlist(event.data)
        if items:
            p = items[0]
            if os.path.isdir(p):
                self.entry2.delete(0, tk.END)
                self.entry2.insert(0, p)
            elif os.path.isfile(p):
                self.entry2.delete(0, tk.END)
                self.entry2.insert(0, os.path.dirname(p))

    def on_format_change(self, event=None):
        fmt = self.format_var.get()
        if fmt == "JPEG":
            self.quality_var.set("95")
            self.hint_label.config(text="(JPEG质量 1-100)")
        elif fmt == "PNG":
            self.quality_var.set("0")
            self.hint_label.config(text="(PNG压缩级别 0-9)")
        elif fmt == "WEBP":
            self.quality_var.set("80")
            self.hint_label.config(text="(WebP质量 1-100，推荐80)")
        else:
            self.hint_label.config(text="(此格式忽略质量参数)")

    def get_save_params(self, fmt):
        params = {"format": fmt}
        qs = self.quality_var.get().strip()
        if fmt == "JPEG":
            try:
                q = max(1, min(100, int(qs)))
                params["quality"] = q
            except:
                params["quality"] = 95
        elif fmt == "PNG":
            try:
                l = max(0, min(9, int(qs)))
                params["compress_level"] = l
            except:
                params["compress_level"] = 6
        elif fmt == "WEBP":
            try:
                q = max(1, min(100, int(qs)))
                params["quality"] = q
            except:
                params["quality"] = 80
        return params

    def create_progress_dialog(self, total):
        self.progress_win = tk.Toplevel(self.master)
        self.progress_win.title("切割进度")
        self.progress_win.transient(self.master)
        self.progress_win.grab_set()
        self.progress_win.geometry("300x100")
        self.progress_win.update_idletasks()
        w = self.progress_win.winfo_width()
        h = self.progress_win.winfo_height()
        x = (self.progress_win.winfo_screenwidth() - w) // 2
        y = (self.progress_win.winfo_screenheight() - h) // 2
        self.progress_win.geometry(f"+{x}+{y}")
        tk.Label(self.progress_win, text=f"正在切割，共 {total} 张...").pack(pady=5)
        self.progress_var = tk.IntVar(value=0)
        self.progress_bar = ttk.Progressbar(self.progress_win, variable=self.progress_var, maximum=total, length=250)
        self.progress_bar.pack(pady=5)
        self.progress_label = tk.Label(self.progress_win, text="0 / {}".format(total))
        self.progress_label.pack(pady=5)
        def update_progress(current):
            self.progress_var.set(current)
            self.progress_label.config(text=f"{current} / {total}")
            self.progress_win.update_idletasks()
        return update_progress

    def start_cutting(self):
        img_path = self.entry1.get().strip()
        if not img_path or not os.path.isfile(img_path):
            messagebox.showerror("错误", "请先选择一张有效的图片")
            return
        out_dir = self.entry2.get().strip()
        if not out_dir:
            out_dir = os.path.dirname(img_path)
        elif not os.path.isdir(out_dir):
            messagebox.showerror("错误", f"保存目录不存在: {out_dir}")
            return
        try:
            image = Image.open(img_path)
            fmt = self.format_var.get()
            # 修复：JPEG 或 WEBP 且图片有透明通道时转 RGB
            if fmt in ("JPEG", "WEBP") and image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGB")
            save_params = self.get_save_params(fmt)
            ext = fmt.lower()
            mode = self.cut_mode.get()

            total_pieces = 0
            if mode == "grid":
                rows = int(self.rows_entry.get())
                cols = int(self.cols_entry.get())
                total_pieces = rows * cols
            elif mode == "smart":
                blocks, _ = self.parse_smart_pattern()
                if blocks is None:
                    raise ValueError("智能数字模式输入格式错误")
                total_pieces = sum(blocks)
            elif mode == "advanced":
                _, pattern = self.parse_advanced_pattern()
                if pattern is None:
                    raise ValueError("高级嵌套模式输入格式错误")
                total_pieces = 0
                for blk, ratios in pattern:
                    if ratios is None:
                        total_pieces += blk
                    else:
                        total_pieces += sum(1 for _, flag in ratios if flag)
            else:  # free
                rects = self.parse_free_pattern()
                if rects is None:
                    raise ValueError("自由模式矩形定义错误")
                total_pieces = len(rects)

            update_progress = self.create_progress_dialog(total_pieces)
            self.master.update_idletasks()

            if mode == "grid":
                total = self.cut_grid(image, out_dir, ext, save_params, update_progress)
                msg = f"标准网格切割完成！共生成 {total} 张小图"
            elif mode == "smart":
                total = self.cut_smart(image, out_dir, ext, save_params, update_progress)
                msg = f"智能数字模式切割完成！共生成 {total} 张小图"
            elif mode == "advanced":
                total = self.cut_advanced(image, out_dir, ext, save_params, update_progress)
                msg = f"高级嵌套模式切割完成！共生成 {total} 张小图"
            else:
                total = self.cut_free(image, out_dir, ext, save_params, update_progress)
                msg = f"自由模式切割完成！共生成 {total} 张小图"

            if hasattr(self, 'progress_win') and self.progress_win.winfo_exists():
                self.progress_win.destroy()
                self.progress_win = None

            messagebox.showinfo("完成", f"{msg}\n格式：{fmt}\n保存在：{out_dir}")

        except Exception as e:
            if hasattr(self, 'progress_win') and self.progress_win.winfo_exists():
                self.progress_win.destroy()
            messagebox.showerror("错误", f"切割失败: {e}")

    def cut_grid(self, img, out_dir, ext, params, progress_callback=None):
        try:
            rows = int(self.rows_entry.get())
            cols = int(self.cols_entry.get())
            if rows <= 0 or cols <= 0:
                raise ValueError
        except:
            raise ValueError("行数和列数必须为正整数")
        w, h = img.size
        if rows > h:
            raise ValueError(f"行数({rows})超过了图片高度({h})，无法切割")
        if cols > w:
            raise ValueError(f"列数({cols})超过了图片宽度({w})，无法切割")
        cell_w = w // cols
        cell_h = h // rows
        count = 0
        for i in range(rows):
            top = i * cell_h
            bottom = top + cell_h if i < rows-1 else h
            for j in range(cols):
                left = j * cell_w
                right = left + cell_w if j < cols-1 else w
                cropped = img.crop((left, top, right, bottom))
                cropped.save(os.path.join(out_dir, f"{i}_{j}.{ext}"), **params)
                count += 1
                if progress_callback:
                    progress_callback(count)
        return count

    def cut_smart(self, img, out_dir, ext, params, progress_callback=None):
        blocks, ratios = self.parse_smart_pattern()
        if blocks is None:
            raise ValueError("智能数字模式输入格式错误")
        direction = self.direction.get()
        w, h = img.size
        if direction == "horizontal":
            for idx, blk in enumerate(blocks):
                if blk > h:
                    raise ValueError(f"第{idx+1}列的块数({blk})超过了图片高度({h})，无法切割")
        else:
            for idx, blk in enumerate(blocks):
                if blk > w:
                    raise ValueError(f"第{idx+1}行的块数({blk})超过了图片宽度({w})，无法切割")
        count = 0
        if direction == "horizontal":
            n_cols = len(blocks)
            if ratios is None:
                col_widths = [w // n_cols] * n_cols
                remainder = w - sum(col_widths)
                if remainder > 0:
                    col_widths[-1] += remainder
            else:
                col_widths = [int(w * r / 100.0) for r in ratios]
                diff = w - sum(col_widths)
                col_widths[-1] += diff
            left = 0
            for col_idx, blk in enumerate(blocks):
                col_w = col_widths[col_idx]
                right = left + col_w
                block_h = h // blk
                remaining_h = h
                heights = []
                for i in range(blk):
                    if i == blk - 1:
                        seg_h = remaining_h
                    else:
                        seg_h = block_h
                        remaining_h -= seg_h
                    heights.append(seg_h)
                top = 0
                for blk_idx, seg_h in enumerate(heights):
                    bottom = top + seg_h
                    cropped = img.crop((left, top, right, bottom))
                    cropped.save(os.path.join(out_dir, f"c{col_idx+1}_r{blk_idx+1}.{ext}"), **params)
                    count += 1
                    if progress_callback:
                        progress_callback(count)
                    top = bottom
                left = right
        else:
            n_rows = len(blocks)
            if ratios is None:
                row_heights = [h // n_rows] * n_rows
                remainder = h - sum(row_heights)
                if remainder > 0:
                    row_heights[-1] += remainder
            else:
                row_heights = [int(h * r / 100.0) for r in ratios]
                diff = h - sum(row_heights)
                row_heights[-1] += diff
            top = 0
            for row_idx, blk in enumerate(blocks):
                row_h = row_heights[row_idx]
                bottom = top + row_h
                block_w = w // blk
                remaining_w = w
                widths = []
                for i in range(blk):
                    if i == blk - 1:
                        seg_w = remaining_w
                    else:
                        seg_w = block_w
                        remaining_w -= seg_w
                    widths.append(seg_w)
                left = 0
                for blk_idx, seg_w in enumerate(widths):
                    right = left + seg_w
                    cropped = img.crop((left, top, right, bottom))
                    cropped.save(os.path.join(out_dir, f"r{row_idx+1}_c{blk_idx+1}.{ext}"), **params)
                    count += 1
                    if progress_callback:
                        progress_callback(count)
                    left = right
                top = bottom
        return count

    def cut_advanced(self, img, out_dir, ext, params, progress_callback=None):
        group_ratios, pattern = self.parse_advanced_pattern()
        if pattern is None:
            raise ValueError("高级嵌套模式输入格式错误")
        direction = self.direction.get()
        w, h = img.size
    
        # 校验块数是否超过图片尺寸
        if direction == "horizontal":
            for idx, (blk, _) in enumerate(pattern):
                if blk > h:
                    raise ValueError(f"第{idx+1}列的块数({blk})超过了图片高度({h})，无法切割")
        else:
            for idx, (blk, _) in enumerate(pattern):
                if blk > w:
                    raise ValueError(f"第{idx+1}行的块数({blk})超过了图片宽度({w})，无法切割")
    
        count = 0
    
        if direction == "horizontal":
            n = len(pattern)
            # 计算每列的实际宽度（整数像素）
            if group_ratios is None:
                col_widths = [w // n] * n
                diff = w - sum(col_widths)
                if diff > 0:
                    col_widths[-1] += diff
            else:
                col_widths = [int(w * r / 100.0) for r in group_ratios]
                diff = w - sum(col_widths)
                col_widths[-1] += diff
    
            left = 0
            for col_idx, (blk, ratios) in enumerate(pattern):
                col_w = col_widths[col_idx]
                right = left + col_w
    
                if ratios is None:
                    # 均分内部块高度（整数），全部输出
                    block_h = h // blk
                    remaining = h
                    heights = []
                    for i in range(blk):
                        if i == blk - 1:
                            seg_h = remaining
                        else:
                            seg_h = block_h
                            remaining -= seg_h
                        heights.append(seg_h)
    
                    top = 0
                    for blk_idx, seg_h in enumerate(heights):
                        bottom = top + seg_h
                        cropped = img.crop((left, top, right, bottom))
                        cropped.save(os.path.join(out_dir, f"c{col_idx+1}_r{blk_idx+1}.{ext}"), **params)
                        count += 1
                        if progress_callback:
                            progress_callback(count)
                        top = bottom
                else:
                    # 按比例分割内部块高度（整数），支持不输出
                    remaining = h
                    heights = []
                    for i, (r, _) in enumerate(ratios):
                        if i == len(ratios) - 1:
                            seg_h = remaining
                        else:
                            seg_h = int(h * r / 100.0)
                            remaining -= seg_h
                        heights.append(seg_h)
    
                    top = 0
                    for blk_idx, seg_h in enumerate(heights):
                        bottom = top + seg_h
                        if ratios[blk_idx][1]:  # 需要输出
                            cropped = img.crop((left, top, right, bottom))
                            cropped.save(os.path.join(out_dir, f"c{col_idx+1}_r{blk_idx+1}.{ext}"), **params)
                            count += 1
                            if progress_callback:
                                progress_callback(count)
                        # 无论是否输出，都更新 top 累积坐标
                        top = bottom
    
                left = right
    
        else:  # vertical
            n = len(pattern)
            # 计算每行的实际高度（整数像素）
            if group_ratios is None:
                row_heights = [h // n] * n
                diff = h - sum(row_heights)
                if diff > 0:
                    row_heights[-1] += diff
            else:
                row_heights = [int(h * r / 100.0) for r in group_ratios]
                diff = h - sum(row_heights)
                row_heights[-1] += diff
    
            top = 0
            for row_idx, (blk, ratios) in enumerate(pattern):
                row_h = row_heights[row_idx]
                bottom = top + row_h
    
                if ratios is None:
                    # 均分内部块宽度（整数），全部输出
                    block_w = w // blk
                    remaining = w
                    widths = []
                    for i in range(blk):
                        if i == blk - 1:
                            seg_w = remaining
                        else:
                            seg_w = block_w
                            remaining -= seg_w
                        widths.append(seg_w)
    
                    left = 0
                    for blk_idx, seg_w in enumerate(widths):
                        right = left + seg_w
                        cropped = img.crop((left, top, right, bottom))
                        cropped.save(os.path.join(out_dir, f"r{row_idx+1}_c{blk_idx+1}.{ext}"), **params)
                        count += 1
                        if progress_callback:
                            progress_callback(count)
                        left = right
                else:
                    # 按比例分割内部块宽度（整数），支持不输出
                    remaining = w
                    widths = []
                    for i, (r, _) in enumerate(ratios):
                        if i == len(ratios) - 1:
                            seg_w = remaining
                        else:
                            seg_w = int(w * r / 100.0)
                            remaining -= seg_w
                        widths.append(seg_w)
    
                    left = 0
                    for blk_idx, seg_w in enumerate(widths):
                        right = left + seg_w
                        if ratios[blk_idx][1]:  # 需要输出
                            cropped = img.crop((left, top, right, bottom))
                            cropped.save(os.path.join(out_dir, f"r{row_idx+1}_c{blk_idx+1}.{ext}"), **params)
                            count += 1
                            if progress_callback:
                                progress_callback(count)
                        left = right
    
                top = bottom
    
        return count

    def cut_free(self, img, out_dir, ext, params, progress_callback=None):
        """自由模式切割：按定义的矩形区域裁剪并保存"""
        rects = self.parse_free_pattern()
        if rects is None:
            raise ValueError("自由模式矩形定义错误")
        img_w, img_h = img.size
        count = 0
        for idx, (x, y, w, h) in enumerate(rects):
            # 边界校验
            if x < 0 or y < 0 or x + w > img_w or y + h > img_h:
                raise ValueError(f"矩形 {idx+1} 超出图片边界: x={x}, y={y}, w={w}, h={h}")
            if w <= 0 or h <= 0:
                raise ValueError(f"矩形 {idx+1} 宽度或高度为0")
            cropped = img.crop((x, y, x + w, y + h))
            cropped.save(os.path.join(out_dir, f"free_{idx+1}.{ext}"), **params)
            count += 1
            if progress_callback:
                progress_callback(count)
        return count

    def quit_app(self):
        if self.preview_window:
            self.preview_window.destroy()
        self.master.destroy()

def center_window(win):
    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    x = (win.winfo_screenwidth() - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")

if __name__ == "__main__":
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = App(root)
    center_window(root)
    root.mainloop()