import os
import sys
import json
import copy
import subprocess
import platform
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, Toplevel, simpledialog
from PIL import Image, ImageTk, ImageEnhance, ImageDraw, ImageFont
#删除到回收站需要的线程并发
from concurrent.futures import ThreadPoolExecutor

import ctypes
from ctypes import wintypes
import time

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    class TkinterDnD:
        class Tk(tk.Tk):
            pass
    DND_FILES = None


def get_supported_extensions():
    """返回Pillow支持的所有可读取图片扩展名（小写，包含点号）"""
    exts = set()
    # 从Pillow注册的扩展名中提取
    for ext, format in Image.registered_extensions().items():
        if format:  # 确保格式可读
            exts.add(ext.lower())
    # 补充一些常见但可能未注册的扩展名（Pillow通常支持但可能未全部列出）
    additional = {
        '.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif',
        '.gif', '.ico', '.ppm', '.pgm', '.pbm', '.xbm', '.pcx', '.tga',
        '.jp2', '.j2k', '.jpx', '.jpf'  # JPEG2000
    }
    exts.update(additional)
    return exts

SUPPORTED_IMG_EXTS = get_supported_extensions()

# 格式配置字典
FORMAT_CONFIG = {
    'JPEG': {
        'extension': '.jpg',
        'save_params': {'quality': 'quality', 'optimize': True},
        'quality_range': (1, 100),
        'default_quality': 85,
        'mode': 'RGB',
        'supports_exif': True,          # 新增
    },
    'PNG': {
        'extension': '.png',
        'save_params': {'compress_level': 'compress_level'},
        'quality_range': (0, 9),
        'default_quality': 6,
        'mode': None,
        'supports_exif': False,         # 新增
    },
    'WEBP': {
        'extension': '.webp',
        'save_params': {'quality': 'quality', 'lossless': False},
        'quality_range': (1, 100),
        'default_quality': 80,
        'mode': 'RGB',
        'supports_exif': True,          # 新增
    },
    'BMP': {
        'extension': '.bmp',
        'save_params': {},
        'quality_range': None,
        'default_quality': None,
        'mode': 'RGB',
        'supports_exif': False,         # 新增
    }
}


def send_to_trash(path):
    """跨平台地将文件或文件夹移动到回收站/废纸篓。"""
    if platform.system() == 'Windows':
        # Windows: 调用 Shell API
        try:
            import ctypes
            from ctypes import wintypes
            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", ctypes.c_void_p),
                    ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR),
                    ("fFlags", wintypes.UINT),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR),
                ]
            # 定义常量
            FO_DELETE = 0x0003
            FOF_ALLOWUNDO = 0x0040   # 允许撤销 -> 放入回收站
            FOF_NOCONFIRMATION = 0x0010
            FOF_SILENT = 0x0004
            # 构建操作结构体
            file_op = SHFILEOPSTRUCTW()
            file_op.wFunc = FO_DELETE
            # 路径必须以双null结尾
            file_op.pFrom = path + '\0\0'
            file_op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
            file_op.hwnd = 0
            # 调用 Shell API
            result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(file_op))
            if result != 0:
                raise OSError(f"SHFileOperationW failed with error code: {result}")
        except Exception as e:
            raise OSError(f"Failed to move '{path}' to Recycle Bin: {e}")
    elif platform.system() == 'Darwin':
        # macOS: 使用 osascript 调用 AppleScript
        try:
            script = f'''
            tell application "Finder"
                delete POSIX file "{path}"
            end tell
            '''
            subprocess.run(['osascript', '-e', script], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise OSError(f"Failed to move '{path}' to Trash: {e.stderr.strip()}")
        except Exception as e:
            raise OSError(f"Failed to move '{path}' to Trash: {e}")
    else:
        # Linux: 检查可用的 CLI 工具
        # 优先使用 gio (GNOME) 或 kioclient5 (KDE)，最后尝试 trash-cli
        try:
            # 尝试使用 gio
            subprocess.run(['gio', 'trash', path], check=True, capture_output=True, text=True)
        except FileNotFoundError:
            try:
                # 尝试使用 kioclient5
                subprocess.run(['kioclient5', 'move', path, 'trash:/'], check=True, capture_output=True, text=True)
            except FileNotFoundError:
                try:
                    # 尝试使用 trash-cli
                    subprocess.run(['trash-put', path], check=True, capture_output=True, text=True)
                except FileNotFoundError:
                    raise OSError("No supported trash CLI tool found (gio, kioclient5, or trash-put). Please install one.")
        except subprocess.CalledProcessError as e:
            raise OSError(f"Failed to move '{path}' to Trash: {e.stderr.strip()}")
        except Exception as e:
            raise OSError(f"Failed to move '{path}' to Trash: {e}")

def get_preset_file_path():
    if getattr(sys, 'frozen', False):
        # 打包后的 exe：使用 exe 所在目录
        base_dir = os.path.dirname(sys.executable)
    else:
        # 开发环境：使用脚本所在目录
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "picpresets.json")

