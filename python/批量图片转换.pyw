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
    for ext, format in Image.registered_extensions().items():
        if format:
            exts.add(ext.lower())
    additional = {
        '.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif',
        '.gif', '.ico', '.ppm', '.pgm', '.pbm', '.xbm', '.pcx', '.tga',
        '.jp2', '.j2k', '.jpx', '.jpf'
    }
    exts.update(additional)
    return exts

SUPPORTED_IMG_EXTS = get_supported_extensions()

FORMAT_CONFIG = {
    'JPEG': {
        'extension': '.jpg',
        'save_params': {'quality': 'quality', 'optimize': True},
        'quality_range': (1, 100),
        'default_quality': 85,
        'mode': 'RGB',
        'supports_exif': True,
    },
    'PNG': {
        'extension': '.png',
        'save_params': {'compress_level': 'compress_level'},
        'quality_range': (0, 9),
        'default_quality': 6,
        'mode': None,
        'supports_exif': False,
    },
    'WEBP': {
        'extension': '.webp',
        'save_params': {'quality': 'quality', 'lossless': False},
        'quality_range': (1, 100),
        'default_quality': 80,
        'mode': 'RGB',
        'supports_exif': True,
    },
    'BMP': {
        'extension': '.bmp',
        'save_params': {},
        'quality_range': None,
        'default_quality': None,
        'mode': 'RGB',
        'supports_exif': False,
    },
    'ICO': {
        'extension': '.ico',
        'save_params': {'sizes': [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]},  # 默认多尺寸
        'quality_range': None,   # ICO无质量参数
        'default_quality': None,
        'mode': 'RGBA',          # ICO支持透明
        'supports_exif': False,
    }
}

def center_window(parent, child):
    """
    将子窗口（Toplevel）居中显示在父窗口（任意 widget）之上。
    自动处理屏幕边界，避免超出可视区域。
    """
    parent = parent.winfo_toplevel()   # 获取顶层窗口（Tk 或 Toplevel）
    parent.update_idletasks()          # 确保尺寸/位置最新
    child.update_idletasks()
    
    screen_w = parent.winfo_screenwidth()
    screen_h = parent.winfo_screenheight()
    
    x = parent.winfo_x() + (parent.winfo_width() - child.winfo_width()) // 2
    y = parent.winfo_y() + (parent.winfo_height() - child.winfo_height()) // 2
    
    # 限制不能超出屏幕
    x = max(0, min(x, screen_w - child.winfo_width()))
    y = max(0, min(y, screen_h - child.winfo_height()))
    
    child.geometry(f"+{x}+{y}")


def send_to_trash(path):
    """跨平台地将文件或文件夹移动到回收站/废纸篓。"""
    if platform.system() == 'Windows':
        try:
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
            FO_DELETE = 0x0003
            FOF_ALLOWUNDO = 0x0040
            FOF_NOCONFIRMATION = 0x0010
            FOF_SILENT = 0x0004
            file_op = SHFILEOPSTRUCTW()
            file_op.wFunc = FO_DELETE
            file_op.pFrom = path + '\0\0'
            file_op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
            file_op.hwnd = 0
            result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(file_op))
            if result != 0:
                raise OSError(f"SHFileOperationW failed with error code: {result}")
        except Exception as e:
            raise OSError(f"Failed to move '{path}' to Recycle Bin: {e}")
    elif platform.system() == 'Darwin':
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
        try:
            subprocess.run(['gio', 'trash', path], check=True, capture_output=True, text=True)
        except FileNotFoundError:
            try:
                subprocess.run(['kioclient5', 'move', path, 'trash:/'], check=True, capture_output=True, text=True)
            except FileNotFoundError:
                try:
                    subprocess.run(['trash-put', path], check=True, capture_output=True, text=True)
                except FileNotFoundError:
                    raise OSError("No supported trash CLI tool found (gio, kioclient5, or trash-put). Please install one.")
        except subprocess.CalledProcessError as e:
            raise OSError(f"Failed to move '{path}' to Trash: {e.stderr.strip()}")
        except Exception as e:
            raise OSError(f"Failed to move '{path}' to Trash: {e}")

def get_preset_file_path():
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "picpresets.json")



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



class TemplateEditor(ttk.Frame):
    """可复用的参数编辑组件（不含名称模板、重名处理等界面级选项）"""
    def __init__(self, parent, include_exif_date_delete=True, default_expanded=False, **kwargs):
        super().__init__(parent, **kwargs)
        self.include_exif_date_delete = include_exif_date_delete
        self.default_expanded = default_expanded
        self.preview_callback = None
        self.visual_crop_callback = None
        self._create_widgets()
        self._setup_traces()
        self._ico_sizes = [(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)]
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
                                    values=["保持原格式", "JPEG", "PNG", "WEBP", "BMP", "ICO"],
                                    state="readonly", width=10)
        format_combo.pack(side=tk.LEFT, padx=2)

        # ----- 原质量控件代码替换为以下内容 -----
        self.quality_frame = ttk.Frame(row1)
        self.quality_frame.pack(side=tk.LEFT, padx=2)   # 放在 row1 中
        
        self.quality_label = ttk.Label(self.quality_frame, text="质量:")
        self.quality_label.pack(side=tk.LEFT, padx=(10,2))
        
        self.quality_var = tk.IntVar(value=85)   # 原有，无需改动
        self.quality_scale = ttk.Scale(self.quality_frame, from_=1, to=100, variable=self.quality_var,
                                       orient=tk.HORIZONTAL, length=80)
        self.quality_scale.pack(side=tk.LEFT, padx=2)
        
        self.quality_spin = ttk.Spinbox(self.quality_frame, from_=1, to=100, textvariable=self.quality_var,
                                        width=5, state='normal')
        self.quality_spin.pack(side=tk.LEFT, padx=2)
        
        # ICO 尺寸按钮（默认隐藏）
        self.ico_size_btn = ttk.Button(self.quality_frame, text="设置 ICO 尺寸", command=self._edit_ico_sizes)
        self.ico_size_btn.pack_forget()   # 初始不显示

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
            self.keep_exif_checkbtn = ttk.Checkbutton(row2, text="保留EXIF", variable=self.keep_exif_var)
            self.keep_exif_checkbtn.pack(side=tk.LEFT, padx=(20, 5))
            ToolTip(self.keep_exif_checkbtn,
                    text="保留EXIF元数据，仅对 JPEG、WebP 等格式有效。\n\n（PNG、BMP、ICO 不支持）",
                    wraplength=400)

            self.preserve_date_var = tk.BooleanVar(value=False)
            self.preserve_date_checkbtn = ttk.Checkbutton(row2, text="维持原始日期", variable=self.preserve_date_var)
            self.preserve_date_checkbtn.pack(side=tk.LEFT, padx=5)
            ToolTip(self.preserve_date_checkbtn,
                    text="保持输出文件的创建时间和修改时间与原文件一致。",
                    wraplength=400)
            
            self.delete_original_var = tk.BooleanVar(value=False)
            self.delete_original_checkbtn = ttk.Checkbutton(row2, text="删除原文件", variable=self.delete_original_var)
            self.delete_original_checkbtn.pack(side=tk.LEFT, padx=5)
            ToolTip(self.delete_original_checkbtn,
                    text="转换后原文件将被移至回收站/废纸篓！\n\n请确保输出目录与源文件不同，避免覆盖。",
                    wraplength=450)

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
        self.visual_crop_btn = ttk.Button(row3, text="可视化", width=6, command=self.on_visual_crop)
        self.visual_crop_btn.pack(side=tk.LEFT, padx=5)

        # 预览尺寸控制
        ttk.Label(row3, text="预览尺寸:").pack(side=tk.LEFT, padx=(10,2))
        self.preview_size_var = tk.IntVar(value=600)
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
                                          orient=tk.HORIZONTAL, length=90, state=tk.DISABLED)
        self.brightness_scale.pack(side=tk.LEFT, padx=5)
        self.brightness_label = ttk.Label(bc_row, text="0", width=4)
        self.brightness_label.pack(side=tk.LEFT)

        ttk.Label(bc_row, text="  ").pack(side=tk.LEFT)
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


        self.format_var.trace_add('write', self._on_format_changed)


    def _on_format_changed(self, *args):
        fmt = self.format_var.get()
        if fmt == "ICO":
            # 隐藏质量控件
            self.quality_label.pack_forget()
            self.quality_scale.pack_forget()
            self.quality_spin.pack_forget()
            # 显示按钮（按钮在质量控件之后，所以 pack 会排在最后，但因为我们隐藏了前面的，按钮会占据整个容器位置，顺序正确）
            self.ico_size_btn.pack(side=tk.LEFT, padx=2)
        else:
            # 隐藏按钮
            self.ico_size_btn.pack_forget()
            # 按原顺序重新显示质量控件
            self.quality_label.pack(side=tk.LEFT, padx=(10,2))
            self.quality_scale.pack(side=tk.LEFT, padx=2)
            self.quality_spin.pack(side=tk.LEFT, padx=2)
        self._on_settings_changed()

    def _edit_ico_sizes(self):
        """弹出独立对话框编辑 ICO 尺寸列表"""
        dlg = Toplevel(self)
        dlg.title("编辑 ICO 尺寸")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("300x250")
        center_window(self, dlg)   # 居中
    
        # 当前尺寸列表副本
        current_sizes = self._ico_sizes.copy()
    
        # Listbox 显示尺寸
        list_frame = ttk.Frame(dlg)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=8)
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.configure(yscrollcommand=scroll.set)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
    
        def refresh_list():
            listbox.delete(0, tk.END)
            for w, h in current_sizes:
                listbox.insert(tk.END, f"{w}x{h}")
    
        refresh_list()
    
        # 按钮区域
        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
    
        def add_size():
            from tkinter import simpledialog
            s = simpledialog.askstring("添加尺寸", "输入宽x高，如 16x16", parent=dlg)
            if not s:
                return
            try:
                w, h = map(int, s.split('x'))
                if w <= 0 or h <= 0:
                    raise ValueError
                current_sizes.append((w, h))
                refresh_list()
            except:
                messagebox.showerror("错误", "无效格式，请输入 宽x高")
    
        def remove_selected():
            selected = listbox.curselection()
            if not selected:
                messagebox.showinfo("提示", "请先选择要删除的尺寸")
                return
            for idx in reversed(selected):
                del current_sizes[idx]
            refresh_list()
    
        def restore_default():
            default = [(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)]
            current_sizes.clear()
            current_sizes.extend(default)
            refresh_list()
    
        def save_and_close():
            self._ico_sizes = current_sizes.copy()
            self._on_settings_changed()
            dlg.destroy()
    
        ttk.Button(btn_frame, text="添加", command=add_size, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="删除", command=remove_selected, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="复原默认", command=restore_default, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="保存", command=save_and_close, width=8).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="取消", command=dlg.destroy, width=8).pack(side=tk.RIGHT, padx=2)


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

    def set_visual_crop_callback(self, callback):
        """设置可视化裁剪的回调函数"""
        self.visual_crop_callback = callback
    
    def on_visual_crop(self):
        """点击可视化按钮时触发，调用外部回调"""
        if hasattr(self, 'visual_crop_callback') and self.visual_crop_callback:
            self.visual_crop_callback()
        else:
            messagebox.showinfo("提示", "可视化裁剪功能未就绪")

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
            'ico_sizes': self._ico_sizes.copy(),
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
        
        self.preview_size_var.set(settings.get('preview_size', 600))


        # 颜色加载
        self.watermark_color_var.set(settings.get('watermark_color', '#FFFFFF'))
        if hasattr(self, 'color_preview'):
            self.color_preview.config(bg=self.watermark_color_var.get())


        if self.include_exif_date_delete:
            self.keep_exif_var.set(settings.get('keep_exif', False))
            self.preserve_date_var.set(settings.get('preserve_original_date', False))
            self.delete_original_var.set(settings.get('delete_original', False))


        ico_sizes = settings.get('ico_sizes')
        if ico_sizes and isinstance(ico_sizes, list):
            self._ico_sizes = [tuple(s) for s in ico_sizes if isinstance(s, (tuple, list)) and len(s)==2]
        # 确保格式变化触发显示切换（在 set_settings 最后调用 _on_format_changed）
        self._on_format_changed()  # 强制更新显示状态
        
        self._on_resize_mode_changed()
        self._update_enhance_enable()
        self._on_settings_changed()