class TemplateEditor(ttk.Frame):
    """可复用的参数编辑组件（不含名称模板、重名处理等界面级选项）"""
    def __init__(self, parent, include_exif_date_delete=True, default_expanded=False, **kwargs):
        super().__init__(parent, **kwargs)
        self.include_exif_date_delete = include_exif_date_delete
        self.default_expanded = default_expanded
        self.preview_callback = None
        self._create_widgets()
        self._setup_traces()
        self._init_enhance_state()
        if self.default_expanded:
            self._toggle_enhance()

    def _create_widgets(self):
        # 第一行：格式、质量、旋转、翻转
        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="格式:").pack(side=tk.LEFT, padx=2)
        self.format_var = tk.StringVar(value="JPEG")
        format_combo = ttk.Combobox(row1, textvariable=self.format_var,
                                    values=["保持原格式", "JPEG", "PNG", "WEBP", "BMP"],
                                    state="readonly", width=10)
        format_combo.pack(side=tk.LEFT, padx=2)   # 添加这一行

        ttk.Label(row1, text="质量:").pack(side=tk.LEFT, padx=(10,2))
        self.quality_var = tk.IntVar(value=85)
        quality_scale = ttk.Scale(row1, from_=1, to=100, variable=self.quality_var,
                                  orient=tk.HORIZONTAL, length=80)
        quality_scale.pack(side=tk.LEFT, padx=2)
        self.quality_spin = ttk.Spinbox(row1, from_=1, to=100, textvariable=self.quality_var,
                                        width=5, state='normal')
        self.quality_spin.pack(side=tk.LEFT, padx=2)

        ttk.Label(row1, text="旋转:").pack(side=tk.LEFT, padx=(10,2))
        self.rotation_var = tk.StringVar(value="0°")
        rot_frame = ttk.Frame(row1)
        rot_frame.pack(side=tk.LEFT, padx=2)
        for text, val in [("无", "0°"), ("左90", "90°"), ("右90", "-90°"), ("180", "180°")]:
            ttk.Radiobutton(rot_frame, text=text, variable=self.rotation_var, value=val).pack(side=tk.LEFT, padx=2)

        self.h_flip_var = tk.BooleanVar(value=False)
        self.v_flip_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="水平翻转", variable=self.h_flip_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(row1, text="垂直翻转", variable=self.v_flip_var).pack(side=tk.LEFT, padx=5)

        # 第二行：尺寸调整 + 三个复选框（保留EXIF、维持日期、删除原文件）
        row2 = ttk.Frame(self)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="尺寸调整:").pack(side=tk.LEFT, padx=2)
        self.resize_mode_var = tk.StringVar(value="无调整")
        mode_combo = ttk.Combobox(row2, textvariable=self.resize_mode_var,
                                  values=["无调整", "精确 (WxH)", "限制长边", "限制短边"],
                                  state="readonly", width=12)
        mode_combo.pack(side=tk.LEFT, padx=2)
        self.width_label = ttk.Label(row2, text="宽:")
        self.width_label.pack(side=tk.LEFT, padx=(10,2))
        self.resize_width_var = tk.IntVar(value=800)
        self.resize_width_spin = ttk.Spinbox(row2, from_=1, to=9999, textvariable=self.resize_width_var, width=6)
        self.resize_width_spin.pack(side=tk.LEFT, padx=2)
        ttk.Label(row2, text="高:").pack(side=tk.LEFT, padx=(5,2))
        self.resize_height_var = tk.IntVar(value=600)
        self.resize_height_spin = ttk.Spinbox(row2, from_=1, to=9999, textvariable=self.resize_height_var, width=6)
        self.resize_height_spin.pack(side=tk.LEFT, padx=2)

        if self.include_exif_date_delete:
            self.keep_exif_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(row2, text="保留EXIF", variable=self.keep_exif_var).pack(side=tk.LEFT, padx=(20, 5))
            self.preserve_date_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(row2, text="维持原始日期", variable=self.preserve_date_var).pack(side=tk.LEFT, padx=5)
            self.delete_original_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(row2, text="删除原文件", variable=self.delete_original_var).pack(side=tk.LEFT, padx=5)

        # 第三行：裁剪
        row3 = ttk.Frame(self)
        row3.pack(fill=tk.X, pady=2)
        self.crop_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row3, text="启用裁剪", variable=self.crop_enabled_var).pack(side=tk.LEFT, padx=2)
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

        # 预览尺寸控制
        ttk.Label(row3, text="预览尺寸:").pack(side=tk.LEFT, padx=(10,2))
        self.preview_size_var = tk.IntVar(value=500)
        self.preview_size_spin = ttk.Spinbox(row3, from_=100, to=2000, textvariable=self.preview_size_var, width=6)
        self.preview_size_spin.pack(side=tk.LEFT, padx=2)

        self.toggle_btn = ttk.Button(row3, text="▶ 更多调整", width=12, command=self._toggle_enhance)
        self.toggle_btn.pack(side=tk.RIGHT, padx=(0,15))

        # 增强面板（初始隐藏）
        self.enhance_expanded = False
        self.enhance_frame = ttk.Frame(self)

        # 亮度/对比/饱和/锐化
        bc_frame = ttk.LabelFrame(self.enhance_frame, text="亮度/对比/饱和/锐化")
        bc_frame.pack(fill=tk.X, pady=2, padx=5)
        bc_row = ttk.Frame(bc_frame)
        bc_row.pack(fill=tk.X, pady=2, padx=5)

        self.brightness_enable = tk.BooleanVar(value=False)
        ttk.Checkbutton(bc_row, text="亮度", variable=self.brightness_enable).pack(side=tk.LEFT)
        self.brightness_var = tk.IntVar(value=0)
        self.brightness_scale = ttk.Scale(bc_row, from_=-100, to=100, variable=self.brightness_var,
                                          orient=tk.HORIZONTAL, length=90, state=tk.DISABLED)  # 长度改为80
        self.brightness_scale.pack(side=tk.LEFT, padx=5)
        self.brightness_label = ttk.Label(bc_row, text="0", width=4)
        self.brightness_label.pack(side=tk.LEFT)

        ttk.Label(bc_row, text="  ").pack(side=tk.LEFT)  # 间距缩小
        self.contrast_enable = tk.BooleanVar(value=False)
        ttk.Checkbutton(bc_row, text="对比度", variable=self.contrast_enable).pack(side=tk.LEFT)
        self.contrast_var = tk.IntVar(value=0)
        self.contrast_scale = ttk.Scale(bc_row, from_=-100, to=100, variable=self.contrast_var,
                                        orient=tk.HORIZONTAL, length=90, state=tk.DISABLED)
        self.contrast_scale.pack(side=tk.LEFT, padx=5)
        self.contrast_label = ttk.Label(bc_row, text="0", width=4)
        self.contrast_label.pack(side=tk.LEFT)

        ttk.Label(bc_row, text="  ").pack(side=tk.LEFT)
        self.saturation_enable = tk.BooleanVar(value=False)
        ttk.Checkbutton(bc_row, text="饱和度", variable=self.saturation_enable).pack(side=tk.LEFT)
        self.saturation_var = tk.IntVar(value=0)
        self.saturation_scale = ttk.Scale(bc_row, from_=-100, to=100, variable=self.saturation_var,
                                          orient=tk.HORIZONTAL, length=90, state=tk.DISABLED)
        self.saturation_scale.pack(side=tk.LEFT, padx=5)
        self.saturation_label = ttk.Label(bc_row, text="0", width=4)
        self.saturation_label.pack(side=tk.LEFT)

        ttk.Label(bc_row, text="  ").pack(side=tk.LEFT)
        self.sharpen_enable = tk.BooleanVar(value=False)
        ttk.Checkbutton(bc_row, text="锐化", variable=self.sharpen_enable).pack(side=tk.LEFT)
        self.sharpen_var = tk.IntVar(value=0)
        self.sharpen_scale = ttk.Scale(bc_row, from_=-100, to=100, variable=self.sharpen_var,
                                       orient=tk.HORIZONTAL, length=90, state=tk.DISABLED)
        self.sharpen_scale.pack(side=tk.LEFT, padx=5)
        self.sharpen_label = ttk.Label(bc_row, text="0", width=4)
        self.sharpen_label.pack(side=tk.LEFT)

        # 色彩平衡
        color_frame = ttk.LabelFrame(self.enhance_frame, text="色彩平衡")
        color_frame.pack(fill=tk.X, pady=2, padx=5)
        color_header = ttk.Frame(color_frame)
        color_header.pack(fill=tk.X, pady=2, padx=5)
        self.color_enable = tk.BooleanVar(value=False)
        ttk.Checkbutton(color_header, text="启用RGB调整", variable=self.color_enable).pack(side=tk.LEFT)

        # 三个滑块放在一行
        row = ttk.Frame(color_frame)
        row.pack(fill=tk.X, pady=2, padx=5)

        # 第一组：青 ↔ 红
        self.r_var = tk.IntVar(value=0)
        group1 = ttk.Frame(row)
        group1.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Label(group1, text="青", width=4).pack(side=tk.LEFT)
        self.r_scale = ttk.Scale(group1, from_=-100, to=100, variable=self.r_var,
                                 orient=tk.HORIZONTAL, length=100, state=tk.DISABLED)
        self.r_scale.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Label(group1, text="红", width=4).pack(side=tk.LEFT)
        self.r_label = ttk.Label(group1, text="0", width=4)
        self.r_label.pack(side=tk.LEFT)

        # 第二组：洋红 ↔ 绿
        self.g_var = tk.IntVar(value=0)
        group2 = ttk.Frame(row)
        group2.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Label(group2, text="洋红", width=4).pack(side=tk.LEFT)
        self.g_scale = ttk.Scale(group2, from_=-100, to=100, variable=self.g_var,
                                 orient=tk.HORIZONTAL, length=100, state=tk.DISABLED)
        self.g_scale.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Label(group2, text="绿", width=4).pack(side=tk.LEFT)
        self.g_label = ttk.Label(group2, text="0", width=4)
        self.g_label.pack(side=tk.LEFT)

        # 第三组：黄 ↔ 蓝
        self.b_var = tk.IntVar(value=0)
        group3 = ttk.Frame(row)
        group3.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Label(group3, text="黄", width=4).pack(side=tk.LEFT)
        self.b_scale = ttk.Scale(group3, from_=-100, to=100, variable=self.b_var,
                                 orient=tk.HORIZONTAL, length=100, state=tk.DISABLED)
        self.b_scale.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Label(group3, text="蓝", width=4).pack(side=tk.LEFT)
        self.b_label = ttk.Label(group3, text="0", width=4)
        self.b_label.pack(side=tk.LEFT)

        # ========== 文字水印 ==========
        self.watermark_frame = ttk.LabelFrame(self.enhance_frame, text="文字水印 - 简易")
        self.watermark_frame.pack(fill=tk.X, pady=2, padx=5)

        # 第一行：启用 + 文本 + 字体 + 字号 + 透明度 + 颜色
        wm_row1 = ttk.Frame(self.watermark_frame)
        wm_row1.pack(fill=tk.X, pady=2, padx=5)

        self.watermark_enable = tk.BooleanVar(value=False)
        ttk.Checkbutton(wm_row1, text="启用", variable=self.watermark_enable).pack(side=tk.LEFT, padx=2)

        ttk.Label(wm_row1, text="文本:").pack(side=tk.LEFT, padx=5)
        self.watermark_text_var = tk.StringVar(value="Watermark")
        wm_entry = ttk.Entry(wm_row1, textvariable=self.watermark_text_var, width=15)
        wm_entry.pack(side=tk.LEFT, padx=2)

        ttk.Label(wm_row1, text="字体:").pack(side=tk.LEFT, padx=5)
        import tkinter.font as tkfont
        font_list = sorted(tkfont.families())
        self.watermark_font_var = tk.StringVar(value="Arial" if "Arial" in font_list else (font_list[0] if font_list else "TkDefaultFont"))
        self.font_combo = ttk.Combobox(wm_row1, textvariable=self.watermark_font_var, values=font_list, width=10, state="readonly")
        self.font_combo.pack(side=tk.LEFT, padx=2)

        ttk.Label(wm_row1, text="大小:").pack(side=tk.LEFT, padx=5)
        self.watermark_size_var = tk.IntVar(value=36)
        self.font_size_spin = ttk.Spinbox(wm_row1, from_=6, to=200, textvariable=self.watermark_size_var, width=5)
        self.font_size_spin.pack(side=tk.LEFT, padx=2)

        ttk.Label(wm_row1, text="透明度:").pack(side=tk.LEFT, padx=5)
        self.watermark_opacity_var = tk.IntVar(value=80)
        opacity_scale = ttk.Scale(wm_row1, from_=0, to=100, variable=self.watermark_opacity_var, orient=tk.HORIZONTAL, length=80)
        opacity_scale.pack(side=tk.LEFT, padx=2)
        self.watermark_opacity_label = ttk.Label(wm_row1, text="80%", width=4)
        self.watermark_opacity_label.pack(side=tk.LEFT, padx=2)

        # 第二行：位置按钮（平铺）
        wm_row2 = ttk.Frame(self.watermark_frame)
        wm_row2.pack(fill=tk.X, pady=2, padx=5)

        self.watermark_pos_var = tk.StringVar(value="右下")
        positions = ["左上", "上", "右上", "左中", "中", "右中", "左下", "下", "右下"]

        for pos in positions:
            btn = ttk.Button(wm_row2, text=pos, width=4,
                             command=lambda p=pos: self.watermark_pos_var.set(p))
            btn.pack(side=tk.LEFT, padx=2)
        
        # 颜色选择：按钮 + 预览色块
        ttk.Label(wm_row2, text="颜色:").pack(side=tk.LEFT, padx=(15,2))
        self.watermark_color_var = tk.StringVar(value="#FFFFFF")
        self.choose_color_btn = ttk.Button(wm_row2, text="选择颜色", command=self.choose_color, width=8)
        self.choose_color_btn.pack(side=tk.LEFT, padx=2)
        self.color_preview = tk.Canvas(wm_row2, width=20, height=20, bg="#FFFFFF", bd=1, relief=tk.SUNKEN)
        self.color_preview.pack(side=tk.LEFT, padx=2)

    def choose_color(self):
        from tkinter import colorchooser
        initial = self.watermark_color_var.get()
        if not initial or initial == '':
            initial = "#FFFFFF"
        color = colorchooser.askcolor(title="选择水印颜色", initialcolor=initial)
        if color:
            hex_color = color[1]
            self.watermark_color_var.set(hex_color)
            self.color_preview.config(bg=hex_color)


    def _setup_traces(self):
        vars_list = [
            self.format_var, self.quality_var, self.rotation_var,
            self.h_flip_var, self.v_flip_var, self.resize_mode_var,
            self.resize_width_var, self.resize_height_var, self.crop_enabled_var,
            self.crop_x_var, self.crop_y_var, self.crop_w_var, self.crop_h_var,
            self.brightness_enable, self.brightness_var, self.contrast_enable,
            self.contrast_var, self.color_enable, self.r_var, self.g_var, self.b_var,
            self.saturation_enable, self.saturation_var,
            self.sharpen_enable, self.sharpen_var,  # 添加锐化变量跟踪
            self.preview_size_var,
        ]
        if self.include_exif_date_delete:
            vars_list.extend([self.keep_exif_var, self.preserve_date_var, self.delete_original_var])

        # 添加水印变量（如果这些属性已经存在）
        watermark_vars = [
            self.watermark_enable,
            self.watermark_text_var,
            self.watermark_font_var,
            self.watermark_size_var,
            self.watermark_pos_var,
            self.watermark_opacity_var,
            self.watermark_color_var,
        ]
        vars_list.extend(watermark_vars)


        for var in vars_list:
            var.trace_add('write', lambda *a: self._on_settings_changed())


        self.brightness_var.trace_add('write', lambda *a: self.brightness_label.config(text=str(self.brightness_var.get())))
        self.contrast_var.trace_add('write', lambda *a: self.contrast_label.config(text=str(self.contrast_var.get())))
        self.saturation_var.trace_add('write', lambda *a: self.saturation_label.config(text=str(self.saturation_var.get())))
        self.sharpen_var.trace_add('write', lambda *a: self.sharpen_label.config(text=str(self.sharpen_var.get())))
        self.r_var.trace_add('write', lambda *a: self.r_label.config(text=str(self.r_var.get())))
        self.g_var.trace_add('write', lambda *a: self.g_label.config(text=str(self.g_var.get())))
        self.b_var.trace_add('write', lambda *a: self.b_label.config(text=str(self.b_var.get())))
        # 水印透明度标签更新
        self.watermark_opacity_var.trace_add('write', lambda *a: self.watermark_opacity_label.config(text=f"{self.watermark_opacity_var.get()}%"))
        self.resize_mode_var.trace_add('write', lambda *a: self._on_resize_mode_changed())
        self._on_resize_mode_changed()
        self.watermark_color_var.trace_add('write', lambda *a: self.color_preview.config(bg=self.watermark_color_var.get()))

        self.brightness_enable.trace_add('write', lambda *a: self._update_enhance_enable())
        self.contrast_enable.trace_add('write', lambda *a: self._update_enhance_enable())
        self.color_enable.trace_add('write', lambda *a: self._update_enhance_enable())
        self.saturation_enable.trace_add('write', lambda *a: self._update_enhance_enable())
        self.sharpen_enable.trace_add('write', lambda *a: self._update_enhance_enable())

    def _init_enhance_state(self):
        self._update_enhance_enable()

    def _update_enhance_enable(self):
        self.brightness_scale.config(state=tk.NORMAL if self.brightness_enable.get() else tk.DISABLED)
        self.contrast_scale.config(state=tk.NORMAL if self.contrast_enable.get() else tk.DISABLED)
        self.saturation_scale.config(state=tk.NORMAL if self.saturation_enable.get() else tk.DISABLED)
        self.sharpen_scale.config(state=tk.NORMAL if self.sharpen_enable.get() else tk.DISABLED)
        state = tk.NORMAL if self.color_enable.get() else tk.DISABLED
        self.r_scale.config(state=state)
        self.g_scale.config(state=state)
        self.b_scale.config(state=state)

    def _on_resize_mode_changed(self):
        mode = self.resize_mode_var.get()
        if mode == "限制长边":
            self.width_label.config(text="长边:")
            self.resize_height_spin.config(state=tk.DISABLED)
        elif mode == "限制短边":
            self.width_label.config(text="短边:")
            self.resize_height_spin.config(state=tk.DISABLED)
        else:
            self.width_label.config(text="宽:")
            self.resize_height_spin.config(state=tk.NORMAL)
        self._on_settings_changed()

    def _toggle_enhance(self):
        if self.enhance_expanded:
            self.enhance_frame.pack_forget()
            self.toggle_btn.config(text="▶ 更多调整")
            self.enhance_expanded = False
        else:
            self.enhance_frame.pack(fill=tk.X, pady=2)
            self.toggle_btn.config(text="▼ 更多调整")
            self.enhance_expanded = True

    def _on_settings_changed(self):
        if self.preview_callback:
            self.preview_callback(self.get_settings())

    def bind_preview_callback(self, callback):
        self.preview_callback = callback

    def get_settings(self):
        settings = {
            'format': self.format_var.get(),
            'quality': self.quality_var.get(),
            'rotation': self.rotation_var.get(),
            'h_flip': self.h_flip_var.get(),
            'v_flip': self.v_flip_var.get(),
            'resize_mode': self.resize_mode_var.get(),
            'resize_w': self.resize_width_var.get(),
            'resize_h': self.resize_height_var.get(),
            'crop_enabled': self.crop_enabled_var.get(),
            'crop_x': self.crop_x_var.get(),
            'crop_y': self.crop_y_var.get(),
            'crop_w': self.crop_w_var.get(),
            'crop_h': self.crop_h_var.get(),
            'brightness_enable': self.brightness_enable.get(),
            'brightness_val': self.brightness_var.get(),
            'contrast_enable': self.contrast_enable.get(),
            'contrast_val': self.contrast_var.get(),
            'color_enable': self.color_enable.get(),
            'r_gain': self.r_var.get(),
            'g_gain': self.g_var.get(),
            'b_gain': self.b_var.get(),
            'saturation_enable': self.saturation_enable.get(),
            'saturation_val': self.saturation_var.get(),
            'sharpen_enable': self.sharpen_enable.get(),
            'sharpen_val': self.sharpen_var.get(),
            # 文字水印参数
            'watermark_enable': self.watermark_enable.get(),
            'watermark_text': self.watermark_text_var.get(),
            'watermark_font': self.watermark_font_var.get(),
            'watermark_size': self.watermark_size_var.get(),
            'watermark_position': self.watermark_pos_var.get(),
            'watermark_opacity': self.watermark_opacity_var.get(),
            'preview_size': self.preview_size_var.get(),
        }
        # 保存颜色：将颜色名称转换为十六进制存储
        settings['watermark_color'] = self.watermark_color_var.get()
    
        if self.include_exif_date_delete:
            settings.update({
                'keep_exif': self.keep_exif_var.get(),
                'preserve_original_date': self.preserve_date_var.get(),
                'delete_original': self.delete_original_var.get(),
            })
        return settings
    
    def set_settings(self, settings):
        self.format_var.set(settings.get('format', 'JPEG'))
        self.quality_var.set(settings.get('quality', 85))
        self.rotation_var.set(settings.get('rotation', '0°'))
        self.h_flip_var.set(settings.get('h_flip', False))
        self.v_flip_var.set(settings.get('v_flip', False))
        self.resize_mode_var.set(settings.get('resize_mode', '无调整'))
        self.resize_width_var.set(settings.get('resize_w', 800))
        self.resize_height_var.set(settings.get('resize_h', 600))
        self.crop_enabled_var.set(settings.get('crop_enabled', False))
        self.crop_x_var.set(settings.get('crop_x', '0'))
        self.crop_y_var.set(settings.get('crop_y', '0'))
        self.crop_w_var.set(settings.get('crop_w', 'iw'))
        self.crop_h_var.set(settings.get('crop_h', 'ih'))
        self.brightness_enable.set(settings.get('brightness_enable', False))
        self.brightness_var.set(settings.get('brightness_val', 0))
        self.contrast_enable.set(settings.get('contrast_enable', False))
        self.contrast_var.set(settings.get('contrast_val', 0))
        self.color_enable.set(settings.get('color_enable', False))
        self.r_var.set(settings.get('r_gain', 0))
        self.g_var.set(settings.get('g_gain', 0))
        self.b_var.set(settings.get('b_gain', 0))
        self.saturation_enable.set(settings.get('saturation_enable', False))
        self.saturation_var.set(settings.get('saturation_val', 0))
        self.sharpen_enable.set(settings.get('sharpen_enable', False))
        self.sharpen_var.set(settings.get('sharpen_val', 0))
        
        # 文字水印参数
        self.watermark_enable.set(settings.get('watermark_enable', False))
        self.watermark_text_var.set(settings.get('watermark_text', 'Watermark'))
        self.watermark_font_var.set(settings.get('watermark_font', 'Arial'))
        self.watermark_size_var.set(settings.get('watermark_size', 36))
        self.watermark_pos_var.set(settings.get('watermark_position', '右下'))
        self.watermark_opacity_var.set(settings.get('watermark_opacity', 80))
        
        self.preview_size_var.set(settings.get('preview_size', 500))


        # 颜色加载
        self.watermark_color_var.set(settings.get('watermark_color', '#FFFFFF'))
        if hasattr(self, 'color_preview'):
            self.color_preview.config(bg=self.watermark_color_var.get())


        if self.include_exif_date_delete:
            self.keep_exif_var.set(settings.get('keep_exif', False))
            self.preserve_date_var.set(settings.get('preserve_original_date', False))
            self.delete_original_var.set(settings.get('delete_original', False))
        
        self._on_resize_mode_changed()
        self._update_enhance_enable()
        self._on_settings_changed()


class ImageConverter(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        # 根据拖拽库可用性设置窗口标题
        if DND_AVAILABLE:
            self.title("图片批量转换 Lite (支持拖拽)")
        else:
            self.title("图片批量转换 Lite (拖拽不可用，请使用按钮)")
        if getattr(sys, 'frozen', False):
            # 打包后：exe 所在目录
            base_dir = os.path.dirname(sys.executable)
        else:
            # 开发环境：脚本所在目录
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.preset_file = os.path.join(base_dir, "picpresets.json")

        # 加载配置
        self.load_settings_and_presets()

        # 窗口大小
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width - self.window_width) // 2
        y = (screen_height - self.window_height) // 2
        self.geometry(f"{self.window_width}x{self.window_height}+{x}+{y}")
        self.resizable(True, True)

        self.tasks = []
        self.history = []
        self.history_index = -1
        self.output_dir = tk.StringVar(value=self.default_output_dir)
        self.converting = False
        self.cancel_convert = False   # 取消转换标志
        self.executor = None
        self.futures = []
        self.total_tasks = 0
        self.rename_lock = threading.Lock()
        self.preview_window = None
        self.preview_canvas = None
        self.preview_status = None
        self._preview_after_id = None   # 用于存储预览更新的 after 回调 ID
        self.total_input_size = 0
        self.total_output_size = 0
        self.size_lock = threading.Lock()
        self.global_preview_size = 500  # 默认值
        self.font_cache = {}          # 缓存字体对象 key=(font_name, size)
        self.font_path_cache = {}     # 缓存字体路径 key=font_name


        # ========== 新增：解析命令行参数，必须在 create_widgets 之前 ==========
        self.initial_files = []
        if len(sys.argv) > 1:
            for arg in sys.argv[1:]:
                arg = arg.strip('"')
                if os.path.exists(arg):
                    self.initial_files.append(arg)
        # ==================================================================


        self.create_widgets()
        self.load_presets_list()
        self.save_current_state_to_history()
        # 如果有命令行传入的文件/文件夹，延迟添加
        if self.initial_files:
            self.after(100, self._add_initial_files)

        # 右键菜单
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="编辑当前任务", command=self.edit_selected_task)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="移除当前任务", command=self.remove_selected)

        self.bind_all("<Button-1>", self.on_click_outside, add=True)
        self.bind("<Configure>", lambda e: self._position_preview_window())

        # 拖拽初始化（仅当库可用时）
        if DND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.on_drop)
        else:
            messagebox.showwarning("提示", "未安装 tkinterdnd2 库，拖拽添加功能不可用。\n可使用按钮添加图片或文件夹。")

        self.processed_indices = set()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)


    def _get_font(self, font_name, font_size):
        key = (font_name, font_size)
        if key in self.font_cache:
            return self.font_cache[key]
        
        # 查找字体路径（带缓存）
        if font_name not in self.font_path_cache:
            self.font_path_cache[font_name] = self._find_font_file(font_name)
        font_path = self.font_path_cache[font_name]
        
        if font_path:
            try:
                font = ImageFont.truetype(font_path, font_size)
            except Exception as e:
                print(f"加载字体失败: {e}")
                font = ImageFont.load_default()
        else:
            font = ImageFont.load_default()
        
        self.font_cache[key] = font
        return font


    #-----输出格式处理类-----
    def _get_format_config(self, fmt):
        """获取格式配置，如果 fmt 是'保持原格式'则返回 None"""
        if fmt == "保持原格式":
            return None
        return FORMAT_CONFIG.get(fmt)
    
    def _get_output_extension(self, fmt, original_path=None):
        """获取输出文件扩展名"""
        if fmt == "保持原格式" and original_path:
            # 从原文件扩展名推断
            ext = os.path.splitext(original_path)[1].lower()
            return ext
        config = self._get_format_config(fmt)
        if config:
            return config['extension']
        return '.jpg'  # 默认
    
    def _prepare_save_params(self, fmt, quality, original_path=None):
        """
        准备保存参数。
        如果 fmt 是'保持原格式'，则根据原文件实际格式决定参数。
        """
        if fmt == "保持原格式" and original_path:
            # 根据原文件扩展名推断实际格式
            ext = os.path.splitext(original_path)[1].lower()
            actual_fmt = None
            for name, cfg in FORMAT_CONFIG.items():
                if cfg['extension'] == ext:
                    actual_fmt = name
                    break
            if actual_fmt is None:
                actual_fmt = 'JPEG'  # 默认
            config = FORMAT_CONFIG.get(actual_fmt)
        else:
            config = self._get_format_config(fmt)
        
        if not config:
            return {}
        
        save_params = {}
        quality_range = config.get('quality_range')
        if quality_range is not None and 'quality' in config['save_params']:
            min_q, max_q = quality_range
            q_clamped = max(min_q, min(max_q, quality))
            save_params['quality'] = q_clamped
        # 处理 compress_level 等其他参数
        for key, val in config['save_params'].items():
            if key == 'quality':
                continue  # 已处理
            if key == 'compress_level':
                # 质量滑块 1-100 映射到压缩级别 0-9
                if quality_range is not None and quality_range == (0, 9):
                    comp = int((100 - quality) * 9 / 99)
                    save_params['compress_level'] = comp
                else:
                    save_params[key] = val
            else:
                save_params[key] = val
        return save_params
    
    def _get_output_mode(self, img, fmt, original_path=None):
        """根据格式返回需要转换的模式（如 RGBA -> RGB）"""
        if fmt == "保持原格式" and original_path:
            ext = os.path.splitext(original_path)[1].lower()
            actual_fmt = None
            for name, cfg in FORMAT_CONFIG.items():
                if cfg['extension'] == ext:
                    actual_fmt = name
                    break
            if actual_fmt is None:
                actual_fmt = 'JPEG'
            config = FORMAT_CONFIG.get(actual_fmt)
        else:
            config = self._get_format_config(fmt)
        
        if config and config.get('mode'):
            target_mode = config['mode']
            if img.mode in ('RGBA', 'LA', 'P') and target_mode == 'RGB':
                return 'RGB'
        return None  # 不转换
    #-----输出格式处理类结束-----


    #-----水印----
    def draw_watermark(self, img, watermark_settings):
        """在图像上绘制文字水印（支持字体、大小、颜色、透明度、位置） - 透明图层叠加法"""
        if not watermark_settings.get('enable', False):
            return img
    
        text = watermark_settings.get('text', '')
        if not text:
            return img
    
        font_name = watermark_settings.get('font', 'Arial')
        font_size = watermark_settings.get('size', 36)
        opacity = watermark_settings.get('opacity', 80) / 100.0   # 0~1
        position = watermark_settings.get('position', '右下')
        color_hex = watermark_settings.get('color', '#FFFFFF')
    
        # 透明度为 0，直接返回原图（完全透明）
        if opacity <= 0:
            return img
    
        # 确保图像为 RGBA 模式（支持透明通道）
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
    
        w, h = img.size
    
        # 创建一个全透明的图层
        overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
    
        # 解析颜色
        color_hex = color_hex.lstrip('#')
        r = int(color_hex[0:2], 16)
        g = int(color_hex[2:4], 16)
        b = int(color_hex[4:6], 16)
        alpha = int(255 * opacity)   # 整体透明度
    
        # 加载字体
        font = self._get_font(font_name, font_size)
    
        # 获取文本尺寸
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        w, h = img.size

        # 动态边距：短边 * 3%
        short_side = min(w, h)
        padding = max(5, min(30, int(short_side * 0.03)))

        # 位置映射
        pos_map = {
            '左上': (padding, padding),
            '上': ((w - tw) // 2, padding),
            '右上': (w - tw - padding, padding),
            '左中': (padding, (h - th) // 2),
            '中': ((w - tw) // 2, (h - th) // 2),
            '右中': (w - tw - padding, (h - th) // 2),
            '左下': (padding, h - th - padding),
            '下': ((w - tw) // 2, h - th - padding),
            '右下': (w - tw - padding, h - th - padding),
        }
        x, y = pos_map.get(position, (w - tw - padding, h - th - padding))
    
        # 在透明图层上绘制文字（仅一次，无描边）
        draw.text((x, y), text, font=font, fill=(r, g, b, alpha))
    
        # 将透明图层与原图合成
        result = Image.alpha_composite(img, overlay)
        return result



    def _add_initial_files(self):
        """处理命令行传入的文件/文件夹"""
        image_files = []
        for path in self.initial_files:
            if os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    for f in files:
                        if os.path.splitext(f)[1].lower() in SUPPORTED_IMG_EXTS:
                            image_files.append(os.path.join(root, f))
            elif os.path.isfile(path) and os.path.splitext(path)[1].lower() in SUPPORTED_IMG_EXTS:
                image_files.append(path)
        if image_files:
            self._add_image_paths(image_files)
#            messagebox.showinfo("提示", f"已自动添加 {len(image_files)} 张图片")

    def set_file_times(self, filepath, creation_time, access_time, modification_time):
        """设置文件的创建时间、访问时间和修改时间（Windows专用）"""
        if platform.system() != 'Windows':
            # 非Windows系统只能通过os.utime设置访问和修改时间
            os.utime(filepath, (access_time, modification_time))
            return
        
        # 将Python时间戳（浮点数）转换为Windows FILETIME（100纳秒间隔，从1601年1月1日起）
        def to_filetime(timestamp):
            # Windows epoch 1601-01-01 到 Unix epoch 1970-01-01 的间隔（秒）
            EPOCH_DIFF = 11644473600.0
            # 转换为100纳秒单位
            ft = int((timestamp + EPOCH_DIFF) * 10000000)
            # 低位和高位
            low = ft & 0xFFFFFFFF
            high = ft >> 32
            return wintypes.DWORD(low), wintypes.DWORD(high)
        
        # 转换时间
        ct_low, ct_high = to_filetime(creation_time)
        at_low, at_high = to_filetime(access_time)
        mt_low, mt_high = to_filetime(modification_time)
        
        # 创建 FILETIME 结构体
        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD),
                        ("dwHighDateTime", wintypes.DWORD)]
        
        creation_ft = FILETIME(ct_low, ct_high)
        access_ft = FILETIME(at_low, at_high)
        modify_ft = FILETIME(mt_low, mt_high)
        
        # 调用 SetFileTime
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateFileW(filepath, 0x40000000, 0x3, None, 3, 0x80, None)  # 打开文件以写入属性
        if handle != -1:
            kernel32.SetFileTime(handle, ctypes.byref(creation_ft), ctypes.byref(access_ft), ctypes.byref(modify_ft))
            kernel32.CloseHandle(handle)


    # ---------- 预览功能 ----------
    def on_task_select(self, event=None):
        sel = self.task_listbox.curselection()
        if len(sel) == 1:
            self._show_preview(self.tasks[sel[0]])

    def _show_preview(self, task):
        if self.preview_window is not None and self.preview_window.winfo_exists():
            self._update_preview_content(task)
            self._position_preview_window()
            self.preview_window.lift()
        else:
            self.preview_window = Toplevel(self)
            self.preview_window.title("图片预览")
            self.preview_window.transient(self)
            self.preview_window.attributes('-toolwindow', 1)
            self.preview_window.geometry("500x500")
            self.preview_window.minsize(200, 200)
            self.preview_canvas = tk.Canvas(self.preview_window, bg='gray', relief=tk.SUNKEN)
            self.preview_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            self.preview_status = ttk.Label(self.preview_window, text="正在生成预览...")
            self.preview_status.pack(pady=5)


            def on_close():
                if self._preview_after_id is not None:
                    try:
                        self.preview_window.after_cancel(self._preview_after_id)
                    except:
                        pass
                    self._preview_after_id = None
                if self.preview_window:
                    self.preview_window.destroy()
                    self.preview_window = None
                    self.preview_canvas = None
                    self.preview_status = None
            self.preview_window.protocol("WM_DELETE_WINDOW", on_close)
            self.preview_window.update_idletasks()
            self._position_preview_window()
            self._update_preview_content(task)

    def _position_preview_window(self):
        if self.preview_window is None or not self.preview_window.winfo_exists():
            return
        self.update_idletasks()
        main_x = self.winfo_x()
        main_y = self.winfo_y()
        main_w = self.winfo_width()
        main_h = self.winfo_height()
        win_w = self.preview_window.winfo_reqwidth()
        win_h = self.preview_window.winfo_reqheight()
        if win_w < 100:
            win_w = 500
        if win_h < 100:
            win_h = 500
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = main_x + main_w + 5
        y = main_y
        # 边界检查
        if x + win_w > screen_w:
            x = screen_w - win_w - 10
            if x < 0:
                x = 10
        if y + win_h > screen_h:
            y = screen_h - win_h - 10
        if y < 0:
            y = 10
        self.preview_window.geometry(f"+{x}+{y}")

    def _update_preview_content(self, task):
        if self.preview_window is None or not self.preview_window.winfo_exists():
            return
    
        # 取消之前尚未执行的预览生成任务
        if self._preview_after_id is not None:
            try:
                self.preview_window.after_cancel(self._preview_after_id)
            except Exception:
                pass
            self._preview_after_id = None
    
        if self.preview_canvas:
            self.preview_canvas.delete("all")
        if self.preview_status:
            self.preview_status.config(text="正在生成预览...")
    
        def generate():
            self._preview_after_id = None   # 任务开始执行，清除 ID
            if self.preview_window is None or not self.preview_window.winfo_exists():
                return
            try:
                with Image.open(task['path']) as img:
                    # 旋转
                    angle = int(task['rotation'].rstrip('°'))
                    if angle != 0:
                        img = img.rotate(angle, expand=True, resample=Image.NEAREST)
                    # 翻转
                    if task['h_flip']:
                        img = img.transpose(Image.FLIP_LEFT_RIGHT)
                    if task['v_flip']:
                        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    
                    # 缩放
                    if task['resize_mode'] != "无调整":
                        img = self.apply_resize(img, task['resize_mode'], task['resize_w'], task['resize_h'], resample=Image.NEAREST)
    
                    # 裁剪
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
    
                    # 亮度
                    if task.get('brightness_enable', False) and task.get('brightness_val', 0) != 0:
                        enhancer = ImageEnhance.Brightness(img)
                        factor = 1 + task['brightness_val'] / 100.0
                        img = enhancer.enhance(factor)
    
                    # 对比度
                    if task.get('contrast_enable', False) and task.get('contrast_val', 0) != 0:
                        enhancer = ImageEnhance.Contrast(img)
                        factor = 1 + task['contrast_val'] / 100.0
                        img = enhancer.enhance(factor)
    
                    # 饱和度
                    if task.get('saturation_enable', False) and task.get('saturation_val', 0) != 0:
                        enhancer = ImageEnhance.Color(img)
                        factor = 1 + task['saturation_val'] / 100.0
                        img = enhancer.enhance(factor)
    
                    # RGB
                    if task.get('color_enable', False):
                        r_factor = (task.get('r_gain', 0) + 100) / 100.0
                        g_factor = (task.get('g_gain', 0) + 100) / 100.0
                        b_factor = (task.get('b_gain', 0) + 100) / 100.0
                        if r_factor != 1 or g_factor != 1 or b_factor != 1:
                            r, g, b = img.split()
                            r = r.point(lambda i: i * r_factor)
                            g = g.point(lambda i: i * g_factor)
                            b = b.point(lambda i: i * b_factor)
                            img = Image.merge('RGB', (r, g, b))
    
                    # 锐化
                    if task.get('sharpen_enable', False) and task.get('sharpen_val', 0) != 0:
                        enhancer = ImageEnhance.Sharpness(img)
                        factor = 1 + task['sharpen_val'] / 100.0
                        img = enhancer.enhance(factor)
    
                    # 文字水印
                    watermark_settings = {
                        'enable': task.get('watermark_enable', False),
                        'text': task.get('watermark_text', ''),
                        'font': task.get('watermark_font', 'Arial'),
                        'size': task.get('watermark_size', 36),
                        'position': task.get('watermark_position', '右下'),
                        'opacity': task.get('watermark_opacity', 80),
                        'color': task.get('watermark_color', '#FFFFFF'),
                    }
                    img = self.draw_watermark(img, watermark_settings)
    
                    # 缩放预览到画布大小
                    preview_size = self.global_preview_size
                    img.thumbnail((preview_size, preview_size), Image.NEAREST)
                    thumb_w, thumb_h = img.size
    
                    # 调整窗口大小
                    win_w = thumb_w + 20
                    win_h = thumb_h + 70
                    self.preview_window.geometry(f"{win_w}x{win_h}")
    
                    # 更新 Canvas 尺寸
                    self.preview_canvas.config(width=thumb_w, height=thumb_h)
    
                    # 创建 PhotoImage 并保持引用
                    photo = ImageTk.PhotoImage(img)
                    self.preview_canvas.delete("all")
                    self.preview_canvas.create_image(thumb_w//2, thumb_h//2, image=photo, anchor=tk.CENTER)
                    self.preview_canvas.image = photo  # 防止被垃圾回收
    
                    self.preview_canvas.update_idletasks()
    
                    if self.preview_status:
                        self.preview_status.config(text=f"预览完成 | 缩略图尺寸: {thumb_w}x{thumb_h}")
            except Exception as e:
                if self.preview_status:
                    self.preview_status.config(text=f"预览失败: {str(e)}")
                if self.preview_canvas:
                    self.preview_canvas.delete("all")
                    self.preview_canvas.create_text(10, 10, anchor=tk.NW, text=f"错误: {e}", fill="red")
    
        self._preview_after_id = self.preview_window.after(10, generate)

    # ---------- 配置加载/保存 ----------
    def load_settings_and_presets(self):
        """加载配置文件：顶层包含 settings 对象和各个预设"""
        default_settings = {
            "window_width": 860,
            "window_height": 760,
            "default_output_dir": os.getcwd(),
            "thread_count": min(8, os.cpu_count() or 4),
            "keep_exif": False,
            "preserve_original_date": False,
            "delete_original": False,
        }
        self.presets = {}
        if not os.path.exists(self.preset_file):
            # 新文件，使用默认值
            self.window_width = default_settings["window_width"]
            self.window_height = default_settings["window_height"]
            self.default_output_dir = default_settings["default_output_dir"]
            self.default_threads = default_settings["thread_count"]
            self.keep_exif = default_settings["keep_exif"]
            self.preserve_original_date = default_settings["preserve_original_date"]
            self.delete_original = default_settings["delete_original"]
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
            self.preserve_original_date = settings.get("preserve_original_date", default_settings["preserve_original_date"])
            self.delete_original = settings.get("delete_original", default_settings["delete_original"])
            self.presets = {k: v for k, v in data.items() if k != "settings"}
        except Exception as e:
            print(f"加载配置失败: {e}，使用默认值")
            self.window_width = default_settings["window_width"]
            self.window_height = default_settings["window_height"]
            self.default_output_dir = default_settings["default_output_dir"]
            self.default_threads = default_settings["thread_count"]
            self.keep_exif = default_settings["keep_exif"]
            self.preserve_original_date = default_settings["preserve_original_date"]
            self.delete_original = default_settings["delete_original"]
            self.presets = {}

    def save_settings_and_presets(self):
        """保存配置：将全局设置放入 settings 对象，预设放在顶层"""
        data = {
            "settings": {
                "window_width": self.winfo_width(),
                "window_height": self.winfo_height(),
                "default_output_dir": os.path.normpath(self.output_dir.get()),
                "thread_count": self.thread_count_var.get(),
                "keep_exif": self.keep_exif_var.get(),
                "preserve_original_date": self.preserve_date_var.get(),
                "delete_original": self.delete_original_var.get(),
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

    # ---------- 撤销功能 ----------
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
            messagebox.showinfo("撤销", "已恢复到上一次状态")
        else:
            messagebox.showinfo("提示", "没有更早的状态")

    def refresh_task_listbox(self):
        self.task_listbox.delete(0, tk.END)
        for task in self.tasks:
            self.task_listbox.insert(tk.END, self.get_task_display_text(task))

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
        self.browse_btn.config(state=state)
        self.load_preset_btn.config(state=state)
        self.save_preset_btn.config(state=state)
        self.delete_preset_btn.config(state=state)
        self.set_widgets_state(self.template_container, state)
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

    # ---------- 表达式计算 ----------
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

    # ---------- 重名处理 ----------
    def resolve_duplicate_paths(self, tasks, out_dir):
        """
        解析重复文件名的处理策略。
        参数:
            tasks: 原始任务列表（字典）
            out_dir: 输出目录，如果为 None 则表示输出到每个文件的原目录
        返回:
            list of (task, original_index) 元组，task 中已包含 'out_path' 键
        """
        resolved_items = []
        duplicate_mode = self.duplicate_mode_var.get()
        
        # 辅助函数：根据任务和输出目录生成最终输出路径
        def make_output_path(task, base_out_dir):
            name_or_path = self.build_output_name(task['name_template'], task['path'])
            fmt = task['format']
            if fmt == "保持原格式":
                ext = os.path.splitext(task['path'])[1].lower()
            else:
                ext = self._get_output_extension(fmt)
            # 如果名称模板包含了 {Original}，则 name_or_path 已经是完整路径（不含扩展名）
            if "{Original}" in task['name_template']:
                full_path = name_or_path + ext
            else:
                if base_out_dir is None:
                    base_out_dir = os.path.dirname(task['path'])
                full_path = os.path.join(base_out_dir, name_or_path + ext)
            return full_path
        
        if duplicate_mode in ("覆盖", "自动重命名"):
            for idx, task in enumerate(tasks):
                task_copy = task.copy()
                task_copy['out_path'] = None   # 稍后在转换时决定，以避免文件名冲突
                resolved_items.append((task_copy, idx))
            return resolved_items
        
        if duplicate_mode == "跳过":
            for idx, task in enumerate(tasks):
                base_out = make_output_path(task, out_dir)
                if os.path.exists(base_out):
                    continue   # 跳过此任务
                task_copy = task.copy()
                task_copy['out_path'] = base_out
                resolved_items.append((task_copy, idx))
            return resolved_items
        
        if duplicate_mode == "询问":
            conflicts = []
            for idx, task in enumerate(tasks):
                base_out = make_output_path(task, out_dir)
                conflicts.append((task, base_out, idx))
            
            apply_to_all = None
            for task, original_path, original_idx in conflicts:
                final_path = original_path
                if os.path.exists(original_path):
                    if apply_to_all is None:
                        result = self._ask_duplicate_action(original_path)
                        if result == "apply_overwrite":
                            apply_to_all = "overwrite"
                            final_path = original_path
                        elif result == "apply_rename":
                            apply_to_all = "rename"
                            final_path = self._auto_rename_path(original_path)
                        elif result == "apply_skip":
                            apply_to_all = "skip"
                            continue
                        elif result == "overwrite":
                            final_path = original_path
                        elif result == "rename":
                            final_path = self._auto_rename_path(original_path)
                        elif result == "skip":
                            continue
                    else:
                        if apply_to_all == "overwrite":
                            final_path = original_path
                        elif apply_to_all == "rename":
                            final_path = self._auto_rename_path(original_path)
                        elif apply_to_all == "skip":
                            continue
                else:
                    final_path = original_path
                task_copy = task.copy()
                task_copy['out_path'] = final_path
                resolved_items.append((task_copy, original_idx))
            return resolved_items
        
        return resolved_items

    def _ask_duplicate_action(self, path):
        dlg = Toplevel(self)
        dlg.withdraw()
        dlg.title("文件已存在")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("500x200")
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - dlg.winfo_width()) // 2
        y = self.winfo_y() + (self.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.deiconify()
        dlg.lift()
        dlg.focus_force()
        label = ttk.Label(dlg, text=f"输出文件已存在：\n{path}\n\n请选择操作：")
        label.pack(pady=15)
        result = ["overwrite"]
        def set_result(value):
            result[0] = value
            dlg.destroy()
        frame1 = ttk.Frame(dlg)
        frame1.pack(pady=5)
        ttk.Button(frame1, text="覆盖", width=12, command=lambda: set_result("overwrite")).pack(side=tk.LEFT, padx=8)
        ttk.Button(frame1, text="自动重命名", width=12, command=lambda: set_result("rename")).pack(side=tk.LEFT, padx=8)
        ttk.Button(frame1, text="跳过此文件", width=12, command=lambda: set_result("skip")).pack(side=tk.LEFT, padx=8)
        ttk.Separator(dlg, orient='horizontal').pack(fill=tk.X, pady=10, padx=20)
        frame2 = ttk.Frame(dlg)
        frame2.pack(pady=5)
        ttk.Button(frame2, text="全部覆盖", width=12, command=lambda: set_result("apply_overwrite")).pack(side=tk.LEFT, padx=8)
        ttk.Button(frame2, text="全部重命名", width=12, command=lambda: set_result("apply_rename")).pack(side=tk.LEFT, padx=8)
        ttk.Button(frame2, text="全部跳过", width=12, command=lambda: set_result("apply_skip")).pack(side=tk.LEFT, padx=8)
        self.wait_window(dlg)
        return result[0]

    def _auto_rename_path(self, path):
        return self._get_unique_filename(path, "自动重命名")

    # ---------- 界面构建 ----------
    def create_widgets(self):
        left_frame = ttk.Frame(self)
        left_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        io_frame = ttk.LabelFrame(left_frame, text="输入与输出")
        io_frame.pack(fill=tk.X, pady=5)
        io_row = ttk.Frame(io_frame)
        io_row.pack(fill=tk.X, padx=5, pady=5)
        self.add_files_btn = ttk.Button(io_row, text="添加图片", command=self.add_files)
        self.add_files_btn.pack(side=tk.LEFT, padx=2)
        self.add_folder_btn = ttk.Button(io_row, text="遍历文件夹", command=self.add_folders)
        self.add_folder_btn.pack(side=tk.LEFT, padx=2)
        ttk.Label(io_row, text="输出目录:").pack(side=tk.LEFT, padx=(10,2))
        self.output_dir_entry = ttk.Entry(io_row, textvariable=self.output_dir, width=40)
        self.output_dir_entry.pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        self.browse_btn = ttk.Button(io_row, text="浏览", command=self.select_output_dir)
        self.browse_btn.pack(side=tk.LEFT, padx=2)

        # 模板容器（包含所有参数控件）
        self.template_container = ttk.LabelFrame(left_frame, text="当前模板（新任务将使用此设置）- 处理顺序: 旋转→翻转→缩放→裁剪→更多")
        self.template_container.pack(fill=tk.X, pady=5)

        # 图像参数编辑器
        self.template_editor = TemplateEditor(self.template_container, include_exif_date_delete=True, default_expanded=False)
        self.template_editor.pack(fill=tk.X, padx=5, pady=5)
        self.template_editor.bind_preview_callback(self.update_template_preview)

        # 输出名称模板、重名处理、预设（同一行）
        row4 = ttk.Frame(self.template_container)
        row4.pack(fill=tk.X, pady=5, padx=5)
        
        ttk.Label(row4, text="输出名称模板:").pack(side=tk.LEFT, padx=2)
        self.name_template_var = tk.StringVar(value="{Filename}")
        template_combo = ttk.Combobox(row4, textvariable=self.name_template_var,
                                      values=["{Filename}", "{Folder name}{Filename}", "{Original}/{Filename}", "{Folder name}_{Filename}", "{Original}/123/{Filename}", "{Folder name}/{Filename}", "{Original}/{Folder name}/{Filename}"],
                                      width=23)
        template_combo.pack(side=tk.LEFT, padx=2)
        self.name_template_var.trace_add('write', lambda *a: self.update_template_preview())
        ttk.Label(row4, text="重名处理:").pack(side=tk.LEFT, padx=(10,2))
        self.duplicate_mode_var = tk.StringVar(value="覆盖")
        dup_combo = ttk.Combobox(row4, textvariable=self.duplicate_mode_var,
                                 values=["覆盖", "自动重命名", "询问", "跳过"], state="readonly", width=10)
        dup_combo.pack(side=tk.LEFT, padx=2)
        # 预设
        ttk.Label(row4, text="预设:").pack(side=tk.LEFT, padx=(10,2))
        self.preset_combo = ttk.Combobox(row4, state="readonly", width=16)
        self.preset_combo.pack(side=tk.LEFT, padx=2)
        self.load_preset_btn = ttk.Button(row4, text="加载", command=self.load_preset, width=6)
        self.load_preset_btn.pack(side=tk.LEFT, padx=2)
        self.save_preset_btn = ttk.Button(row4, text="保存", command=self.save_preset, width=6)
        self.save_preset_btn.pack(side=tk.LEFT, padx=2)
        self.delete_preset_btn = ttk.Button(row4, text="删除", command=self.delete_preset, width=6)
        self.delete_preset_btn.pack(side=tk.LEFT, padx=2)

        # 模板预览标签
        self.template_preview_label = ttk.Label(self.template_container, text="", relief="sunken")
        self.template_preview_label.pack(fill=tk.X, pady=5, padx=5)
        self.update_template_preview(self.template_editor.get_settings())

        # 任务列表
        list_frame = ttk.LabelFrame(left_frame, text="转换任务（单击预览，右键编辑）")
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

        # 按钮区
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        self.start_btn = ttk.Button(btn_frame, text="开始转换", command=self.start_convert)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.cancel_btn = ttk.Button(btn_frame, text="取消转换", command=self.cancel_convert_func, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=5)
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

        # 同步全局变量
        self.keep_exif_var = self.template_editor.keep_exif_var
        self.preserve_date_var = self.template_editor.preserve_date_var
        self.delete_original_var = self.template_editor.delete_original_var
        # 同步从配置文件加载的初始值到界面控件
        self.preserve_date_var.set(self.preserve_original_date)
        self.keep_exif_var.set(self.keep_exif)
        self.delete_original_var.set(self.delete_original)

    def update_template_preview(self, settings=None):
        if settings is None:
            settings = self.template_editor.get_settings()
        # 更新全局预览尺寸
        if 'preview_size' in settings:
            self.global_preview_size = settings['preview_size']
        fmt = settings['format']
        qual = settings['quality']
        rot = settings['rotation']
        rot_display = {"0°":"无", "90°":"左90", "-90°":"右90", "180°":"180"}.get(rot, rot)
        flip = []
        if settings['h_flip']: flip.append("水平")
        if settings['v_flip']: flip.append("垂直")
        flip_str = " | ".join(flip) if flip else "无翻转"
        mode = settings['resize_mode']
        size_info = ""
        if mode == "精确 (WxH)":
            size_info = f" | 尺寸: {settings['resize_w']}x{settings['resize_h']} (精确)"
        elif mode == "限制长边":
            size_info = f" | 长边: {settings['resize_w']}px"
        elif mode == "限制短边":
            size_info = f" | 短边: {settings['resize_w']}px"
        else:
            size_info = " | 不调整尺寸"
        crop_info = ""
        if settings.get('crop_enabled', False):
            crop_info = f" | 裁剪: x={settings['crop_x']} y={settings['crop_y']} w={settings['crop_w']} h={settings['crop_h']}"
        template = self.name_template_var.get()
        fake_path = "D:/test/image.jpg"
        name_part = self.build_output_name(template, fake_path)
        if "{Original}" in template:
            drive, rest = os.path.splitdrive(name_part)
            if rest.startswith(('/', '\\')):
                rest = rest[1:]
            name_part = rest
        ext_map = {'JPEG':'.jpg', 'PNG':'.png', 'WEBP':'.webp'}
        ext = ext_map.get(settings.get('format', 'JPEG'), '.jpg')
        example_out = name_part + ext
        
        self.template_preview_label.config(
            text=f"模板: {fmt} | Q{qual} | {rot_display} | {flip_str}{size_info}{crop_info} | 输出示例: {example_out}"
        )


    # ---------- 添加图片/文件夹 ----------
    def add_files(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法添加新任务")
            return
        file_paths = filedialog.askopenfilenames(
            title="选择图片文件",
            filetypes=[
                ("所有支持的图片", " ".join(f"*{ext}" for ext in SUPPORTED_IMG_EXTS)),
                ("所有文件", "*.*")
            ]
        )
        if not file_paths:
            return
        self._add_image_paths(file_paths)

    def add_folders(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法添加新任务")
            return
        folder = filedialog.askdirectory(title="选择包含图片的文件夹")
        if not folder:
            return
        image_files = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in SUPPORTED_IMG_EXTS:
                    image_files.append(os.path.join(root, f))
        if not image_files:
            messagebox.showinfo("提示", "所选文件夹中没有找到支持的图片")
            return
        self._add_image_paths(image_files)

    def _add_image_paths(self, paths):
        current = self.template_editor.get_settings()
        if 'preview_size' in current:
            del current['preview_size']
        current['name_template'] = self.name_template_var.get()
        current['duplicate_mode'] = self.duplicate_mode_var.get()
        added = 0
        for fp in paths:
            task = {'path': fp, **current}
            self.tasks.append(task)
            self.task_listbox.insert(tk.END, self.get_task_display_text(task))
            added += 1
        if added > 0:
            self.save_current_state_to_history()

    # ---------- 右键菜单 ----------
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
        first_idx = selection[0]
        first_task = self.tasks[first_idx]
        self.edit_task_dialog(first_idx, first_task, selected_indices=selection)

    # ---------- 辅助函数 ----------
    def get_task_display_text(self, task):
        filename = os.path.basename(task['path'])
        out_name = self.build_output_name(task['name_template'], task['path'])
        if task['format'] == "保持原格式":
            ext = os.path.splitext(task['path'])[1].lower()
        else:
            ext = self._get_output_extension(task['format'])
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
        if task.get('delete_original', False):
            param_str = param_str[:-1] + " 删]"
        return f"{filename} → {out_full} {param_str}"

    def select_output_dir(self):
        d = filedialog.askdirectory(initialdir=self.output_dir.get())
        if d:
            self.output_dir.set(os.path.normpath(d))
            self.save_settings_and_presets()

    def apply_resize(self, img, mode, param_w, param_h, resample=Image.LANCZOS):
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
        return img.resize((new_w, new_h), resample)

    def build_output_name(self, template, file_path):
        """
        根据模板生成输出文件名（或包含路径的文件名）。
    
        模板占位符：
            {Filename}   - 原文件名（不含扩展名）
            {Folder name} - 原文件所在文件夹的名称（最后一级目录名）
            {Original}    - 原文件所在目录的完整绝对路径
    
        如果模板中包含 {Original}，则返回完整的输出路径（目录+文件名，不含扩展名），
        否则仅返回文件名（不含扩展名和目录）。
    
        参数：
            template (str): 输出名称模板，例如 "{Original}/resized/{Filename}"
            file_path (str): 原文件的完整路径
    
        返回：
            str: 生成的输出名称（不含扩展名），或完整输出路径（不含扩展名）
        """
        dirname = os.path.dirname(file_path)          # 原文件所在目录
        folder_name = os.path.basename(dirname)       # 最后一级目录名
        base_name = os.path.splitext(os.path.basename(file_path))[0]  # 文件名无扩展名
    
        # 依次替换占位符
        result = template
        result = result.replace("{Filename}", base_name)
        result = result.replace("{Folder name}", folder_name)
        result = result.replace("{Original}", dirname)
    
        # 规范化路径（处理多余的斜杠或反斜杠）
        result = os.path.normpath(result)
    
        # 如果模板中使用了 {Original}，则 result 已经是完整路径的一部分（可能还包含文件名）
        # 注意：此时不添加扩展名，扩展名会在调用方（如 resolve_duplicate_paths 或 _convert_single）中附加
        return result

    # ---------- 拖放文件夹支持 ----------
    def on_drop(self, event):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法添加新任务")
            return
    
        raw_data = event.data.strip()
        if not raw_data:
            return
    
        # ----- 解析拖拽数据（轻量操作，仍可在主线程）-----
        files = []
        if DND_AVAILABLE and hasattr(self, 'tk'):
            try:
                files = self.tk.splitlist(raw_data)
                if len(files) < 5 and len(raw_data) > 500:
                    files = []
            except Exception:
                files = []
    
        if not files:
            import re
            matches = re.findall(r'\{(.*?)\}', raw_data)
            if matches:
                files = [m.strip() for m in matches if m.strip()]
            else:
                files = [p.strip('{}') for p in raw_data.split() if p.strip()]
    
        cleaned = []
        for fp in files:
            fp = fp.strip()
            if not fp:
                continue
            if fp.startswith('\\\\?\\'):
                fp = fp[4:]
            cleaned.append(fp)
    
        # 如果没有任何有效路径，直接返回
        if not cleaned:
            messagebox.showinfo("提示", "未检测到有效的文件或文件夹")
            return
    
        # ----- 后台遍历文件夹 -----
        # 先禁用拖拽相关操作，避免重复添加
        self.drop_target_unregister() if DND_AVAILABLE else None
        # 显示一个简单的提示标签（可选）
        self.progress_label.config(text="正在扫描文件夹，请稍候...")
        self.update_idletasks()
    
        # 启动后台线程
        def scan_folders():
            image_files = []
            for fp in cleaned:
                if os.path.isdir(fp):
                    for root, dirs, filenames in os.walk(fp):
                        for f in filenames:
                            if os.path.splitext(f)[1].lower() in SUPPORTED_IMG_EXTS:
                                image_files.append(os.path.join(root, f))
                elif os.path.isfile(fp) and os.path.splitext(fp)[1].lower() in SUPPORTED_IMG_EXTS:
                    image_files.append(fp)
            # 扫描完成后，通过 after 回到主线程处理
            self.after(0, lambda: self._on_drop_scan_complete(cleaned, image_files))
    
        threading.Thread(target=scan_folders, daemon=True).start()
    
    def _on_drop_scan_complete(self, cleaned, image_files):
        # 恢复拖拽注册
        if DND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.on_drop)
    
        if not image_files:
            self.progress_label.config(text="就绪")
            messagebox.showinfo("提示", "未检测到支持的图片")
            return
    
        # 解析统计提示（帮助用户发现异常）
        if len(cleaned) != len(image_files):
            diff = len(cleaned) - len(image_files)
            messagebox.showwarning("注意",
                f"拖拽解析到 {len(cleaned)} 个文件/文件夹，\n"
                f"其中包含 {len(image_files)} 张图片。\n"
                f"如果数量明显少于预期，可能是因为系统拖拽数据被截断。\n"
                f"建议分批拖拽或使用“添加图片”按钮。")
        else:
            if len(image_files) > 200:
                if not messagebox.askyesno("确认添加",
                    f"即将添加 {len(image_files)} 个任务，是否继续？"):
                    self.progress_label.config(text="就绪")
                    return
    
        self._add_image_paths(image_files)
        self.progress_label.config(text="就绪")
    


    # ---------- 编辑任务对话框 ----------
    def edit_task_dialog(self, idx, task, selected_indices=None):
        dlg = Toplevel(self)
        dlg.withdraw()
        dlg.title("编辑任务参数")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("800x440")  # 调小尺寸，因为不需要右侧预览
        dlg.update_idletasks()

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = self.winfo_x() + (self.winfo_width() - dlg.winfo_width()) // 2
        y = self.winfo_y() + (self.winfo_height() - dlg.winfo_height()) // 2
        x = max(0, min(x, screen_w - dlg.winfo_width()))
        y = max(0, min(y, screen_h - dlg.winfo_height()))
        dlg.geometry(f"+{x}+{y}")
        dlg.deiconify()
        dlg.lift()
        dlg.focus_force()
    
        # 只保留左侧参数面板
        left_panel = ttk.Frame(dlg)
        left_panel.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
        # 编辑器（默认展开更多调整）
        editor = TemplateEditor(left_panel, include_exif_date_delete=True, default_expanded=True)
        editor.pack(fill=tk.BOTH, expand=True)
        editor.set_settings(task)
        editor.preview_size_var.set(self.global_preview_size)
    
        # 输出名称模板、重名处理（单独一行）
        row = ttk.Frame(left_panel)
        row.pack(fill=tk.X, pady=5)
        ttk.Label(row, text="输出名称模板:").pack(side=tk.LEFT, padx=5)
        name_var = tk.StringVar(value=task.get('name_template', '{Filename}'))
        name_combo = ttk.Combobox(row, textvariable=name_var,
                                  values=["{Filename}", "{Folder name}{Filename}", "{Original}/{Filename}", "{Folder name}_{Filename}", "{Original}/123/{Filename}"],
                                  width=20)
        name_combo.pack(side=tk.LEFT, padx=5)
        ttk.Label(row, text="重名处理:").pack(side=tk.LEFT, padx=(10,5))
        dup_var = tk.StringVar(value=task.get('duplicate_mode', '覆盖'))
        dup_combo = ttk.Combobox(row, textvariable=dup_var,
                                 values=["覆盖", "自动重命名", "询问", "跳过"], state="readonly", width=10)
        dup_combo.pack(side=tk.LEFT, padx=5)
    
        # ---------- 预览更新函数（更新主预览窗口） ----------
        def update_main_preview():
            # 获取当前编辑器的设置
            new_settings = editor.get_settings()
            new_settings['name_template'] = name_var.get()
            new_settings['duplicate_mode'] = dup_var.get()
            # 同步全局预览尺寸
            if 'preview_size' in new_settings:
                self.global_preview_size = new_settings['preview_size']
                self.template_editor.preview_size_var.set(self.global_preview_size)
            # 创建预览任务（原任务 + 新设置）
            preview_task = task.copy()
            preview_task.update(new_settings)
            # 确保主预览窗口存在并更新
            if self.preview_window is None or not self.preview_window.winfo_exists():
                self._show_preview(preview_task)
            else:
                self._update_preview_content(preview_task)
    
        # 绑定编辑器所有设置变化
        editor.bind_preview_callback(lambda s: update_main_preview())
        # 名称模板和重名处理变化也触发刷新
        name_var.trace_add('write', lambda *a: update_main_preview())
        dup_var.trace_add('write', lambda *a: update_main_preview())
    
        # 初始打开时，确保主预览窗口显示当前任务
        if self.preview_window is None or not self.preview_window.winfo_exists():
            self._show_preview(task)
        else:
            self._update_preview_content(task)
    
        # ---------- 保存按钮逻辑 ----------
        def save_single():
            new_settings = editor.get_settings()
            new_settings.pop('preview_size', None)
            new_settings['name_template'] = name_var.get()
            new_settings['duplicate_mode'] = dup_var.get()
            task.update(new_settings)
            new_display = self.get_task_display_text(task)
            self.task_listbox.delete(idx)
            self.task_listbox.insert(idx, new_display)
            # 更新主预览窗口为当前任务（保存后参数固定）
            self._update_preview_content(task)
            self.save_current_state_to_history()
            dlg.destroy()
    
        def save_batch():
            new_settings = editor.get_settings()
            new_settings.pop('preview_size', None)
            new_settings['name_template'] = name_var.get()
            new_settings['duplicate_mode'] = dup_var.get()
            for i in selected_indices:
                t = self.tasks[i]
                t.update(new_settings)
                self.task_listbox.delete(i)
                self.task_listbox.insert(i, self.get_task_display_text(t))
            if selected_indices:
                self._update_preview_content(self.tasks[selected_indices[0]])
            self.save_current_state_to_history()
            dlg.destroy()

        def sync_to_main():
            # 获取当前编辑器的设置
            new_settings = editor.get_settings()
            new_settings['name_template'] = name_var.get()
            new_settings['duplicate_mode'] = dup_var.get()
            # 移除预览尺寸（全局参数，不应覆盖主窗口）
            new_settings.pop('preview_size', None)
            # 将设置应用到主窗口的模板编辑器
            self.template_editor.set_settings(new_settings)
            # 刷新主窗口的模板预览标签
            self.update_template_preview(new_settings)
            # 可选：弹出一个短暂提示
            messagebox.showinfo("同步完成", "已将当前参数同步到主窗口模板")
    
        btn_frame = ttk.Frame(left_panel)
        btn_frame.pack(pady=15)
        is_multi = selected_indices is not None and len(selected_indices) > 1
        if not is_multi:
            ttk.Button(btn_frame, text="保存", command=save_single).pack(side=tk.LEFT, padx=10)
        else:
            ttk.Button(btn_frame, text="仅保存当前任务", command=save_single).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text=f"应用到所有 {len(selected_indices)} 个任务", command=save_batch).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=10)
        # 添加同步按钮
        ttk.Button(btn_frame, text="同步当前参数到主窗口", command=sync_to_main).pack(side=tk.LEFT, padx=5)




    # ---------- 任务管理 ----------
    def remove_selected(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法删除任务")
            return
        for i in reversed(self.task_listbox.curselection()):
            del self.tasks[i]
            self.task_listbox.delete(i)
        self.save_current_state_to_history()

    def clear_tasks(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法清空列表")
            return
        self.tasks.clear()
        self.task_listbox.delete(0, tk.END)
        self.progress_var.set(0)
        self.progress_label.config(text="就绪")
        self.save_current_state_to_history()

    def cancel_convert_func(self):
        """用户点击取消按钮时调用"""
        if self.converting:
            self.cancel_convert = True
            self.progress_label.config(text="正在取消...")
            self.cancel_btn.config(state=tk.DISABLED)  # 防止重复点击

    # ---------- 预设功能 ----------
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
        current_name = self.preset_combo.get()
        if current_name:
            name = simpledialog.askstring("保存预设", "请输入预设名称:", parent=self, initialvalue=current_name)
        else:
            name = simpledialog.askstring("保存预设", "请输入预设名称:", parent=self)
        if not name:
            return
        if name in self.presets:
            if not messagebox.askyesno("确认覆盖", f"预设 '{name}' 已存在，是否覆盖？"):
                return
        settings = self.template_editor.get_settings()
        settings['output_dir'] = self.output_dir.get()
        settings['name_template'] = self.name_template_var.get()
        settings['duplicate_mode'] = self.duplicate_mode_var.get()
        self.presets[name] = settings
        self.save_settings_and_presets()
        self.load_presets_list()
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
        if 'output_dir' in p:
            self.output_dir.set(os.path.normpath(p['output_dir']))
        self.template_editor.set_settings(p)
        if 'name_template' in p:
            self.name_template_var.set(p['name_template'])
        if 'duplicate_mode' in p:
            self.duplicate_mode_var.set(p['duplicate_mode'])
        messagebox.showinfo("成功", f"预设 '{name}' 已加载")

    def delete_preset(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法删除预设")
            return
        name = self.preset_combo.get()
        if not name:
            messagebox.showwarning("警告", "请先选择一个预设")
            return
        if name not in self.presets:
            messagebox.showerror("错误", f"预设 '{name}' 不存在")
            return
        if messagebox.askyesno("确认删除", f"确定要删除预设 '{name}' 吗？"):
            del self.presets[name]
            self.save_settings_and_presets()
            self.load_presets_list()
            if self.presets:
                self.preset_combo.set(list(self.presets.keys())[0])
            else:
                self.preset_combo.set('')
            messagebox.showinfo("成功", f"预设 '{name}' 已删除")

    # ---------- 多线程转换 ----------
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

        # 检查是否有任务开启了删除原文件
        has_delete = any(task.get('delete_original', False) for task in self.tasks)
        if has_delete:
            delete_count = sum(1 for task in self.tasks if task.get('delete_original', False))
            msg = f"检测到 {delete_count} 个任务开启了“删除原文件”选项。\n\n删除操作会将原文件移至回收站/废纸篓，不可恢复！\n\n是否继续转换？"
            if not messagebox.askyesno("确认删除", msg, icon='warning'):
                return

    
        # 处理输出目录：为空则设为 None（表示使用原目录）
        out_dir_input = self.output_dir.get().strip()
        if out_dir_input == "":
            out_dir = None
        else:
            out_dir = os.path.normpath(out_dir_input)
            os.makedirs(out_dir, exist_ok=True)
    
        dangerous_fixed = False
        for idx, task in enumerate(self.tasks):
            src_dir = os.path.dirname(os.path.normpath(task['path']))
            dup_mode = task.get('duplicate_mode', self.duplicate_mode_var.get())
            # 只有当输出目录非空且等于源目录时才警告
            if out_dir is not None and src_dir == out_dir and dup_mode == "覆盖":
                task['duplicate_mode'] = "自动重命名"
                self.task_listbox.delete(idx)
                self.task_listbox.insert(idx, self.get_task_display_text(task))
                dangerous_fixed = True
    
        if dangerous_fixed:
            messagebox.showwarning("安全提示",
                "检测到有任务的输出目录与源文件目录相同，且原重名处理为“覆盖”。\n"
                "为避免源文件损坏，已自动将这些任务的“重名处理”改为“自动重命名”。\n"
                "请确认任务列表中的变更。")

        # 计算原始文件总大小
        self.total_input_size = 0
        for task in self.tasks:
            if os.path.exists(task['path']):
                self.total_input_size += os.path.getsize(task['path'])
        self.total_output_size = 0

        # 获取 resolved_items: 列表元素为 (task, original_index)
        resolved_items = self.resolve_duplicate_paths(self.tasks, out_dir)
        if not resolved_items:
            messagebox.showinfo("提示", "所有任务均被跳过，没有需要转换的任务")
            return
    
        self.start_btn.config(state=tk.DISABLED)

        self.converting = True
        self.cancel_convert = False          # 重置取消标志
        self.cancel_btn.config(state=tk.NORMAL)  # 启用取消按钮
        self.enable_task_edit_buttons(False)

        self.converting = True
        self.enable_task_edit_buttons(False)
    
        self.total_tasks = len(resolved_items)
        self.progress_bar['maximum'] = self.total_tasks
        self.progress_var.set(0)
        self.progress_label.config(text=f"0 / {self.total_tasks}")
    
        max_workers = self.thread_count_var.get()
        if max_workers < 1:
            max_workers = 1
    
        if self.executor:
            self.executor.shutdown(wait=False)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
    
        self.futures = []
        for task, original_idx in resolved_items:
            future = self.executor.submit(self._convert_single, task, out_dir, original_idx)
            self.futures.append((future, original_idx))
    
        self.processed_indices.clear()
        self.after(100, self._poll_futures)

    def _poll_futures(self):
        # 检查是否取消转换
        if self.cancel_convert:
            # 取消所有未开始的任务
            for future, idx in self.futures:
                future.cancel()
            self.futures.clear()
            self._on_convert_finished()
            return
    
        if not self.futures:
            self._on_convert_finished()
            return

        remaining = []
        for future, original_idx in self.futures:
            if future.done():
                try:
                    idx, success, error, out_size = future.result()
                    self._update_task_item(idx, success, error)
                    if success:
                        with self.size_lock:
                            self.total_output_size += out_size
                    self.progress_var.set(self.progress_var.get() + 1)
                    self.progress_label.config(text=f"{self.progress_var.get()} / {self.total_tasks}")
                except Exception as e:
                    self._update_task_item(original_idx, False, str(e))
            else:
                remaining.append((future, original_idx))
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
        self.cancel_btn.config(state=tk.DISABLED)   # 禁用取消按钮
        self.cancel_convert = False                 # 重置标志
        if self.executor:
            self.executor.shutdown(wait=False)
        success_count = sum(1 for i in range(len(self.tasks)) if " ✓" in self.task_listbox.get(i))
        msg = f"转换完成\n成功: {success_count}\n失败: {len(self.tasks)-success_count}\n输出目录: {self.output_dir.get()}"
        
        # 添加大小统计（仅当有成功转换且输入大小>0）
        if success_count > 0 and self.total_input_size > 0:
            saved_size = self.total_input_size - self.total_output_size
            percent = (saved_size / self.total_input_size) * 100
            msg += f"\n\n原始总大小: {self._format_size(self.total_input_size)}"
            msg += f"\n输出总大小: {self._format_size(self.total_output_size)}"
            msg += f"\n节省空间: {self._format_size(saved_size)} ({percent:.1f}%)"
        else:
            msg += "\n\n(无有效大小统计)"
        
        messagebox.showinfo("完成", msg)
        self.progress_label.config(text="完成")

    def _format_size(self, size):
        """将字节数转换为可读格式 (B/KB/MB/GB)"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"

    def _find_font_file(self, font_name):
        """根据字体名称查找系统字体文件路径（支持中文）"""
        import platform
        system = platform.system()
        
        # 字体名称到文件名的映射表（可扩充）
        font_map = {
            # 英文
            'Arial': 'arial.ttf',
            'Times New Roman': 'times.ttf',
            'Courier New': 'cour.ttf',
            'Verdana': 'verdana.ttf',
            # 中文字体
            'SimHei': 'simhei.ttf',
            'SimSun': 'simsun.ttc',
            'KaiTi': 'simkai.ttf',
            'FangSong': 'simfang.ttf',
            'Microsoft YaHei': 'msyh.ttc',
            '微软雅黑': 'msyh.ttc',
            'Microsoft YaHei UI': 'msyh.ttc',
            '黑体': 'simhei.ttf',
            '宋体': 'simsun.ttc',
            '楷体': 'simkai.ttf',
            '仿宋': 'simfang.ttf',
            '新宋体': 'nsimsun.ttc',
            '隶书': 'lisu.ttf',
            '幼圆': 'youyuan.ttf',
            '华文楷书': 'STKAITI.TTF',
            '华文隶书': 'STLITI.TTF',
            '华文行书': 'STXINGKA.TTF',
        }
        
        filename = font_map.get(font_name)
        if not filename:
            # 若没有映射，则直接使用字体名（小写）加 .ttf
            filename = font_name.lower().replace(' ', '') + '.ttf'
        
        # 系统字体目录
        if system == 'Windows':
            windir = os.environ.get('WINDIR', 'C:/Windows')
            font_dirs = [os.path.join(windir, 'Fonts'), 'C:/Windows/Fonts']
        elif system == 'Darwin':  # macOS
            font_dirs = ['/System/Library/Fonts', '/Library/Fonts']
        else:  # Linux
            font_dirs = ['/usr/share/fonts/truetype', '/usr/local/share/fonts']
        
        for font_dir in font_dirs:
            if not os.path.isdir(font_dir):
                continue
            # 尝试直接匹配
            candidate = os.path.join(font_dir, filename)
            if os.path.exists(candidate):
                return candidate
            # 不区分大小写查找
            for f in os.listdir(font_dir):
                if f.lower() == filename.lower():
                    return os.path.join(font_dir, f)
            # 对于 .ttf 可尝试 .ttc
            if filename.endswith('.ttf'):
                ttc_name = filename[:-4] + '.ttc'
                if os.path.exists(os.path.join(font_dir, ttc_name)):
                    return os.path.join(font_dir, ttc_name)
        return None

    # ---------- 转换单张图片 ----------
    def _convert_single(self, task, out_dir, original_idx):
        # 检查取消标志（如果用户已经取消，直接返回失败）
        if self.cancel_convert:
            return (original_idx, False, "用户取消", 0)
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
        keep_exif = task.get('keep_exif', self.keep_exif_var.get())
        preserve_date = task.get('preserve_original_date', self.preserve_date_var.get())
        delete_original = task.get('delete_original', self.delete_original_var.get())
        brightness_enable = task.get('brightness_enable', False)
        brightness_val = task.get('brightness_val', 0)
        contrast_enable = task.get('contrast_enable', False)
        contrast_val = task.get('contrast_val', 0)
        color_enable = task.get('color_enable', False)
        r_gain = task.get('r_gain', 0)
        g_gain = task.get('g_gain', 0)
        b_gain = task.get('b_gain', 0)
        saturation_enable = task.get('saturation_enable', False)
        saturation_val = task.get('saturation_val', 0)
        sharpen_enable = task.get('sharpen_enable', False)
        sharpen_val = task.get('sharpen_val', 0)
    
        # ---------- 获取输出路径 ----------
        out_path = task.get('out_path')
        if out_path is None:
            name_or_path = self.build_output_name(name_tmpl, src)
            # 获取扩展名
            if fmt == "保持原格式":
                ext = os.path.splitext(src)[1].lower()
            else:
                ext = self._get_output_extension(fmt)
            if "{Original}" in name_tmpl:
                out_path = name_or_path + ext
            else:
                if out_dir is None:
                    out_dir = os.path.dirname(src)
                out_path = os.path.join(out_dir, name_or_path + ext)
            dup_mode = task.get('duplicate_mode', self.duplicate_mode_var.get())
            out_path = self._get_unique_filename(out_path, dup_mode)
    
        # 确保输出目录存在
        out_dir_path = os.path.dirname(out_path)
        if out_dir_path:
            os.makedirs(out_dir_path, exist_ok=True)
    
        src_stat = None
        if preserve_date and os.path.exists(src):
            src_stat = os.stat(src)
    
        try:
            with Image.open(src) as img:
                # 旋转
                if angle != 0:
                    img = img.rotate(angle, expand=True, resample=Image.LANCZOS)
                # 翻转
                if h_flip:
                    img = img.transpose(Image.FLIP_LEFT_RIGHT)
                if v_flip:
                    img = img.transpose(Image.FLIP_TOP_BOTTOM)
                # 缩放
                if mode != "无调整":
                    img = self.apply_resize(img, mode, w, h)
                # 裁剪
                if crop_enabled:
                    w_cur, h_cur = img.size
                    x = self.eval_crop_expr(crop_x, w_cur, h_cur)
                    y = self.eval_crop_expr(crop_y, w_cur, h_cur)
                    w_crop = self.eval_crop_expr(crop_w, w_cur, h_cur)
                    h_crop = self.eval_crop_expr(crop_h, w_cur, h_cur)
                    x = max(0, min(x, w_cur - 1))
                    y = max(0, min(y, h_cur - 1))
                    w_crop = min(w_crop, w_cur - x)
                    h_crop = min(h_crop, h_cur - y)
                    if w_crop > 0 and h_crop > 0:
                        img = img.crop((x, y, x + w_crop, y + h_crop))
                # 亮度
                if brightness_enable and brightness_val != 0:
                    enhancer = ImageEnhance.Brightness(img)
                    factor = 1 + brightness_val / 100.0
                    img = enhancer.enhance(factor)
                # 对比度
                if contrast_enable and contrast_val != 0:
                    enhancer = ImageEnhance.Contrast(img)
                    factor = 1 + contrast_val / 100.0
                    img = enhancer.enhance(factor)
                # 饱和度
                if saturation_enable and saturation_val != 0:
                    enhancer = ImageEnhance.Color(img)
                    factor = 1 + saturation_val / 100.0
                    img = enhancer.enhance(factor)
                # RGB 调整
                if color_enable:
                    r_factor = (r_gain + 100) / 100.0
                    g_factor = (g_gain + 100) / 100.0
                    b_factor = (b_gain + 100) / 100.0
                    if r_factor != 1 or g_factor != 1 or b_factor != 1:
                        has_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
                        if has_alpha and img.mode != 'RGBA':
                            img = img.convert('RGBA')
                        if has_alpha:
                            r, g, b, a = img.split()
                            r = r.point(lambda i: i * r_factor)
                            g = g.point(lambda i: i * g_factor)
                            b = b.point(lambda i: i * b_factor)
                            img = Image.merge('RGBA', (r, g, b, a))
                        else:
                            r, g, b = img.split()
                            r = r.point(lambda i: i * r_factor)
                            g = g.point(lambda i: i * g_factor)
                            b = b.point(lambda i: i * b_factor)
                            img = Image.merge('RGB', (r, g, b))
                # 锐化
                if sharpen_enable and sharpen_val != 0:
                    enhancer = ImageEnhance.Sharpness(img)
                    factor = 1 + sharpen_val / 100.0
                    img = enhancer.enhance(factor)
    
                # ---------- 文字水印 ----------
                watermark_settings = {
                    'enable': task.get('watermark_enable', False),
                    'text': task.get('watermark_text', ''),
                    'font': task.get('watermark_font', 'Arial'),
                    'size': task.get('watermark_size', 36),
                    'position': task.get('watermark_position', '右下'),
                    'opacity': task.get('watermark_opacity', 80),
                    'color': task.get('watermark_color', '#FFFFFF'),
                }
                img = self.draw_watermark(img, watermark_settings)
    
                # ---------- 保存前的格式转换和参数准备 ----------
                # 确定实际保存格式名
                if fmt == "保持原格式":
                    actual_fmt = os.path.splitext(src)[1].lower().lstrip('.')
                    actual_fmt = actual_fmt.upper()
                    if actual_fmt not in FORMAT_CONFIG:
                        actual_fmt = 'JPEG'
                    original_path_for_config = src
                else:
                    actual_fmt = fmt
                    original_path_for_config = None
    
                # 准备保存参数
                save_params = self._prepare_save_params(fmt, qual, original_path_for_config)
    
                # 处理图像模式转换（如 RGBA -> RGB）
                target_mode = self._get_output_mode(img, fmt, original_path_for_config)
                if target_mode:
                    img = img.convert(target_mode)
    
                # 处理 EXIF
                exif = None
                if keep_exif and hasattr(img, 'info') and 'exif' in img.info:
                    exif = img.info['exif']
                    # 获取实际格式的配置（如果是“保持原格式”，需要先获取 actual_fmt 对应的配置）
                    config = FORMAT_CONFIG.get(actual_fmt)
                    if config and config.get('supports_exif', False):
                        save_params['exif'] = exif
    
                # 保存图片
                img.save(out_path, actual_fmt, **save_params)
    
            # 保留原始日期
            if preserve_date and src_stat is not None:
                if platform.system() == 'Windows':
                    ctime = os.path.getctime(src)
                    try:
                        self.set_file_times(out_path, ctime, src_stat.st_atime, src_stat.st_mtime)
                    except Exception as e:
                        print(f"设置文件时间戳失败: {e}")
                else:
                    os.utime(out_path, (src_stat.st_atime, src_stat.st_mtime))
    
            # 删除原文件
            if delete_original and os.path.exists(src):
                try:
                    send_to_trash(src)
                except Exception as e:
                    raise Exception(f"删除原文件失败: {e}")
    
            # 获取输出文件大小
            out_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
            return (original_idx, True, None, out_size)
    
        except Exception as e:
            return (original_idx, False, str(e), 0)



    def _get_unique_filename(self, base_path, dup_mode):
        if dup_mode == "覆盖":
            return base_path
        with self.rename_lock:
            dir_name = os.path.dirname(base_path)
            base_name = os.path.basename(base_path)
            name, ext = os.path.splitext(base_name)
            candidate = base_path
            counter = 1
            while os.path.exists(candidate):
                candidate = os.path.join(dir_name, f"{name}_{counter}{ext}")
                counter += 1
            return candidate

if __name__ == "__main__":
    app = ImageConverter()
    app.mainloop()