class ImageConverter(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        if DND_AVAILABLE:
            self.title("图片批量转换 Lite (支持拖拽)")
        else:
            self.title("图片批量转换 Lite (拖拽不可用，请使用按钮)")
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.preset_file = os.path.join(base_dir, "picpresets.json")

        self.load_settings_and_presets()

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
        self.cancel_convert = False
        self.executor = None
        self.futures = []
        self.total_tasks = 0
        self.rename_lock = threading.Lock()
        self.preview_window = None
        self.preview_canvas = None
        self.preview_status = None
        self._preview_after_id = None
        self.total_input_size = 0
        self.total_output_size = 0
        self.size_lock = threading.Lock()
        self.global_preview_size = 600
        self.font_cache = {}
        self.font_path_cache = {}
        self.visual_crop_callback = None   # 外部设置的回调函数
        self.current_preview_task = None   # 当前显示的预览任务
        self.active_crop_editor = None

        self.initial_files = []
        if len(sys.argv) > 1:
            for arg in sys.argv[1:]:
                arg = arg.strip('"')
                if os.path.exists(arg):
                    self.initial_files.append(arg)

        self.create_widgets()
        self.load_presets_list()
        self.save_current_state_to_history()
        if self.initial_files:
            self.after(100, self._add_initial_files)

        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="编辑当前任务", command=self.edit_selected_task)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="移除当前任务", command=self.remove_selected)

        self.bind_all("<Button-1>", self.on_click_outside, add=True)
        self.bind("<Configure>", lambda e: self._position_preview_window())

        if DND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.on_drop)
        else:
            messagebox.showwarning("提示", "未安装 tkinterdnd2 库，拖拽添加功能不可用。\n可使用按钮添加图片或文件夹。")

        self.processed_indices = set()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ==================== 公共函数 ====================
    def _apply_all_transforms(self, img, settings):
        angle = int(settings['rotation'].rstrip('°'))
        if angle != 0:
            img = img.rotate(angle, expand=True, resample=Image.LANCZOS)
        if settings['h_flip']:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if settings['v_flip']:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)

        if settings.get('crop_enabled', False):
            w_cur, h_cur = img.size
            x = self.eval_crop_expr(settings['crop_x'], w_cur, h_cur)
            y = self.eval_crop_expr(settings['crop_y'], w_cur, h_cur)
            w = self.eval_crop_expr(settings['crop_w'], w_cur, h_cur)
            h = self.eval_crop_expr(settings['crop_h'], w_cur, h_cur)
            x = max(0, min(x, w_cur-1))
            y = max(0, min(y, h_cur-1))
            w = min(w, w_cur - x)
            h = min(h, h_cur - y)
            if w > 0 and h > 0:
                img = img.crop((x, y, x+w, y+h))
        if settings['resize_mode'] != "无调整":
            img = self.apply_resize(img, settings['resize_mode'], settings['resize_w'], settings['resize_h'], resample=Image.LANCZOS)
        if settings.get('brightness_enable', False) and settings.get('brightness_val', 0) != 0:
            enhancer = ImageEnhance.Brightness(img)
            factor = 1 + settings['brightness_val'] / 100.0
            img = enhancer.enhance(factor)
        if settings.get('contrast_enable', False) and settings.get('contrast_val', 0) != 0:
            enhancer = ImageEnhance.Contrast(img)
            factor = 1 + settings['contrast_val'] / 100.0
            img = enhancer.enhance(factor)
        if settings.get('saturation_enable', False) and settings.get('saturation_val', 0) != 0:
            enhancer = ImageEnhance.Color(img)
            factor = 1 + settings['saturation_val'] / 100.0
            img = enhancer.enhance(factor)
        if settings.get('color_enable', False):
            r_factor = (settings.get('r_gain', 0) + 100) / 100.0
            g_factor = (settings.get('g_gain', 0) + 100) / 100.0
            b_factor = (settings.get('b_gain', 0) + 100) / 100.0
            if r_factor != 1 or g_factor != 1 or b_factor != 1:
                if img.mode == 'RGBA':
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
        if settings.get('sharpen_enable', False) and settings.get('sharpen_val', 0) != 0:
            enhancer = ImageEnhance.Sharpness(img)
            factor = 1 + settings['sharpen_val'] / 100.0
            img = enhancer.enhance(factor)
        watermark_settings = {
            'enable': settings.get('watermark_enable', False),
            'text': settings.get('watermark_text', ''),
            'font': settings.get('watermark_font', 'Arial'),
            'size': settings.get('watermark_size', 36),
            'position': settings.get('watermark_position', '右下'),
            'opacity': settings.get('watermark_opacity', 80),
            'color': settings.get('watermark_color', '#FFFFFF'),
        }
        img = self.draw_watermark(img, watermark_settings)
        return img

    def _apply_all_transforms_up_to_crop(self, img, settings):
        """只应用到裁剪之前的所有变换（旋转 + 翻转）"""
        angle = int(settings['rotation'].rstrip('°'))
        if angle != 0:
            img = img.rotate(angle, expand=True, resample=Image.LANCZOS)
    
        if settings['h_flip']:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if settings['v_flip']:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
    
        return img


    def set_visual_crop_callback(self, callback):
        """设置可视化裁剪的回调函数，回调接收 (x, y, w, h) 四个整数参数"""
        self.visual_crop_callback = callback
    
    def on_visual_crop(self):
        """点击可视化按钮时触发，调用外部回调"""
        if self.visual_crop_callback:
            # 获取当前图片路径（需要从外部获取，可以通过回调参数传递）
            # 这里简单传递，实际需要 ImageConverter 提供当前预览任务的路径
            # 我们将在 ImageConverter 中实现具体逻辑，因此只调用回调，参数由外部决定
            self.visual_crop_callback()
        else:
            messagebox.showinfo("提示", "可视化裁剪功能未就绪")


    def visual_crop_mode(self, task=None, on_finish=None):
        """
        启用可视化裁剪模式（支持在已有裁剪基础上追加裁剪）
        """
        if task is None:
            task = self.current_preview_task
        if not task:
            messagebox.showwarning("警告", "没有当前预览的图片")
            if on_finish:
                on_finish()
            return
    
        editor = self.active_crop_editor if self.active_crop_editor is not None else self.template_editor
    
        # ========== 1. 获取当前裁剪参数作为基准偏移 ==========
        settings = editor.get_settings()
        # 先获取旋转翻转后的完整图像尺寸（用于计算绝对坐标边界）
        try:
            with Image.open(task['path']) as orig_img:
                rotated_img = self._apply_all_transforms_up_to_crop(orig_img, settings)
                full_w, full_h = rotated_img.size
        except Exception as e:
            messagebox.showerror("错误", f"无法处理图像: {e}")
            if on_finish:
                on_finish()
            return
    
        # 计算当前基准裁剪区域（相对于旋转翻转后的完整图像）
        crop_enabled = settings.get('crop_enabled', False)
        if crop_enabled:
            base_x = self.eval_crop_expr(settings['crop_x'], full_w, full_h)
            base_y = self.eval_crop_expr(settings['crop_y'], full_w, full_h)
            base_w = self.eval_crop_expr(settings['crop_w'], full_w, full_h)
            base_h = self.eval_crop_expr(settings['crop_h'], full_w, full_h)
            # 边界保护
            base_x = max(0, min(base_x, full_w - 1))
            base_y = max(0, min(base_y, full_h - 1))
            base_w = min(base_w, full_w - base_x)
            base_h = min(base_h, full_h - base_y)
        else:
            base_x = base_y = 0
            base_w, base_h = full_w, full_h
    
        # ========== 2. 预览裁剪后的图像（基准区域） ==========
        preview_settings = settings.copy()
        preview_settings['crop_enabled'] = True
        preview_settings['crop_x'] = str(base_x)
        preview_settings['crop_y'] = str(base_y)
        preview_settings['crop_w'] = str(base_w)
        preview_settings['crop_h'] = str(base_h)
    
        if not self.preview_window or not self.preview_window.winfo_exists():
            self._show_preview(task)
        self._update_preview_content(task, override_settings=preview_settings, sync=True)
    
        canvas = self.preview_canvas
        if not canvas:
            messagebox.showerror("错误", "预览画布不存在")
            if on_finish:
                on_finish()
            return
    
        # 获取画布上的图像对象
        image_obj = None
        for item in canvas.find_all():
            if canvas.type(item) == "image":
                image_obj = item
                break
        if not image_obj:
            messagebox.showwarning("警告", "未找到预览图片")
            if on_finish:
                on_finish()
            return
    
        bbox = canvas.bbox(image_obj)
        if not bbox:
            messagebox.showerror("错误", "无法获取图片位置")
            if on_finish:
                on_finish()
            return
        img_x1, img_y1, img_x2, img_y2 = bbox
        display_w = img_x2 - img_x1
        display_h = img_y2 - img_y1
    
        # 比例尺：当前显示的是基准区域（base_w x base_h）
        scale_x = base_w / display_w if display_w > 0 else 1
        scale_y = base_h / display_h if display_h > 0 else 1
    
        # ========== 3. 交互绘制（与之前相同，但坐标转换有偏移） ==========
     #   old_cursor = canvas.cget("cursor")
    #    canvas.config(cursor="crosshair")
    
        canvas.delete("crop_hint")
        hint_text = canvas.create_text(
            canvas.winfo_width()//2, canvas.winfo_height()//2 - 30,
            text="🖱 拖拽绘制裁剪区域\nShift: 保持正方形\n取消勾选可重置预览",
            font=("", 14, "bold"), fill="black", tags="crop_hint"
        )
        hint_bbox = canvas.bbox(hint_text)
        if hint_bbox:
            canvas.create_rectangle(
                hint_bbox[0]-20, hint_bbox[1]-15, hint_bbox[2]+20, hint_bbox[3]+15,
                fill="white", outline="gray", width=1, tags="crop_hint"
            )
            canvas.tag_raise(hint_text)
    
        self.rect_id = None
        self.start_x = self.start_y = None
    
        def on_mouse_down(event):
            cx = canvas.canvasx(event.x)
            cy = canvas.canvasy(event.y)
            if img_x1 <= cx <= img_x2 and img_y1 <= cy <= img_y2:
                self.start_x, self.start_y = cx, cy
                canvas.delete("crop_hint")
                if self.rect_id:
                    canvas.delete(self.rect_id)
                    self.rect_id = None
    
        def on_mouse_move(event):
            if self.start_x is None:
                return
            cx = max(img_x1, min(canvas.canvasx(event.x), img_x2))
            cy = max(img_y1, min(canvas.canvasy(event.y), img_y2))
    
            shift = bool(event.state & 0x0001)
            end_x, end_y = cx, cy
            if shift:
                dx = cx - self.start_x
                dy = cy - self.start_y
                size = max(abs(dx), abs(dy))
                end_x = self.start_x + (size if dx >= 0 else -size)
                end_y = self.start_y + (size if dy >= 0 else -size)
                end_x = max(img_x1, min(end_x, img_x2))
                end_y = max(img_y1, min(end_y, img_y2))
    
            if self.rect_id:
                canvas.coords(self.rect_id, self.start_x, self.start_y, end_x, end_y)
            else:
                self.rect_id = canvas.create_rectangle(
                    self.start_x, self.start_y, end_x, end_y,
                    outline='red', width=2, dash=(4, 2)
                )
    
        def on_mouse_up(event):
            if self.start_x is None:
                _cleanup()
                return
    
            cx = max(img_x1, min(canvas.canvasx(event.x), img_x2))
            cy = max(img_y1, min(canvas.canvasy(event.y), img_y2))
    
            shift = bool(event.state & 0x0001)
            end_x, end_y = cx, cy
            if shift:
                dx = cx - self.start_x
                dy = cy - self.start_y
                size = max(abs(dx), abs(dy))
                end_x = self.start_x + (size if dx >= 0 else -size)
                end_y = self.start_y + (size if dy >= 0 else -size)
                end_x = max(img_x1, min(end_x, img_x2))
                end_y = max(img_y1, min(end_y, img_y2))
    
            x1 = min(self.start_x, end_x)
            y1 = min(self.start_y, end_y)
            x2 = max(self.start_x, end_x)
            y2 = max(self.start_y, end_y)
    
            # 相对坐标（相对于当前基准区域）
            rel_x = int((x1 - img_x1) * scale_x)
            rel_y = int((y1 - img_y1) * scale_y)
            rel_w = int((x2 - x1) * scale_x)
            rel_h = int((y2 - y1) * scale_y)
    
            # 转换为绝对坐标（相对于旋转翻转后的完整图像）
            final_x = base_x + rel_x
            final_y = base_y + rel_y
            final_w = rel_w
            final_h = rel_h
    
            # 边界限制（不能超出完整图像）
            final_x = max(0, min(final_x, full_w - 1))
            final_y = max(0, min(final_y, full_h - 1))
            final_w = max(1, min(final_w, full_w - final_x))
            final_h = max(1, min(final_h, full_h - final_y))
    
            # 回写编辑器（绝对坐标）
            editor.crop_x_var.set(str(final_x))
            editor.crop_y_var.set(str(final_y))
            editor.crop_w_var.set(str(final_w))
            editor.crop_h_var.set(str(final_h))
            editor.crop_enabled_var.set(True)
    
            _cleanup()
    
            # 刷新预览（应用新裁剪）
            self._update_preview_content(task, override_settings=editor.get_settings(), sync=True)
            if on_finish:
                on_finish()
    
        def _cleanup():
            canvas.unbind("<ButtonPress-1>")
            canvas.unbind("<B1-Motion>")
            canvas.unbind("<ButtonRelease-1>")
            if self.rect_id:
                canvas.delete(self.rect_id)
                self.rect_id = None
            self.start_x = self.start_y = None
            canvas.delete("crop_hint")
        #    canvas.config(cursor=old_cursor)
    
        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_move)
        canvas.bind("<ButtonRelease-1>", on_mouse_up)


    def _build_output_path(self, task, out_dir):
        # 优先使用任务自身的输出目录
        task_out_dir = task.get('output_dir')
        if task_out_dir and task_out_dir.strip():
            out_dir = task_out_dir.strip()
        name_or_path = self.build_output_name(task['name_template'], task['path'])
        fmt = task['format']
        if fmt == "保持原格式":
            ext = os.path.splitext(task['path'])[1].lower()
        else:
            ext = self._get_output_extension(fmt)
        if "{Original}" in task['name_template']:
            base_path = name_or_path + ext
        else:
            if out_dir is None:
                out_dir = os.path.dirname(task['path'])
            base_path = os.path.join(out_dir, name_or_path + ext)
        dup_mode = task.get('duplicate_mode', self.duplicate_mode_var.get())
        return self._get_unique_filename(base_path, dup_mode)

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

    def _get_format_config(self, fmt):
        if fmt == "保持原格式":
            return None
        return FORMAT_CONFIG.get(fmt)

    def _get_output_extension(self, fmt, original_path=None):
        if fmt == "保持原格式" and original_path:
            ext = os.path.splitext(original_path)[1].lower()
            return ext
        config = self._get_format_config(fmt)
        if config:
            return config['extension']
        return '.jpg'

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
            self.current_preview_task = task
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
            self.current_preview_task = task

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

    def _update_preview_content(self, task, override_settings=None, sync=False):
        """生成预览，可传入 override_settings 覆盖任务参数；sync=True 时同步执行"""
        if self.preview_window is None or not self.preview_window.winfo_exists():
            return
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
            try:
                # 若提供了覆盖参数，则合并到任务副本中
                if override_settings:
                    temp_task = task.copy()
                    temp_task.update(override_settings)
                    img_task = temp_task
                else:
                    img_task = task
    
                with Image.open(img_task['path']) as img:
                    img = self._apply_all_transforms(img, img_task)
                    preview_size = self.global_preview_size
                    img.thumbnail((preview_size, preview_size), Image.NEAREST)
                    thumb_w, thumb_h = img.size
                    win_w = thumb_w + 20
                    win_h = thumb_h + 70
                    self.preview_window.geometry(f"{win_w}x{win_h}")
                    self.preview_canvas.config(width=thumb_w, height=thumb_h)
                    photo = ImageTk.PhotoImage(img)
                    self.preview_canvas.delete("all")
                    self.preview_canvas.create_image(thumb_w//2, thumb_h//2, image=photo, anchor=tk.CENTER)
                    self.preview_canvas.image = photo
                    self.preview_canvas.update_idletasks()
                    if self.preview_status:
                        self.preview_status.config(text=f"预览完成 | 缩略图尺寸: {thumb_w}x{thumb_h}")
            except Exception as e:
                if self.preview_status:
                    self.preview_status.config(text=f"预览失败: {str(e)}")
                if self.preview_canvas:
                    self.preview_canvas.delete("all")
                    self.preview_canvas.create_text(10, 10, anchor=tk.NW, text=f"错误: {e}", fill="red")
    
        if sync:
            generate()
        else:
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

    def resolve_duplicate_paths(self, tasks, out_dir):
        # 修改后使用 _build_output_path
        resolved_items = []
        duplicate_mode = self.duplicate_mode_var.get()
        if duplicate_mode in ("覆盖", "自动重命名"):
            for idx, task in enumerate(tasks):
                task_copy = task.copy()
                task_copy['out_path'] = None
                resolved_items.append((task_copy, idx))
            return resolved_items
        if duplicate_mode == "跳过":
            for idx, task in enumerate(tasks):
                base_out = self._build_output_path(task, out_dir)
                if os.path.exists(base_out):
                    continue
                task_copy = task.copy()
                task_copy['out_path'] = base_out
                resolved_items.append((task_copy, idx))
            return resolved_items
        if duplicate_mode == "询问":
            conflicts = []
            for idx, task in enumerate(tasks):
                base_out = self._build_output_path(task, out_dir)
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
        center_window(self, dlg)
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
        self.template_container = ttk.LabelFrame(left_frame, text="当前模板（新任务将使用此设置）- 处理顺序: 旋转→翻转→裁剪→缩放→更多")
        self.template_container.pack(fill=tk.X, pady=5)

        # 图像参数编辑器
        self.template_editor = TemplateEditor(self.template_container, include_exif_date_delete=True, default_expanded=False)
        self.template_editor.pack(fill=tk.X, padx=5, pady=5)
        self.template_editor.bind_preview_callback(self.update_template_preview)
        def main_window_visual_crop():
            # 主窗口点击可视化前强制清空可能残留的弹窗编辑器引用
            self.active_crop_editor = None
            self.visual_crop_mode()
        self.template_editor.set_visual_crop_callback(main_window_visual_crop)

        self.keep_exif_var = self.template_editor.keep_exif_var
        ToolTip(self.template_editor.visual_crop_btn,
            text="当前裁剪预览只供参考，裁剪数据作为模板应用到后续添加文件中。\n\n调整已有任务请使用右键编辑里的可视化。",
            wraplength=550)

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
        self.duplicate_mode_var = tk.StringVar(value="自动重命名")
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
        self.task_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=10)
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
        current.pop('preview_size', None)   # 安全删除
        current['name_template'] = self.name_template_var.get()
        current['duplicate_mode'] = self.duplicate_mode_var.get()
        # 获取当前全局输出目录，并存入每个任务
        global_dir = self.output_dir.get().strip()
        if not global_dir or global_dir == '.':
            current['output_dir'] = None
        else:
            current['output_dir'] = os.path.normpath(global_dir)
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
        dlg.geometry("800x500")
        center_window(self, dlg)   # 直接调用
        dlg.deiconify()
        dlg.lift()
        dlg.focus_force()
    
        # 左侧面板：仅水平填充，不垂直扩展（让内部控件决定高度）
        left_panel = ttk.Frame(dlg)
        left_panel.pack(fill=tk.X, padx=5, pady=0)
    
        # 编辑器（初始展开更多调整）
        editor = TemplateEditor(left_panel, include_exif_date_delete=True, default_expanded=True)
        editor.pack(fill=tk.X, pady=0)
        editor.set_settings(task)
        editor.preview_size_var.set(self.global_preview_size)
        current_edit_task = task.copy()

        def on_dlg_close():
            self.active_crop_editor = None
            dlg.destroy()
        
        dlg.protocol("WM_DELETE_WINDOW", on_dlg_close)

        # ========== 为编辑对话框中的可视化按钮设置回调（仅释放/重获焦点） ==========
        def start_visual_crop_with_release():
            dlg.grab_release()
            self.active_crop_editor = editor
            def finish_visual():
                dlg.grab_set()
                self.active_crop_editor = None
            self.visual_crop_mode(current_edit_task, on_finish=finish_visual)
        editor.set_visual_crop_callback(start_visual_crop_with_release)
        # =================================================================
    
        # 第一行：模板 + 重名
        # 一行：输出名称模板 + 重名处理 + 输出目录
        row_top = ttk.Frame(left_panel)
        row_top.pack(fill=tk.X, pady=(0,5))  # 上边距为0，减少上方空白
        
        ttk.Label(row_top, text="输出名称模板:").pack(side=tk.LEFT, padx=5)
        name_var = tk.StringVar(value=task.get('name_template', '{Filename}'))
        name_combo = ttk.Combobox(row_top, textvariable=name_var,
                                  values=["{Filename}", "{Folder name}{Filename}", "{Original}/{Filename}", "{Folder name}_{Filename}", "{Original}/123/{Filename}", "{Folder name}/{Filename}", "{Original}/{Folder name}/{Filename}"],
                                  width=16)  # 适当减小宽度
        name_combo.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(row_top, text="重名处理:").pack(side=tk.LEFT, padx=(5,2))
        dup_var = tk.StringVar(value=task.get('duplicate_mode', '自动重命名'))
        dup_combo = ttk.Combobox(row_top, textvariable=dup_var,
                                 values=["覆盖", "自动重命名", "询问", "跳过"], state="readonly", width=9)
        dup_combo.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(row_top, text="输出目录:").pack(side=tk.LEFT, padx=(10,2))
        init_dir = task.get('output_dir') or ''
        output_dir_var = tk.StringVar(value=init_dir)
        output_dir_entry = ttk.Entry(row_top, textvariable=output_dir_var, width=18)
        output_dir_entry.pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)  # 自适应剩余宽度
        
        def browse_output_dir():
            d = filedialog.askdirectory(initialdir=output_dir_var.get() or self.output_dir.get())
            if d:
                output_dir_var.set(os.path.normpath(d))
        browse_btn = ttk.Button(row_top, text="浏览", command=browse_output_dir, width=4)
        browse_btn.pack(side=tk.LEFT, padx=1)
        
        def clear_output_dir():
            output_dir_var.set("")
        clear_btn = ttk.Button(row_top, text="清空", command=clear_output_dir, width=4)
        clear_btn.pack(side=tk.LEFT, padx=1)
        
        ttk.Label(row_top, text="(留空=全局)", foreground="gray").pack(side=tk.LEFT, padx=2)
    
        # 详细预览框
        preview_frame = ttk.LabelFrame(left_panel, text="详细输出预览")
        preview_frame.pack(fill=tk.X, pady=5, padx=5)
        preview_text = tk.Text(preview_frame, height=6, wrap=tk.WORD, bg='#f0f0f0', relief=tk.SUNKEN, font=("TkFixedFont", 9))
        preview_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        preview_text.config(state=tk.DISABLED)
    
        # 按钮行
        btn_frame = ttk.Frame(left_panel)
        btn_frame.pack(fill=tk.X, pady=10)
    
        # 辅助函数：动态调整对话框高度
        def adjust_dialog_height():

            dlg.update_idletasks()
            total_height = 0
            for child in left_panel.winfo_children():

                total_height += child.winfo_reqheight()

            decoration = 40
            new_height = total_height + decoration
            # 降低最小高度，让收回时能缩小
            if new_height < 280:
                new_height = 280

            cur_width = dlg.winfo_width()
            dlg.geometry(f"{cur_width}x{new_height}+{x}+{y}")
            dlg.update_idletasks()

        # 保存原始的 _toggle_enhance 方法
        original_toggle = editor._toggle_enhance

        # 定义新的回调函数
        def toggle_with_resize():

            original_toggle()
            # 延迟足够时间，等待布局完全更新
            dlg.after(20, adjust_dialog_height)

        # 直接修改“更多调整”按钮的命令（关键！）
        editor.toggle_btn.config(command=toggle_with_resize)

        # 同时替换编辑器的方法（备用）
        editor._toggle_enhance = toggle_with_resize

        # 初始调用一次，让窗口适应展开状态
        dlg.after(20, adjust_dialog_height)
    
        # 绑定各种变化以更新详细预览和主预览
        def on_any_change(*args):
            try:
                current_settings = editor.get_settings()
                update_detailed_preview(current_settings)
                update_main_preview(current_settings)
            except Exception as e:
                print("预览更新错误:", e)
    
        editor.bind_preview_callback(on_any_change)
        name_var.trace_add('write', on_any_change)
        dup_var.trace_add('write', on_any_change)
        output_dir_var.trace_add('write', on_any_change)
    
        def update_detailed_preview(settings=None):
            try:
                if settings is None:
                    settings = editor.get_settings()
                task_out_dir = output_dir_var.get().strip()
                if task_out_dir:
                    out_dir_raw = task_out_dir
                else:
                    out_dir_raw = self.output_dir.get().strip()
                    if out_dir_raw == '.':
                        out_dir_raw = ''
                src_path = task['path']
                src_dir = os.path.dirname(src_path)
                if not out_dir_raw:
                    out_dir_display = "（使用原文件目录）"
                    out_dir_for_path = src_dir
                else:
                    out_dir_display = os.path.normpath(out_dir_raw).replace('\\', '/')
                    out_dir_for_path = out_dir_display
    
                name_template = name_var.get()
                raw_out_name = self.build_output_name(name_template, src_path)
                fmt = settings['format']
                if fmt == "保持原格式":
                    ext = os.path.splitext(src_path)[1].lower()
                else:
                    ext = self._get_output_extension(fmt)
    
                if "{Original}" in name_template:
                    base_out_path = os.path.normpath(raw_out_name + ext).replace('\\', '/')
                else:
                    base_out_path = os.path.normpath(os.path.join(out_dir_for_path, raw_out_name + ext)).replace('\\', '/')
    
                dup_mode = dup_var.get()
                final_path = base_out_path
                if dup_mode == "自动重命名":
                    final_path = self._get_unique_filename(base_out_path.replace('/', os.sep), "自动重命名").replace('\\', '/')
                elif dup_mode == "询问":
                    final_path = base_out_path + " (如有冲突将询问)"
                elif dup_mode == "跳过":
                    final_path = base_out_path + " (如有冲突则跳过)"
    
                src_path_disp = src_path.replace('\\', '/')
                rot = settings['rotation']
                rot_map = {"0°": "无旋转", "90°": "左转90°", "-90°": "右转90°", "180°": "旋转180°"}
                rot_display = rot_map.get(rot, rot)
                flip_parts = []
                if settings['h_flip']:
                    flip_parts.append("水平翻转")
                if settings['v_flip']:
                    flip_parts.append("垂直翻转")
                flip_display = ", ".join(flip_parts) if flip_parts else "无翻转"
    
                if fmt == "保持原格式":
                    format_quality = f"输出格式: 保持原格式 ({ext}) | 质量/压缩: (保持原参数)"
                else:
                    format_quality = f"输出格式: {fmt} | 质量/压缩: {settings['quality']}"
    
                resize_mode = settings['resize_mode']
                if resize_mode == "无调整":
                    resize_info = "尺寸调整: 不调整"
                elif resize_mode == "精确 (WxH)":
                    resize_info = f"尺寸调整: 精确 {settings['resize_w']}x{settings['resize_h']}"
                elif resize_mode == "限制长边":
                    resize_info = f"尺寸调整: 限制长边 {settings['resize_w']}px"
                elif resize_mode == "限制短边":
                    resize_info = f"尺寸调整: 限制短边 {settings['resize_w']}px"
                else:
                    resize_info = f"尺寸调整: {resize_mode}"
    
                line1 = f"{format_quality} | 旋转: {rot_display} | 翻转: {flip_display} | {resize_info}"
    
                parts = []
                if settings.get('crop_enabled', False):
                    parts.append(f"裁剪: x={settings['crop_x']} y={settings['crop_y']} w={settings['crop_w']} h={settings['crop_h']}")
                filters = []
                if settings.get('brightness_enable', False) and settings.get('brightness_val', 0) != 0:
                    filters.append(f"亮度 {settings['brightness_val']:+}")
                if settings.get('contrast_enable', False) and settings.get('contrast_val', 0) != 0:
                    filters.append(f"对比度 {settings['contrast_val']:+}")
                if settings.get('saturation_enable', False) and settings.get('saturation_val', 0) != 0:
                    filters.append(f"饱和度 {settings['saturation_val']:+}")
                if settings.get('color_enable', False):
                    r = settings.get('r_gain', 0)
                    g = settings.get('g_gain', 0)
                    b = settings.get('b_gain', 0)
                    if any(v != 0 for v in (r, g, b)):
                        filters.append(f"RGB调整(R:{r:+} G:{g:+} B:{b:+})")
                if settings.get('sharpen_enable', False) and settings.get('sharpen_val', 0) != 0:
                    filters.append(f"锐化 {settings['sharpen_val']:+}")
                if filters:
                    parts.append(f"滤镜: {', '.join(filters)}")
                if settings.get('watermark_enable', False):
                    wm_text = settings.get('watermark_text', '')
                    parts.append(f"水印: '{wm_text}'")
                line2 = " | ".join(parts) if parts else "无额外调整"
    
                delete_warning = "⚠️ 转换后将删除原文件" if settings.get('delete_original', False) else ""
    
                info_lines = [
                    f"原文件: {src_path_disp}",
                    f"输出目录: {out_dir_display}",
                    f"最终输出路径: {final_path}",
                    line1,
                    line2,
                ]
                if delete_warning:
                    info_lines.append(delete_warning)
    
                preview_text.config(state=tk.NORMAL)
                preview_text.delete(1.0, tk.END)
                preview_text.insert(tk.END, "\n".join(info_lines))
                preview_text.config(state=tk.DISABLED)
            except Exception as e:
                preview_text.config(state=tk.NORMAL)
                preview_text.delete(1.0, tk.END)
                preview_text.insert(tk.END, f"预览生成失败: {str(e)}")
                preview_text.config(state=tk.DISABLED)
                print(f"详细预览错误: {e}")
    
        def update_main_preview(settings=None):
            if settings is None:
                settings = editor.get_settings()
            preview_task = task.copy()
            preview_task.update(settings)
            preview_task['output_dir'] = output_dir_var.get().strip() or None
            if self.preview_window is None or not self.preview_window.winfo_exists():
                self._show_preview(preview_task)
            else:
                self._update_preview_content(preview_task)
    
        # 初始更新
        on_any_change()
        # 初始调整高度（确保展开状态高度正确）
        dlg.after(30, adjust_dialog_height)
    
        # 保存逻辑
        def save_single():
            new_settings = editor.get_settings()
            new_settings.pop('preview_size', None)
            new_settings['name_template'] = name_var.get()
            new_settings['duplicate_mode'] = dup_var.get()
            new_settings['output_dir'] = output_dir_var.get().strip() or None
            task.update(new_settings)
            new_display = self.get_task_display_text(task)
            self.task_listbox.delete(idx)
            self.task_listbox.insert(idx, new_display)
            self._update_preview_content(task)
            self.save_current_state_to_history()
            on_dlg_close()
    
        def save_batch():
            new_settings = editor.get_settings()
            new_settings.pop('preview_size', None)
            new_settings['name_template'] = name_var.get()
            new_settings['duplicate_mode'] = dup_var.get()
            new_output_dir = output_dir_var.get().strip() or None
            for i in selected_indices:
                t = self.tasks[i]
                t.update(new_settings)
                t['output_dir'] = new_output_dir
                self.task_listbox.delete(i)
                self.task_listbox.insert(i, self.get_task_display_text(t))
            if selected_indices:
                self._update_preview_content(self.tasks[selected_indices[0]])
            self.save_current_state_to_history()
            on_dlg_close()
    
        def sync_to_main():
            new_settings = editor.get_settings()
            new_settings['name_template'] = name_var.get()
            new_settings['duplicate_mode'] = dup_var.get()
            new_settings.pop('preview_size', None)
            self.template_editor.set_settings(new_settings)
            self.update_template_preview(new_settings)
            messagebox.showinfo("同步完成", "已将当前参数同步到主窗口模板（不含输出目录）")
    
        # 按钮
        is_multi = selected_indices is not None and len(selected_indices) > 1
        if not is_multi:
            ttk.Button(btn_frame, text="保存", command=save_single).pack(side=tk.LEFT, padx=10)
        else:
            ttk.Button(btn_frame, text="仅保存当前任务", command=save_single).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text=f"应用到所有 {len(selected_indices)} 个任务", command=save_batch).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=on_dlg_close).pack(side=tk.LEFT, padx=10)
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
    
        # 处理输出目录：为空或 '.' 表示使用源文件目录
        out_dir_input = self.output_dir.get().strip()
        if out_dir_input == "" or out_dir_input == ".":
            out_dir = None
            out_dir_display = "（原文件目录）"
        else:
            out_dir = os.path.normpath(out_dir_input)
            out_dir_display = out_dir
            os.makedirs(out_dir, exist_ok=True)
    
        # ========== 安全检查：检测危险组合 ==========
        dangerous_overwrite_with_delete = []
        dangerous_overwrite_no_delete = []
        for idx, task in enumerate(self.tasks):
            src_dir = os.path.dirname(os.path.normpath(task['path']))
            # 优先使用任务的单独输出目录
            task_out_dir = task.get('output_dir')
            if task_out_dir and task_out_dir.strip():
                actual_out_dir = task_out_dir.strip()
            else:
                actual_out_dir = src_dir if out_dir is None else out_dir
            dup_mode = task.get('duplicate_mode', self.duplicate_mode_var.get())
            delete_orig = task.get('delete_original', self.delete_original_var.get())
            
            if actual_out_dir == src_dir and dup_mode == "覆盖":
                if delete_orig:
                    dangerous_overwrite_with_delete.append((idx, task))
                else:
                    dangerous_overwrite_no_delete.append((idx, task))
        
        # 最危险：覆盖并删除原文件 -> 阻止转换
        if dangerous_overwrite_with_delete:
            msg = "❌ 安全保护：检测到以下任务将覆盖原文件的同时删除原文件，这会导致文件永久丢失！\n\n"
            for idx, task in dangerous_overwrite_with_delete[:10]:
                msg += f"• {os.path.basename(task['path'])}\n"
            if len(dangerous_overwrite_with_delete) > 10:
                msg += f"• ... 共 {len(dangerous_overwrite_with_delete)} 个任务\n"
            msg += "\n请将重名处理改为“自动重命名”或关闭“删除原文件”，或更改输出目录。\n\n是否取消转换？"
            if messagebox.askyesno("严重错误", msg, icon='error'):
                return
            else:
                return
        
        # 覆盖但不删除 -> 警告并确认
        if dangerous_overwrite_no_delete:
            msg = "⚠️ 警告：检测到以下任务将直接覆盖原文件（原内容将被替换）。\n\n"
            for idx, task in dangerous_overwrite_no_delete[:10]:
                msg += f"• {os.path.basename(task['path'])}\n"
            if len(dangerous_overwrite_no_delete) > 10:
                msg += f"• ... 共 {len(dangerous_overwrite_no_delete)} 个任务\n"
            msg += "\n是否继续覆盖？如果不希望覆盖，请将重名处理改为“自动重命名”。"
            if not messagebox.askyesno("覆盖确认", msg, icon='warning'):
                return
    
        # ========== 原有逻辑继续 ==========
        # 检查是否有任务开启了删除原文件（但不与覆盖同时存在的情况）
        has_delete = any(task.get('delete_original', False) for task in self.tasks)
        if has_delete:
            delete_count = sum(1 for task in self.tasks if task.get('delete_original', False))
            msg = f"检测到 {delete_count} 个任务开启了“删除原文件”选项。\n\n删除操作会将原文件移至回收站/废纸篓，不可恢复！\n\n是否继续转换？"
            if not messagebox.askyesno("确认删除", msg, icon='warning'):
                return
    
        # 自动修复：如果输出目录为空且覆盖，但之前已经处理过危险情况，这里不再重复
        # 原有代码中有一段将覆盖改为自动重命名的逻辑，但那是针对 out_dir 不为 None 的情况。
        # 现在 out_dir 可能为 None，需要保留该逻辑的增强版（可选，但我们已经用警告替代了自动修改，避免用户困惑）
        # 为了安全，可以注释掉原有的自动修改，因为我们已经让用户确认了。
        # 如果需要自动修复，可以保留但修改条件。
        # 这里我们选择不自动修改，而是让用户决定。
    
        # 计算原始文件总大小
        self.total_input_size = 0
        for task in self.tasks:
            if os.path.exists(task['path']):
                self.total_input_size += os.path.getsize(task['path'])
        self.total_output_size = 0
    
        # 获取 resolved_items
        resolved_items = self.resolve_duplicate_paths(self.tasks, out_dir)
        if not resolved_items:
            messagebox.showinfo("提示", "所有任务均被跳过，没有需要转换的任务")
            return
    
        self.start_btn.config(state=tk.DISABLED)
        self.converting = True
        self.cancel_convert = False
        self.cancel_btn.config(state=tk.NORMAL)
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

    def _convert_single(self, task, out_dir, original_idx):
        # 使用公共函数简化
        if self.cancel_convert:
            return (original_idx, False, "用户取消", 0)
        src = task['path']
        fmt = task['format']
        qual = task['quality']
        keep_exif = task.get('keep_exif', self.keep_exif_var.get())
        preserve_date = task.get('preserve_original_date', self.preserve_date_var.get())
        delete_original = task.get('delete_original', self.delete_original_var.get())
        out_path = task.get('out_path')
        if out_path is None:
            out_path = self._build_output_path(task, out_dir)
        out_dir_path = os.path.dirname(out_path)
        if out_dir_path:
            os.makedirs(out_dir_path, exist_ok=True)
        src_stat = None
        if preserve_date and os.path.exists(src):
            src_stat = os.stat(src)
        try:
            with Image.open(src) as img:
                img = self._apply_all_transforms(img, task)
                if fmt == "保持原格式":
                    actual_fmt = os.path.splitext(src)[1].lower().lstrip('.')
                    actual_fmt = actual_fmt.upper()
                    if actual_fmt not in FORMAT_CONFIG:
                        actual_fmt = 'JPEG'
                    original_path_for_config = src
                else:
                    actual_fmt = fmt
                    original_path_for_config = None
                save_params = self._prepare_save_params(fmt, qual, original_path_for_config)
                target_mode = self._get_output_mode(img, fmt, original_path_for_config)
                if target_mode:
                    img = img.convert(target_mode)
                exif = None
                if keep_exif and hasattr(img, 'info') and 'exif' in img.info:
                    exif = img.info['exif']
                    config = FORMAT_CONFIG.get(actual_fmt)
                    if config and config.get('supports_exif', False):
                        save_params['exif'] = exif
                if fmt == "ICO":
                    sizes = task.get('ico_sizes')
                    if not sizes:
                        # 从模板编辑器获取当前尺寸
                        sizes = self.template_editor._ico_sizes
                    save_params['sizes'] = sizes
                img.save(out_path, actual_fmt, **save_params)
            if preserve_date and src_stat is not None:
                if platform.system() == 'Windows':
                    ctime = os.path.getctime(src)
                    try:
                        self.set_file_times(out_path, ctime, src_stat.st_atime, src_stat.st_mtime)
                    except Exception:
                        pass
                else:
                    os.utime(out_path, (src_stat.st_atime, src_stat.st_mtime))
            # 删除原文件
            if delete_original and os.path.exists(src):
                if os.path.exists(out_path) and os.path.samefile(src, out_path):
                    raise Exception("安全保护: 禁止覆盖并删除原文件，这会导致文件丢失。请修改重名处理策略。")
                try:
                    send_to_trash(src)
                except Exception as e:
                    raise Exception(f"删除原文件失败: {e}")
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
