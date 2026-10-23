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
import struct

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
        'default_quality': 4,
        'mode': None,
        'supports_exif': False,
    },
    'WEBP': {
        'extension': '.webp',
        'save_params': {'quality': 'quality', 'lossless': False},
        'quality_range': (1, 100),
        'default_quality': 80,
        'mode': 'None',
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


# ==================== 字体缓存 fonts_cache.json（2026-09-08 重写，与 safe5 文字水印完全一致）====================
# 与 picpresets.json 同级（脚本目录）。结构（与 safe5 字节级一致）：
#   {version, scanned_at, fonts_dir_mtime,
#    system_fonts: [{name, file, path}, ...],   # 系统字体：name=显示名(中文优先)，file=文件名，path=完整路径
#    recent_external: [path, ...]}              # 用户最近用过的外部字体路径（最多 20 条）
# 作用：① 免每次启动重扫系统字体目录（~30ms）；② 渲染时 _find_font_file 由 system_fonts
#        建 文件名→路径 映射直接查表，免 os.listdir；③ 下拉启动时即由 merged_font_names()
#        合并 内置表+系统字体，无需点「检测本地」才出现新字体。
# 新鲜度：fonts_dir_mtime ≠ C:\Windows\Fonts 目录 mtime 即过期（任何字体增删都改目录 mtime）。
FONTS_CACHE_FILE = "fonts_cache.json"
FONTS_CACHE_MAX_RECENT = 20

# 精简内置字体表（中文+英文）：下拉前置快捷入口，且 _find_font_file 优先按此解析，
# 避免 tkinter.families() 的 @ 前缀竖排字体（ImageFont 加载不了、不生效）。模块级，
# 供 merged_font_names() / _find_font_file 等全局函数引用。
CN_FONT_MAP = {
    "微软雅黑": "msyh.ttc",
    "微软雅黑 Bold": "msyhbd.ttc",
    "宋体": "simsun.ttc",
    "黑体": "simhei.ttf",
    "楷体": "simkai.ttf",
    "仿宋": "simfang.ttf",
}
EN_FONT_MAP = {
    "Arial": "arial.ttf",
    "Arial Bold": "arialbd.ttf",
    "Times New Roman": "times.ttf",
    "Georgia": "georgia.ttf",
    "Verdana": "verdana.ttf",
    "Tahoma": "tahoma.ttf",
    "Courier New": "cour.ttf",
    "Impact": "impact.ttf",
}

_fonts_state = {"list": None, "dir_mtime": None, "recent": [], "file_map": None}


def get_fonts_cache_path():
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, FONTS_CACHE_FILE)


def _fonts_dir_mtime():
    d = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    try:
        return os.path.getmtime(d)
    except OSError:
        return 0.0


def _fonts_save_cache():
    try:
        with open(get_fonts_cache_path(), "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "fonts_dir_mtime": _fonts_state.get("dir_mtime") or 0.0,
                "system_fonts": _fonts_state.get("list") or [],
                "recent_external": _fonts_state.get("recent") or [],
            }, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _fonts_load_cache() -> bool:
    """从磁盘加载缓存到 _fonts_state。返回 True=加载成功且未过期（可直接用）。"""
    try:
        with open(get_fonts_cache_path(), encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return False
    # 版本不兼容（如旧 v2 用 font_files 映射）即视为失效，触发重建
    if not isinstance(d, dict) or d.get("version") != 1:
        return False
    cur_mtime = _fonts_dir_mtime()
    if not cur_mtime or abs((d.get("fonts_dir_mtime") or 0.0) - cur_mtime) > 1e-3:
        return False          # 目录已变 → 缓存过期
    lst = d.get("system_fonts") or []
    rec = d.get("recent_external") or []
    if not isinstance(lst, list) or not all(isinstance(x, dict) and x.get("path") for x in lst):
        return False
    _fonts_state["list"] = lst
    _fonts_state["dir_mtime"] = cur_mtime
    # 由 system_fonts 建 小写文件名→路径 映射（_find_font_file 查表用，免 os.listdir）
    _fonts_state["file_map"] = {x["file"].lower(): x["path"] for x in lst
                                if isinstance(x.get("file"), str) and isinstance(x.get("path"), str)}
    _fonts_state["recent"] = [x for x in rec if isinstance(x, str)] if isinstance(rec, list) else []
    return True


def _font_names_from_file(path):
    """解析单个字体文件的 name table，返回 {'zh_full','zh_fam','en_full','en_fam'}。

    采用精确 seek：先读 sfnt 头 + table 目录找到 name table 的偏移，再只读那一段，
    因此对 msyh.ttc(22MB) 这类大文件也只读几百字节（实测全量 151 个字体共 ~0.01s）。
    支持 TTF/OTF/TTC；TTC 只读第一个 face，与 ffmpeg drawtext 行为一致。
    解析失败返回 None。（照搬 safe5，纯 struct 解析，无第三方依赖）
    """
    try:
        with open(path, "rb") as fh:
            tag = fh.read(4)
            base = 0
            if tag == b"ttcf":
                fh.seek(8)
                n = struct.unpack(">I", fh.read(4))[0]
                if n < 1:
                    return None
                fh.seek(12)
                base = struct.unpack(">I", fh.read(4))[0]
                if base <= 0:
                    return None
            fh.seek(base)
            hdr = fh.read(12)
            if len(hdr) < 12 or hdr[:4] not in _FONT_SFNT_TAGS:
                return None
            num_tables = struct.unpack(">H", hdr[4:6])[0]
            if not 0 < num_tables <= 4096:
                return None
            tdir = fh.read(num_tables * 16)
            if len(tdir) < num_tables * 16:
                return None
            name_off = None
            for i in range(num_tables):
                rec = tdir[i * 16:i * 16 + 16]
                if rec[:4] == b"name":
                    name_off = struct.unpack(">I", rec[8:12])[0]
                    break
            if name_off is None:
                return None
            fh.seek(name_off)
            nb = fh.read(512 * 1024)   # name table 段，足够容纳全部语言记录
            if len(nb) < 6:
                return None
            fmt, count, str_off = struct.unpack(">HHH", nb[:6])
            if count == 0 or count > 2048:
                return None
            recs = []
            q = 6
            for _ in range(count):
                if q + 12 > len(nb):
                    break
                recs.append(struct.unpack(">HHHHHH", nb[q:q + 12]))
                q += 12

            def pick(langs, nids):
                """严格匹配：语言必须命中（否则英文名会被误当中文名）。"""
                found = []
                for plat, enc, lang, nid, ln, off in recs:
                    if nid not in nids or lang not in langs:
                        continue
                    s = str_off + off
                    if s + ln > len(nb):
                        continue
                    raw = nb[s:s + ln]
                    if plat == 3 or (plat == 0 and enc in (4, 6)):
                        try:
                            txt = raw.decode("utf-16-be")
                        except Exception:
                            continue
                    elif plat == 1:
                        try:
                            txt = raw.decode("latin-1")
                        except Exception:
                            continue
                    else:
                        continue
                    txt = txt.strip("\x00").strip()
                    if txt:
                        found.append((nid, txt))
                if not found:
                    return None
                for nid in nids:
                    for n, t in found:
                        if n == nid:
                            return t
                return found[0][1]

            return {
                "zh_full": pick(_FONT_ZH_LANGS, (4,)),
                "zh_fam": pick(_FONT_ZH_LANGS, (1, 16)),
                "en_full": pick(_FONT_EN_LANGS, (4,)),
                "en_fam": pick(_FONT_EN_LANGS, (1, 16)),
            }
    except Exception:
        return None


def scan_system_fonts(fonts_dir=None):
    """枚举系统字体目录内全部 TTF/TTC/OTF，解析显示名（中文优先）。

    返回按显示名排序的 [{'name','file','path'}, ...]；fonts_dir 默认 C:\\Windows\\Fonts。
    .fon 位图字体（drawtext 不支持）与非字体文件跳过；解析失败用文件名主干兜底，
    保证不漏字体；同名只保留第一个。
    """
    fonts_dir = fonts_dir or os.path.join(
        os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    try:
        entries = sorted(os.listdir(fonts_dir))
    except OSError:
        return []
    out, seen = [], set()
    for fn in entries:
        if os.path.splitext(fn)[1].lower() not in _FONT_EXTS:
            continue
        full = os.path.join(fonts_dir, fn)
        try:
            if not os.path.isfile(full):
                continue
        except OSError:
            continue
        r = _font_names_from_file(full)
        if r:
            name = (r.get("zh_full") or r.get("zh_fam")
                    or r.get("en_full") or r.get("en_fam")
                    or os.path.splitext(fn)[0])
        else:
            name = os.path.splitext(fn)[0]
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "file": fn, "path": full})
    out.sort(key=lambda x: x["name"])
    return out


# 字体名解析辅助常量（与 safe5 一致）
_FONT_ZH_LANGS = (0x0804, 0x0404, 0x0C04, 0x1004, 0x1404, 0x7C04)
_FONT_EN_LANGS = (0x0409, 0x0000, 0x0C09, 0x0809, 0x1009, 0x1409, 0x1809, 0x1C09,
                  0x2009, 0x2409, 0x2809, 0x2C09, 0x3009, 0x3409)
_FONT_SFNT_TAGS = (b"\x00\x01\x00\x00", b"OTTO", b"true")
_FONT_EXTS = (".ttf", ".ttc", ".otf")


def ensure_fonts_cached() -> list:
    """返回系统字体列表 [{'name','file','path'},...]（模块级缓存）。

    磁盘缓存新鲜 → 直接用；缺失/过期 → 全量扫描并落盘。
    全量扫描实测 ~30ms，启动可同步调用；同时由 system_fonts 建 file_map 供渲染查表。
    """
    if _fonts_state.get("list"):
        cur = _fonts_dir_mtime()
        if _fonts_state.get("dir_mtime") and abs(_fonts_state["dir_mtime"] - cur) < 1e-3:
            return _fonts_state["list"]
    if _fonts_load_cache():
        return _fonts_state["list"]
    _lst = scan_system_fonts()
    # 扫描为空（异常 / 目录不可读）→ 不缓存，留待下次重扫，避免把空结果当「新鲜」永久滞留
    if _lst:
        _fonts_state["list"] = _lst
        _fonts_state["dir_mtime"] = _fonts_dir_mtime()
        _fonts_state["file_map"] = {x["file"].lower(): x["path"] for x in _lst}
        _fonts_save_cache()
    return _lst


def force_rescan_fonts() -> list:
    """「检测本地」按钮强制重扫（不信任任何缓存），返回新列表。"""
    _lst = scan_system_fonts()
    _fonts_state["list"] = _lst
    _fonts_state["dir_mtime"] = _fonts_dir_mtime()
    _fonts_state["file_map"] = {x["file"].lower(): x["path"] for x in _lst}
    _fonts_save_cache()
    return _lst


def get_font_file_map() -> dict:
    """返回 小写文件名→完整路径 映射（渲染时 _find_font_file 查表用，免 os.listdir）。"""
    ensure_fonts_cached()
    return _fonts_state.get("file_map") or {}


def merged_font_names() -> list:
    """字体下拉的显示名列表：内置中/英文字体在前（快捷入口），随后接系统扫描字体，
    按显示名去重（内置优先），不含 .fon。启动即调用此填充下拉，无需点「检测本地」。"""
    names = list(CN_FONT_MAP.keys()) + list(EN_FONT_MAP.keys())
    seen = set(names)
    for f in ensure_fonts_cached():
        nm = (f.get("name") or "").strip()
        if nm and nm not in seen:
            seen.add(nm)
            names.append(nm)
    return names


def get_recent_external_fonts() -> list:
    ensure_fonts_cached()   # 顺带保证系统字体缓存已加载/新鲜
    return list(_fonts_state.get("recent") or [])


def record_external_font(path):
    p = (path or "").strip()
    if not p or not os.path.isfile(p):
        return
    rec = _fonts_state.get("recent") or []
    rec = [x for x in rec if x != p]
    rec.insert(0, p)
    _fonts_state["recent"] = rec[:FONTS_CACHE_MAX_RECENT]
    _fonts_save_cache()



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

        # 水印相关变量（必须全部定义）
        self.watermark_enable = tk.BooleanVar(value=False)
        self.watermark_text_var = tk.StringVar(value="Watermark")
        self.watermark_font_var = tk.StringVar(value="Arial")
        self.watermark_size_var = tk.IntVar(value=36)
        self.watermark_pos_var = tk.StringVar(value="右下")          # ← 缺失的这一行
        self.watermark_opacity_var = tk.IntVar(value=80)
        self.watermark_color_var = tk.StringVar(value="#FFFFFF")
        self.watermark_angle_var = tk.IntVar(value=0)               # 新增旋转
        self.watermark_tile_var = tk.BooleanVar(value=False)        # 新增平铺
        self.watermark_gap_x_var = tk.IntVar(value=50)   # 水平间距（像素）
        self.watermark_gap_y_var = tk.IntVar(value=50)   # 垂直间距（像素）
        self.watermark_ext_font_var = tk.StringVar(value="")            # 外部字体文件路径
        self.watermark_border_var = tk.IntVar(value=0)                  # 描边粗细
        self.watermark_border_color_var = tk.StringVar(value="#000000") # 描边颜色

        self._create_widgets()
        self._setup_traces()
        self._ico_sizes = [(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)]
        self._loading_preset = False
        self._init_enhance_state()

        if self.default_expanded:
            self._toggle_enhance()

    def _create_widgets(self):
        # 第一行：格式、质量、旋转、翻转
        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X, pady=2)
        lbl_format = ttk.Label(row1, text="格式:")
        lbl_format.pack(side=tk.LEFT, padx=2)
        ToolTip(lbl_format, "WEBP 格式下，质量值设为 101 可触发无损模式")
        self.format_var = tk.StringVar(value="WEBP")
        format_combo = ttk.Combobox(row1, textvariable=self.format_var,
                                    values=["保持原格式", "JPEG", "PNG", "WEBP", "BMP", "ICO"],
                                    state="readonly", width=10)
        format_combo.pack(side=tk.LEFT, padx=2)

        self.quality_frame = ttk.Frame(row1)
        self.quality_frame.pack(side=tk.LEFT, padx=2)
        self.quality_label = ttk.Label(self.quality_frame, text="质量:")
        self.quality_label.pack(side=tk.LEFT, padx=(10,2))

        self.quality_var = tk.IntVar(value=80)
        self.quality_scale = ttk.Scale(self.quality_frame, from_=1, to=101, variable=self.quality_var,
                                       orient=tk.HORIZONTAL, length=80)
        self.quality_scale.pack(side=tk.LEFT, padx=2)
        self.quality_spin = ttk.Spinbox(self.quality_frame, from_=1, to=101, textvariable=self.quality_var,
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

        ttk.Label(row3, text="预览尺寸:").pack(side=tk.LEFT, padx=(10,2))
        self.preview_size_var = tk.IntVar(value=600)
        self.preview_size_spin = ttk.Spinbox(row3, from_=100, to=2000, textvariable=self.preview_size_var, width=6)
        self.preview_size_spin.pack(side=tk.LEFT, padx=2)

        self.toggle_btn = ttk.Button(row3, text="▶ 更多调整", width=12, command=self._toggle_enhance)
        self.toggle_btn.pack(side=tk.RIGHT, padx=(0,15))

        self.enhance_expanded = False
        self.enhance_frame = ttk.Frame(self)

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

        color_frame = ttk.LabelFrame(self.enhance_frame, text="色彩平衡")
        color_frame.pack(fill=tk.X, pady=2, padx=5)
        color_header = ttk.Frame(color_frame)
        color_header.pack(fill=tk.X, pady=2, padx=5)
        self.color_enable = tk.BooleanVar(value=False)
        ttk.Checkbutton(color_header, text="启用RGB调整", variable=self.color_enable).pack(side=tk.LEFT)

        row = ttk.Frame(color_frame)
        row.pack(fill=tk.X, pady=2, padx=5)

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

        self.watermark_frame = ttk.LabelFrame(self.enhance_frame, text="文字水印 - 简易")
        self.watermark_frame.pack(fill=tk.X, pady=2, padx=5)

        wm_row1 = ttk.Frame(self.watermark_frame)
        wm_row1.pack(fill=tk.X, pady=2, padx=5)

        self.watermark_enable = tk.BooleanVar(value=False)
        ttk.Checkbutton(wm_row1, text="启用", variable=self.watermark_enable).pack(side=tk.LEFT, padx=2)

        ttk.Label(wm_row1, text="文本:").pack(side=tk.LEFT, padx=5)
        self.watermark_text_var = tk.StringVar(value="Watermark")
        ttk.Entry(wm_row1, textvariable=self.watermark_text_var, width=15).pack(side=tk.LEFT, padx=2)

        # 字体下拉：用 safe5 的精简内置表（中文+英文，模块级 CN_FONT_MAP/EN_FONT_MAP），
        # 避免 tkinter.families() 里的 @ 前缀竖排字体名（ImageFont 无法加载、不生效）。
        self._wm_cn_font_map = CN_FONT_MAP
        self._wm_en_font_map = EN_FONT_MAP
        # 启动即构建/读取字体缓存，并把「内置表 + 系统字体」合并填入下拉——
        # 新装的字体打开时就出现，无需点「检测本地」（这才是缓存的意义）。
        try:
            font_list = merged_font_names()
        except Exception:
            font_list = list(CN_FONT_MAP.keys()) + list(EN_FONT_MAP.keys())
        self.watermark_font_var = tk.StringVar(value="Arial" if "Arial" in font_list else (font_list[0] if font_list else "Arial"))
        self.font_combo = ttk.Combobox(wm_row1, textvariable=self.watermark_font_var, values=font_list, width=12, state="readonly")
        self.font_combo.pack(side=tk.LEFT, padx=2)

        # 检测本地：强制重扫系统字体（不信任缓存，装了新字体马上生效）并刷新下拉。
        def _rescan_system_fonts():
            try:
                force_rescan_fonts()
                _vals = merged_font_names()
            except Exception:
                _vals = list(CN_FONT_MAP.keys()) + list(EN_FONT_MAP.keys())
            self.font_combo.config(values=_vals)
            if self.watermark_font_var.get() not in _vals:
                self.watermark_font_var.set(_vals[0] if _vals else "Arial")
        ttk.Button(wm_row1, text="检测本地", command=_rescan_system_fonts, width=8).pack(side=tk.LEFT, padx=(8, 2))

        # 外部字体：留空则用上方「字体」下拉；填写则优先使用（支持 ttf/ttc/otf）。
        # 用 Combobox 接「历史路径」下拉（来自 fonts_cache.json 的 recent_external），
        # 点一下即填，也可继续手改；浏览选完自动记录进历史并刷新下拉。
        ttk.Label(wm_row1, text="外部字体:").pack(side=tk.LEFT, padx=(5, 2))
        self.watermark_ext_font_var = tk.StringVar(value="")
        try:
            _recent = get_recent_external_fonts()
        except Exception:
            _recent = []
        self.ext_font_combo = ttk.Combobox(wm_row1, textvariable=self.watermark_ext_font_var, values=_recent, width=22)
        self.ext_font_combo.pack(side=tk.LEFT, padx=2)

        def _browse_ext_font():
            _p = filedialog.askopenfilename(
                title="选择字体文件",
                filetypes=[("字体文件", "*.ttf *.ttc *.otf"), ("所有文件", "*.*")],
                parent=self)
            if _p:
                self.watermark_ext_font_var.set(_p)
                record_external_font(_p)   # 记入 fonts_cache.json 的 recent_external
                try:
                    self.ext_font_combo.config(values=get_recent_external_fonts())
                except Exception:
                    pass
        ttk.Button(wm_row1, text="浏览", command=_browse_ext_font, width=6).pack(side=tk.LEFT, padx=2)

        def _clear_ext_font():
            self.watermark_ext_font_var.set("")
        ttk.Button(wm_row1, text="清空", command=_clear_ext_font, width=6).pack(side=tk.LEFT, padx=2)

        # ---- 第二行：大小 / 透明度 / 颜色 / 边框 / 边框色（从第一行腾出空间后下移）----
        wm_size_row = ttk.Frame(self.watermark_frame)
        wm_size_row.pack(fill=tk.X, pady=2, padx=5)

        ttk.Label(wm_size_row, text="大小:").pack(side=tk.LEFT, padx=5)
        self.watermark_size_var = tk.IntVar(value=36)
        self.font_size_spin = ttk.Spinbox(wm_size_row, from_=6, to=200, textvariable=self.watermark_size_var, width=5)
        self.font_size_spin.pack(side=tk.LEFT, padx=2)

        ttk.Label(wm_size_row, text="透明度:").pack(side=tk.LEFT, padx=5)
        self.watermark_opacity_var = tk.IntVar(value=80)
        ttk.Scale(wm_size_row, from_=0, to=100, variable=self.watermark_opacity_var, orient=tk.HORIZONTAL, length=80).pack(side=tk.LEFT, padx=2)
        self.watermark_opacity_label = ttk.Label(wm_size_row, text="80%", width=4)
        self.watermark_opacity_label.pack(side=tk.LEFT, padx=2)

        ttk.Label(wm_size_row, text="颜色:").pack(side=tk.LEFT, padx=(5, 2))
        self.choose_color_btn = ttk.Button(wm_size_row, text="选色", command=self.choose_color, width=5)
        self.choose_color_btn.pack(side=tk.LEFT, padx=2)
        self.color_preview = tk.Canvas(wm_size_row, width=20, height=20, bg="#FFFFFF", bd=1, relief=tk.SUNKEN)
        self.color_preview.pack(side=tk.LEFT, padx=2)

        ttk.Label(wm_size_row, text="边框:").pack(side=tk.LEFT, padx=(5, 2))
        self.watermark_border_var = tk.IntVar(value=0)
        ttk.Spinbox(wm_size_row, from_=0, to=20, textvariable=self.watermark_border_var, width=5).pack(side=tk.LEFT, padx=2)

        ttk.Label(wm_size_row, text="边框色:").pack(side=tk.LEFT, padx=(5, 2))
        self.border_color_preview = tk.Canvas(wm_size_row, width=20, height=20, bg="#000000", bd=1, relief=tk.SUNKEN)
        self.border_color_preview.pack(side=tk.LEFT, padx=2)
        ttk.Button(wm_size_row, text="选色", command=self.choose_border_color, width=5).pack(side=tk.LEFT, padx=2)

        # 第三行（位置/旋转/平铺/间距）
        wm_row2 = ttk.Frame(self.watermark_frame)
        wm_row2.pack(fill=tk.X, pady=2, padx=5)

        positions = ["左上", "上", "右上", "左中", "中", "右中", "左下", "下", "右下"]
        for pos in positions:
            btn = ttk.Button(wm_row2, text=pos, width=4,
                             command=lambda p=pos: self.watermark_pos_var.set(p))
            btn.pack(side=tk.LEFT, padx=2)

        ttk.Label(wm_row2, text="旋转:").pack(side=tk.LEFT, padx=(2,2))
        angle_spin = ttk.Spinbox(wm_row2, from_=0, to=360, textvariable=self.watermark_angle_var, width=5)
        angle_spin.pack(side=tk.LEFT, padx=2)

        tile_check = ttk.Checkbutton(wm_row2, text="平铺", variable=self.watermark_tile_var)
        tile_check.pack(side=tk.LEFT, padx=5)
        ttk.Label(wm_row2, text="水平间距:").pack(side=tk.LEFT, padx=(2,2))
        gap_x_spin = ttk.Spinbox(wm_row2, from_=0, to=500, textvariable=self.watermark_gap_x_var, width=5)
        gap_x_spin.pack(side=tk.LEFT, padx=2)
        ttk.Label(wm_row2, text="垂直间距:").pack(side=tk.LEFT, padx=(2,2))
        gap_y_spin = ttk.Spinbox(wm_row2, from_=0, to=500, textvariable=self.watermark_gap_y_var, width=5)
        gap_y_spin.pack(side=tk.LEFT, padx=2)

        self.format_var.trace_add('write', self._on_format_changed)

    def _safe_get_int(self, var, default=0):
        try:
            val = var.get()
            if val == '':
                return default
            return int(val)
        except (tk.TclError, ValueError):
            return default

    def _on_quality_changed(self, *args):
        fmt = self.format_var.get()
        if fmt != "WEBP":
            return
        try:
            val = int(self.quality_var.get())
        except:
            return
        if val == 101:
            self.quality_label.config(text="无损:")
        else:
            self.quality_label.config(text="质量:")

    def _on_format_changed(self, *args):
        fmt = self.format_var.get()
        if fmt == "ICO":
            self.quality_label.pack_forget()
            self.quality_scale.pack_forget()
            self.quality_spin.pack_forget()
            self.ico_size_btn.pack(side=tk.LEFT, padx=2)
            self._on_settings_changed()
            return

        self.ico_size_btn.pack_forget()
        self.quality_label.pack(side=tk.LEFT, padx=(10,2))
        self.quality_scale.pack(side=tk.LEFT, padx=2)
        self.quality_spin.pack(side=tk.LEFT, padx=2)

        if fmt == "WEBP":
            self.quality_label.config(text="质量:")
            self.quality_scale.config(from_=1, to=101)
            self.quality_spin.config(from_=1, to=101)
            self._on_quality_changed()
        elif fmt == "PNG":
            self.quality_label.config(text="压缩:")
            self.quality_scale.config(from_=9, to=0)
            self.quality_spin.config(from_=0, to=9)
            self.quality_scale.config(state=tk.NORMAL)
        else:
            self.quality_label.config(text="质量:")
            self.quality_scale.config(from_=1, to=100)
            self.quality_spin.config(from_=1, to=100)
            self.quality_scale.config(state=tk.NORMAL)

        if getattr(self, '_loading_preset', False):
            self._on_settings_changed()
            return

        config = FORMAT_CONFIG.get(fmt, {})
        q_range = config.get('quality_range')
        default_q = config.get('default_quality')
        if q_range is not None:
            if fmt == "WEBP" and self.quality_var.get() == 101:
                pass
            else:
                new_val = default_q if default_q is not None else q_range[0]
                self.quality_var.set(new_val)

        self._on_settings_changed()

    def _edit_ico_sizes(self):
        dlg = Toplevel(self)
        dlg.title("编辑 ICO 尺寸")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("300x250")
        center_window(self, dlg)

        current_sizes = self._ico_sizes.copy()

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

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        def add_size():
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

    def choose_border_color(self):
        from tkinter import colorchooser
        initial = self.watermark_border_color_var.get() or "#000000"
        color = colorchooser.askcolor(title="选择描边颜色", initialcolor=initial)
        if color and color[1]:
            hex_color = color[1]
            self.watermark_border_color_var.set(hex_color)
            self.border_color_preview.config(bg=hex_color)

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
            self.sharpen_enable, self.sharpen_var,
            self.preview_size_var,
        ]
        if self.include_exif_date_delete:
            vars_list.extend([self.keep_exif_var, self.preserve_date_var, self.delete_original_var])

        watermark_vars = [
            self.watermark_enable,
            self.watermark_text_var,
            self.watermark_font_var,
            self.watermark_size_var,
            self.watermark_pos_var,
            self.watermark_opacity_var,
            self.watermark_color_var,
            self.watermark_angle_var,
            self.watermark_tile_var,
            self.watermark_gap_x_var,
            self.watermark_gap_y_var,
            self.watermark_ext_font_var,
            self.watermark_border_var,
            self.watermark_border_color_var,
        ]
        vars_list.extend(watermark_vars)

        self.quality_var.trace_add('write', self._on_quality_changed)

        for var in vars_list:
            var.trace_add('write', lambda *a: self._on_settings_changed())

        self.brightness_var.trace_add('write', lambda *a: self.brightness_label.config(text=str(self.brightness_var.get())))
        self.contrast_var.trace_add('write', lambda *a: self.contrast_label.config(text=str(self.contrast_var.get())))
        self.saturation_var.trace_add('write', lambda *a: self.saturation_label.config(text=str(self.saturation_var.get())))
        self.sharpen_var.trace_add('write', lambda *a: self.sharpen_label.config(text=str(self.sharpen_var.get())))
        self.r_var.trace_add('write', lambda *a: self.r_label.config(text=str(self.r_var.get())))
        self.g_var.trace_add('write', lambda *a: self.g_label.config(text=str(self.g_var.get())))
        self.b_var.trace_add('write', lambda *a: self.b_label.config(text=str(self.b_var.get())))
        self.watermark_opacity_var.trace_add('write', lambda *a: self.watermark_opacity_label.config(text=f"{self.watermark_opacity_var.get()}%"))
        self.watermark_border_color_var.trace_add('write', lambda *a: self.border_color_preview.config(bg=self.watermark_border_color_var.get()))
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
            'quality': self._safe_get_int(self.quality_var, 85),
            'rotation': self.rotation_var.get(),
            'h_flip': self.h_flip_var.get(),
            'v_flip': self.v_flip_var.get(),
            'resize_mode': self.resize_mode_var.get(),
            'resize_w': self._safe_get_int(self.resize_width_var, 800),
            'resize_h': self._safe_get_int(self.resize_height_var, 600),
            'crop_enabled': self.crop_enabled_var.get(),
            'crop_x': self.crop_x_var.get(),
            'crop_y': self.crop_y_var.get(),
            'crop_w': self.crop_w_var.get(),
            'crop_h': self.crop_h_var.get(),
            'brightness_enable': self.brightness_enable.get(),
            'brightness_val': self._safe_get_int(self.brightness_var, 0),
            'contrast_enable': self.contrast_enable.get(),
            'contrast_val': self._safe_get_int(self.contrast_var, 0),
            'color_enable': self.color_enable.get(),
            'r_gain': self._safe_get_int(self.r_var, 0),
            'g_gain': self._safe_get_int(self.g_var, 0),
            'b_gain': self._safe_get_int(self.b_var, 0),
            'saturation_enable': self.saturation_enable.get(),
            'saturation_val': self._safe_get_int(self.saturation_var, 0),
            'sharpen_enable': self.sharpen_enable.get(),
            'sharpen_val': self._safe_get_int(self.sharpen_var, 0),
            'watermark_enable': self.watermark_enable.get(),
            'watermark_text': self.watermark_text_var.get(),
            'watermark_font': self.watermark_font_var.get(),
            'watermark_size': self._safe_get_int(self.watermark_size_var, 36),
            'watermark_position': self.watermark_pos_var.get(),
            'watermark_opacity': self._safe_get_int(self.watermark_opacity_var, 80),
            'preview_size': self._safe_get_int(self.preview_size_var, 600),
            'ico_sizes': self._ico_sizes.copy(),
            'watermark_angle': self._safe_get_int(self.watermark_angle_var, 0),
            'watermark_tile': self.watermark_tile_var.get(),
            'watermark_gap_x': self._safe_get_int(self.watermark_gap_x_var, 50),
            'watermark_gap_y': self._safe_get_int(self.watermark_gap_y_var, 50),
            'watermark_ext_font': self.watermark_ext_font_var.get(),
            'watermark_border': self._safe_get_int(self.watermark_border_var, 0),
            'watermark_border_color': self.watermark_border_color_var.get(),
        }
        settings['watermark_color'] = self.watermark_color_var.get()
        # 记录用过的外部字体到 fonts_cache.json（与 safe5 对齐；浏览/手填都记）
        try:
            record_external_font(self.watermark_ext_font_var.get())
        except Exception:
            pass

        if self.include_exif_date_delete:
            settings.update({
                'keep_exif': self.keep_exif_var.get(),
                'preserve_original_date': self.preserve_date_var.get(),
                'delete_original': self.delete_original_var.get(),
            })
        return settings

    def set_settings(self, settings):
        self._loading_preset = True
        try:
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
            self.watermark_enable.set(settings.get('watermark_enable', False))
            self.watermark_text_var.set(settings.get('watermark_text', 'Watermark'))
            self.watermark_font_var.set(settings.get('watermark_font', 'Arial'))
            self.watermark_size_var.set(settings.get('watermark_size', 36))
            self.watermark_pos_var.set(settings.get('watermark_position', '右下'))
            self.watermark_opacity_var.set(settings.get('watermark_opacity', 80))
            self.preview_size_var.set(settings.get('preview_size', 600))
            self.watermark_angle_var.set(settings.get('watermark_angle', 0))
            self.watermark_tile_var.set(settings.get('watermark_tile', False))
            self.watermark_gap_x_var.set(settings.get('watermark_gap_x', 50))
            self.watermark_gap_y_var.set(settings.get('watermark_gap_y', 50))
            self.watermark_ext_font_var.set(settings.get('watermark_ext_font', ''))
            self.watermark_border_var.set(settings.get('watermark_border', 0))
            self.watermark_border_color_var.set(settings.get('watermark_border_color', '#000000'))
            self.watermark_color_var.set(settings.get('watermark_color', '#FFFFFF'))
            if hasattr(self, 'color_preview'):
                self.color_preview.config(bg=self.watermark_color_var.get())
            if hasattr(self, 'border_color_preview'):
                self.border_color_preview.config(bg=self.watermark_border_color_var.get())
            if self.include_exif_date_delete:
                self.keep_exif_var.set(settings.get('keep_exif', False))
                self.preserve_date_var.set(settings.get('preserve_original_date', False))
                self.delete_original_var.set(settings.get('delete_original', False))
            ico_sizes = settings.get('ico_sizes')
            if ico_sizes and isinstance(ico_sizes, list):
                self._ico_sizes = [tuple(s) for s in ico_sizes if isinstance(s, (tuple, list)) and len(s)==2]

            # 强制更新显示状态，但此时 _loading_preset 为 True，会跳过默认值设置
            self._on_format_changed()
            self._on_resize_mode_changed()
            self._update_enhance_enable()
            self._on_settings_changed()
        finally:
            self._loading_preset = False   # 结束加载预设


class ImageConverter(TkinterDnD.Tk):
    # 列宽配置（可自行调整）
    COL_WIDTHS = {
        'orig': 60,
        'size': 90,
        'out': 300,
        'params': 250,
        'status': 60
    }

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
        
        self.canvas_padding = 10         #预览画布四周的空白边距（像素）

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
        self.context_menu.add_separator()
        self.context_menu.add_command(label="恢复列宽", command=self.reset_column_widths)


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
            'angle': settings.get('watermark_angle', 0),
            'tile': settings.get('watermark_tile', False),
            'gap_x': settings.get('watermark_gap_x', 50),
            'gap_y': settings.get('watermark_gap_y', 50),
            'ext_font': settings.get('watermark_ext_font', ''),
            'border': settings.get('watermark_border', 0),
            'border_color': settings.get('watermark_border_color', '#000000'),
        }
        img = self.draw_watermark(img, watermark_settings)
        return img

    def _apply_all_transforms_up_to_crop(self, img, settings):
        angle = int(settings['rotation'].rstrip('°'))
        if angle != 0:
            img = img.rotate(angle, expand=True, resample=Image.LANCZOS)
        if settings['h_flip']:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if settings['v_flip']:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        return img

    def set_visual_crop_callback(self, callback):
        self.visual_crop_callback = callback

    def on_visual_crop(self):
        if self.visual_crop_callback:
            self.visual_crop_callback()
        else:
            messagebox.showinfo("提示", "可视化裁剪功能未就绪")

    def visual_crop_mode(self, task=None, on_finish=None):
        """
        可视化裁剪模式（预览画布已带10px边距，支持在已有裁剪基础上追加裁剪）
        """
        if task is None:
            task = self.current_preview_task
        if not task:
            messagebox.showwarning("警告", "没有当前预览的图片")
            if on_finish:
                on_finish()
            return

        editor = self.active_crop_editor if self.active_crop_editor is not None else self.template_editor
    
        # 获取当前裁剪参数作为基准偏移
        settings = editor.get_settings()
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
            base_x = max(0, min(base_x, full_w - 1))
            base_y = max(0, min(base_y, full_h - 1))
            base_w = min(base_w, full_w - base_x)
            base_h = min(base_h, full_h - base_y)
        else:
            base_x = base_y = 0
            base_w, base_h = full_w, full_h
    
        # 预览裁剪后的图像（基准区域）
        preview_settings = settings.copy()
        preview_settings['crop_enabled'] = True
        preview_settings['crop_x'] = str(base_x)
        preview_settings['crop_y'] = str(base_y)
        preview_settings['crop_w'] = str(base_w)
        preview_settings['crop_h'] = str(base_h)
    
        # 确保预览窗口存在并更新内容（画布已带边距）
        if not self.preview_window or not self.preview_window.winfo_exists():
            self._show_preview(task)
        self._update_preview_content(task, override_settings=preview_settings, sync=True)

        canvas = self.preview_canvas
        if not canvas:
            messagebox.showerror("错误", "预览画布不存在")
            if on_finish:
                on_finish()
            return
    
        # ---- 从画布获取边距和缩略图尺寸（由 __init__   self.canvas_padding = 10 设置） ----
        PADDING = getattr(canvas, 'padding', self.canvas_padding)
        thumb_w = getattr(canvas, 'thumb_w', canvas.winfo_width() - 2 * PADDING)
        thumb_h = getattr(canvas, 'thumb_h', canvas.winfo_height() - 2 * PADDING)
    
        # ---- 清除旧的辅助元素 ----
        canvas.delete("crop_guide")
        canvas.delete("crop_hint")
        canvas.delete("crop_rect")
    
        # ---- 比例尺：缩略图显示区域 → 基准区域 ----
        scale_x = base_w / thumb_w if thumb_w > 0 else 1
        scale_y = base_h / thumb_h if thumb_h > 0 else 1
    
        # ---- 显示提示文字（居中于画布） ----
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()
        # 计算画布中心坐标
        center_x = canvas_width // 2
        center_y = canvas_height // 2 - 20   # 稍微向上偏移一点，视觉更平衡
    
        hint = canvas.create_text(
            center_x, center_y,
            text="🖱 拖拽绘制裁剪区域\nShift: 保持正方形\n取消勾选可重置预览",
            font=("", 14, "bold"), fill="black", tags="crop_guide"
        )
        # 文字背景（半透明黑色衬底，提高可读性）
        bbox = canvas.bbox(hint)
        if bbox:
            canvas.create_rectangle(
                bbox[0]-15, bbox[1]-15, bbox[2]+15, bbox[3]+15,
                fill="white", outline="gray", width=1, tags="crop_hint"
            )
            canvas.tag_raise(hint)
    
        # ---- 坐标转换函数 ----
        def canvas_to_thumb(cx, cy):
            """将 canvas 坐标转为缩略图相对坐标，并钳制到 [0, thumb_w]×[0, thumb_h]"""
            dx = cx - PADDING
            dy = cy - PADDING
            dx = max(0, min(dx, thumb_w))
            dy = max(0, min(dy, thumb_h))
            return dx, dy

        def thumb_to_base(tx, ty):
            """缩略图相对坐标 → 基准区域坐标（整数）"""
            return int(tx * scale_x), int(ty * scale_y)
    
        # ---- 拖拽状态 ----
        self.rect_id = None
        self.start_thumb = None
    
        # ---- 鼠标事件处理 ----
        def on_mouse_down(event):
            # 清除提示文字（开始拖拽时隐藏）
            canvas.delete("crop_guide")
            canvas.delete("crop_hint")
            cx = canvas.canvasx(event.x)
            cy = canvas.canvasy(event.y)
            tx, ty = canvas_to_thumb(cx, cy)
            self.start_thumb = (tx, ty)
            canvas.delete("crop_rect")   # 清除旧矩形
    
        def on_mouse_move(event):
            if self.start_thumb is None:
                return
            cx = canvas.canvasx(event.x)
            cy = canvas.canvasy(event.y)
            cur_tx, cur_ty = canvas_to_thumb(cx, cy)
            sx, sy = self.start_thumb

            shift = bool(event.state & 0x0001)
            end_tx, end_ty = cur_tx, cur_ty
            if shift:
                dx = cur_tx - sx
                dy = cur_ty - sy
                size = max(abs(dx), abs(dy))
                end_tx = sx + (size if dx >= 0 else -size)
                end_ty = sy + (size if dy >= 0 else -size)
                end_tx = max(0, min(end_tx, thumb_w))
                end_ty = max(0, min(end_ty, thumb_h))
    
            # 绘制矩形（使用画布绝对坐标，加上 PADDING）
            x1 = min(sx, end_tx) + PADDING
            y1 = min(sy, end_ty) + PADDING
            x2 = max(sx, end_tx) + PADDING
            y2 = max(sy, end_ty) + PADDING

            if self.rect_id:
                canvas.coords(self.rect_id, x1, y1, x2, y2)
            else:
                self.rect_id = canvas.create_rectangle(
                    x1, y1, x2, y2, outline='red', width=2, dash=(4, 2), tags="crop_rect"
                )

        def on_mouse_up(event):
            if self.start_thumb is None:
                _cleanup()
                return
            cx = canvas.canvasx(event.x)
            cy = canvas.canvasy(event.y)
            cur_tx, cur_ty = canvas_to_thumb(cx, cy)
            sx, sy = self.start_thumb

            shift = bool(event.state & 0x0001)
            end_tx, end_ty = cur_tx, cur_ty
            if shift:
                dx = cur_tx - sx
                dy = cur_ty - sy
                size = max(abs(dx), abs(dy))
                end_tx = sx + (size if dx >= 0 else -size)
                end_ty = sy + (size if dy >= 0 else -size)
                end_tx = max(0, min(end_tx, thumb_w))
                end_ty = max(0, min(end_ty, thumb_h))
    
            # 计算缩略图上的相对矩形
            x1 = min(sx, end_tx)
            y1 = min(sy, end_ty)
            x2 = max(sx, end_tx)
            y2 = max(sy, end_ty)
    
            # 映射到基准区域坐标
            rel_x, rel_y = thumb_to_base(x1, y1)
            rel_w = int((x2 - x1) * scale_x)
            rel_h = int((y2 - y1) * scale_y)
    
            # 转换为绝对坐标（相对于完整图像）
            final_x = base_x + rel_x
            final_y = base_y + rel_y
            final_w = rel_w
            final_h = rel_h
    
            # 边界保护（防止超出完整图像）
            final_x = max(0, min(final_x, full_w - 1))
            final_y = max(0, min(final_y, full_h - 1))
            final_w = max(1, min(final_w, full_w - final_x))
            final_h = max(1, min(final_h, full_h - final_y))
    
            # 回写编辑器
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
            canvas.delete("crop_guide")
            canvas.delete("crop_rect")
            canvas.delete("crop_hint")
            self.rect_id = None
            self.start_thumb = None
    
        # ---- 绑定事件 ----
        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_move)
        canvas.bind("<ButtonRelease-1>", on_mouse_up)

    def _build_output_path(self, task, out_dir):
        # 优先使用任务自身的输出目录
        task_out_dir = task.get('output_dir')
        if task_out_dir and task_out_dir.strip():
            out_dir = task_out_dir.strip()
        # 如果 out_dir 为 None 或空，使用原文件目录
        if out_dir is None or out_dir == "":
            out_dir = os.path.dirname(task['path'])
        # 构建名称
        name_or_path = self.build_output_name(task['name_template'], task['path'])
        fmt = task['format']
        if fmt == "保持原格式":
            ext = os.path.splitext(task['path'])[1].lower()
        else:
            ext = self._get_output_extension(fmt)
        if "{Original}" in task['name_template']:
            base_path = name_or_path + ext
        else:
            base_path = os.path.join(out_dir, name_or_path + ext)
        return base_path

    def _get_font(self, font_name, font_size, ext_font=""):
        key = (font_name, font_size, ext_font)
        if key in self.font_cache:
            return self.font_cache[key]

        font = None
        # 外部字体优先（参考 safe5 的文字水印功能）
        if ext_font and os.path.exists(ext_font):
            try:
                font = ImageFont.truetype(ext_font, font_size)
            except Exception as e:
                print(f"加载外部字体失败: {e}")
                font = None

        if font is None:
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
                actual_fmt = 'JPEG'
            config = FORMAT_CONFIG.get(actual_fmt)
        else:
            config = self._get_format_config(fmt)

        if not config:
            return {}

        save_params = {}
        quality_range = config.get('quality_range')

        if quality_range is not None:
            min_q, max_q = quality_range
            q_clamped = max(min_q, min(max_q, quality))

            for key, val in config['save_params'].items():
                if key == 'quality':
                    save_params['quality'] = q_clamped
                elif key == 'compress_level':
                    save_params['compress_level'] = q_clamped
                else:
                    save_params[key] = val
        else:
            save_params.update(config['save_params'])

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
        return None


    #-----水印----
    def draw_watermark(self, img, watermark_settings):
        if not watermark_settings.get('enable', False):
            return img
        text = watermark_settings.get('text', '')
        if not text:
            return img

        import PIL as _PIL
        _PIL_STROKE_OK = tuple(int(x) for x in _PIL.__version__.split('.')[:2]) >= (9, 2)

        font_name = watermark_settings.get('font', 'Arial')
        font_size = watermark_settings.get('size', 36)
        opacity = watermark_settings.get('opacity', 80) / 100.0
        color_hex = watermark_settings.get('color', '#FFFFFF')
        angle = watermark_settings.get('angle', 0)
        tile = watermark_settings.get('tile', False)
        ext_font = watermark_settings.get('ext_font', '')
        border = int(watermark_settings.get('border', 0) or 0)
        border_color_hex = (watermark_settings.get('border_color', '#000000') or '#000000').lstrip('#')

        if opacity <= 0:
            return img
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        w, h = img.size

        color_hex = color_hex.lstrip('#')
        r = int(color_hex[0:2], 16); g = int(color_hex[2:4], 16); b = int(color_hex[4:6], 16)
        alpha = int(255 * opacity)
        if len(border_color_hex) >= 6:
            br = int(border_color_hex[0:2], 16); bg = int(border_color_hex[2:4], 16); bb = int(border_color_hex[4:6], 16)
        else:
            br, bg, bb = 0, 0, 0

        font = self._get_font(font_name, font_size, ext_font)

        import math
        bbox = ImageDraw.Draw(Image.new('RGBA', (1, 1))).textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        _stroke_kwargs = {}
        if border > 0 and _PIL_STROKE_OK:
            _stroke_kwargs = {'stroke_width': border, 'stroke_fill': (br, bg, bb, alpha)}

        def _render(canvas_size):
            """在给定画布上居中绘制水印文字（单元内保持水平），返回 RGBA 图层"""
            cw, ch = canvas_size
            layer = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            d.text(((cw - tw) // 2, (ch - th) // 2), text, font=font,
                   fill=(r, g, b, alpha), **_stroke_kwargs)
            return layer

        if tile:
            # 平铺：旋转「整片图案」而非「每个字」，保证任意角度间距均匀。
            # 用「旋转网格」实现：把单个单元格（含文字与透明边距）整格旋转后，
            # 贴到按 angle 旋转的网格上 —— 视觉等价于整体旋转，但无需建巨型画布，
            # 单次渲染从 O(diag^2) 降到 O(图块数)，预览/大图大幅提速。
            gap_x = watermark_settings.get('gap_x', 50)
            gap_y = watermark_settings.get('gap_y', 50)
            tile_w, tile_h = tw + gap_x, th + gap_y
            cell = _render((tile_w, tile_h))                 # 单元格内文字水平
            if angle != 0:
                cell = cell.rotate(angle, expand=True, resample=Image.BICUBIC)
            bw, bh = cell.size
            cx, cy = w / 2.0, h / 2.0
            rad = math.radians(angle)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            # 旋转后的网格基向量（格距 = 单元格尺寸）。
            # 铁律：PIL rotate(+a) 是「逆时针」，即把 (1,0) 映射到 (cos, -sin)。
            # 网格矩阵必须与单元格旋转同向，否则文字长轴会平行于 v2（堆叠轴），
            # 相邻单元首尾重叠 -> 视觉上「融合成几条带」，且行距变成 tile_w。
            v1 = (cos_a * tile_w, -sin_a * tile_w)
            v2 = (sin_a * tile_h, cos_a * tile_h)
            # 通过图像四角反解所需 (i,j) 范围，保证整图被铺满（含旋转）
            min_i = min_j = float('inf')
            max_i = max_j = float('-inf')
            for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                dx, dy = sx * w / 2.0, sy * h / 2.0
                i_c = (cos_a * dx - sin_a * dy) / tile_w
                j_c = (sin_a * dx + cos_a * dy) / tile_h
                min_i, max_i = min(min_i, i_c), max(max_i, i_c)
                min_j, max_j = min(min_j, j_c), max(max_j, j_c)
            lo_i = int(math.floor(min_i)) - 1
            hi_i = int(math.ceil(max_i)) + 1
            lo_j = int(math.floor(min_j)) - 1
            hi_j = int(math.ceil(max_j)) + 1
            result = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            # 铁律：叠加单元格必须用 alpha_composite，绝不能用 paste(cell, box, cell)。
            # paste 以 cell 自身 alpha 为 mask 时，会把 alpha 同时乘进 RGB 和 A 两个
            # 通道 -> 透明度被「平方」（设 80% 实际只剩 ~39%），白水印发灰。
            # 实测：paste 后核心像素 (204,204,204,163)；alpha_composite 保持
            # (255,255,255,204)，合成到灰底128 得 230（理论 229.6）vs paste 的 177。
            for i in range(lo_i, hi_i + 1):
                for j in range(lo_j, hi_j + 1):
                    px = cx + i * v1[0] + j * v2[0]
                    py = cy + i * v1[1] + j * v2[1]
                    result.alpha_composite(cell, (int(px - bw / 2), int(py - bh / 2)))
            return Image.alpha_composite(img, result)

        # ---- 单位置（保留原逻辑，支持旋转）----
        wm_img = _render((tw, th))
        if angle != 0:
            wm_img = wm_img.rotate(angle, expand=True, resample=Image.BICUBIC)
            bb = wm_img.getbbox()
            if bb:
                pad = 5
                l, t, r, b = bb
                wm_img = wm_img.crop((max(0, l - pad), max(0, t - pad),
                                      min(wm_img.width, r + pad), min(wm_img.height, b + pad)))
        wm_w, wm_h = wm_img.size
        padding = max(5, min(30, int(min(w, h) * 0.03)))
        pos_map = {
            '左上': (padding, padding), '上': ((w - wm_w) // 2, padding),
            '右上': (w - wm_w - padding, padding), '左中': (padding, (h - wm_h) // 2),
            '中': ((w - wm_w) // 2, (h - wm_h) // 2), '右中': (w - wm_w - padding, (h - wm_h) // 2),
            '左下': (padding, h - wm_h - padding), '下': ((w - wm_w) // 2, h - wm_h - padding),
            '右下': (w - wm_w - padding, h - wm_h - padding),
        }
        position = watermark_settings.get('position', '右下')
        x, y = pos_map.get(position, (w - wm_w - padding, h - wm_h - padding))
        result = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        # 同 tile 分支铁律：用 alpha_composite，paste(wm_img, box, wm_img) 会把透明度平方
        result.alpha_composite(wm_img, (x, y))
        return Image.alpha_composite(img, result)

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
        sel = self.get_selected_indices()
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

        PADDING = self.canvas_padding

        def generate():
            try:
                if override_settings:
                    temp_task = task.copy()
                    temp_task.update(override_settings)
                    img_task = temp_task
                else:
                    img_task = task

                with Image.open(img_task['path']) as img:
                    # 全分辨率应用全部变换（含水印），再缩到预览尺寸。
                    # 实测：45° 细斜线经降采样后保留率 81~96%（NEAREST/BILINEAR/
                    # BICUBIC/LANCZOS 均如此），不会被抹掉。因此不要在缩略图分辨率
                    # 重画水印——那样字号/间距会被取整与钳位扭曲，密度失真反而更大。
                    preview_size = self.global_preview_size
                    img = self._apply_all_transforms(img, img_task)
                    img.thumbnail((preview_size, preview_size), Image.LANCZOS)
                    thumb_w, thumb_h = img.size

                    # ---- 创建带边距的画布 ----
                    canvas_w = thumb_w + 2 * PADDING
                    canvas_h = thumb_h + 2 * PADDING
                    win_w = canvas_w + 20      # 窗口额外边距
                    win_h = canvas_h + 70      # 状态栏高度
                    self.preview_window.geometry(f"{win_w}x{win_h}")
                    self.preview_canvas.config(width=canvas_w, height=canvas_h)
    
                    # 绘制图片（偏移 PADDING）
                    photo = ImageTk.PhotoImage(img)
                    self.preview_canvas.delete("all")
                    self.preview_canvas.create_image(PADDING, PADDING, anchor=tk.NW, image=photo, tags="preview_img")
                    self.preview_canvas.image = photo
    
                    # ---- 可选：绘制边距边界（辅助线） ----
                    self.preview_canvas.create_rectangle(
                        PADDING, PADDING, PADDING+thumb_w, PADDING+thumb_h,
                        outline="gray", dash=(2,2), tags="border"
                    )

                    orig_w = img_task.get('orig_w', 0)
                    orig_h = img_task.get('orig_h', 0)
                    orig_str = f"原始: {orig_w}x{orig_h}" if orig_w and orig_h else ""
                    status_text = f"预览完成 | 缩略图: {thumb_w}x{thumb_h}"
                    if orig_str:
                        status_text += f" | {orig_str}"
                    self.preview_status.config(text=status_text)
    
                    # 保存边距信息到 canvas（供可视化使用）
                    self.preview_canvas.padding = PADDING
                    self.preview_canvas.thumb_w = thumb_w
                    self.preview_canvas.thumb_h = thumb_h

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
            self.refresh_task_tree()
            messagebox.showinfo("撤销", "已恢复到上一次状态")
        else:
            messagebox.showinfo("提示", "没有更早的状态")

    # ---------- Treeview 相关方法 ----------
    def refresh_task_tree(self):
        self.task_tree.delete(*self.task_tree.get_children())
        for idx, task in enumerate(self.tasks):
            values = self._format_task_row(task)
            # 交替背景标签
            bg_tag = 'even' if idx % 2 == 0 else 'odd'
            # 格式标签
            fmt_tag = self._get_format_tag(task)
            # 如果有状态（如 ✓ 或 ✗），状态标签由 _update_task_item 管理，初始没有
            self.task_tree.insert('', tk.END, values=values, tags=(bg_tag, fmt_tag))
    
    def _get_format_tag(self, task):
        """根据任务中的格式返回对应的标签名，支持 '保持原格式' 时根据扩展名映射"""
        fmt = task.get('format', 'JPEG')
        
        # 如果格式是“保持原格式”，从原始文件路径中提取扩展名并映射
        if fmt == "保持原格式":
            ext = os.path.splitext(task['path'])[1].lower()
            # 扩展名 → 格式名称映射（只包含您关心的四种）
            ext_to_fmt = {
                '.jpg': 'JPEG',
                '.jpeg': 'JPEG',
                '.png': 'PNG',
                '.webp': 'WEBP',
                '.ico': 'ICO',
            }
            actual_fmt = ext_to_fmt.get(ext, 'OTHER')
        else:
            actual_fmt = fmt
        
        # 返回对应的标签名
        if actual_fmt == 'JPEG':
            return 'fmt_jpeg'
        elif actual_fmt == 'PNG':
            return 'fmt_png'
        elif actual_fmt == 'WEBP':
            return 'fmt_webp'
        elif actual_fmt == 'ICO':
            return 'fmt_ico'
        else:
            return 'fmt_other'

    def get_task_item(self, index):
        """根据索引获取 Treeview 的 item id"""
        children = self.task_tree.get_children()
        if 0 <= index < len(children):
            return children[index]
        return None

    def get_selected_indices(self):
        """返回当前选中的行索引列表"""
        items = self.task_tree.selection()
        indices = []
        for item in items:
            index = self.task_tree.index(item)
            if index is not None:
                indices.append(index)
        return indices

    def _format_task_row(self, task):
        """生成一行各列显示内容"""
        raw_filename = os.path.basename(task['path'])
        w = task.get('orig_w', 0)
        h = task.get('orig_h', 0)
        size_str = f"{w}x{h}" if w and h else "?"
        out_name = self.build_output_name(task['name_template'], task['path'])
        if task['format'] == "保持原格式":
            ext = os.path.splitext(task['path'])[1].lower()
        else:
            ext = self._get_output_extension(task['format'])
        out_full = out_name + ext
        out_filename = os.path.basename(out_full)

        rot = task['rotation']
        rot_display = {"0°":"无", "90°":"左90", "-90°":"右90", "180°":"180"}.get(rot, rot)
        flip_parts = []
        if task['h_flip']: flip_parts.append("H")
        if task['v_flip']: flip_parts.append("V")
        flip_str = "".join(flip_parts) if flip_parts else "无"
        mode = task['resize_mode']
        if mode == "精确 (WxH)":
            size_info = f"{task['resize_w']}x{task['resize_h']}"
        elif mode == "限制长边":
            size_info = f"长边{task['resize_w']}"
        elif mode == "限制短边":
            size_info = f"短边{task['resize_w']}"
        else:
            size_info = "原尺寸"
        crop_str = ""
        if task.get('crop_enabled', False):
            crop_str = f" 裁:{task['crop_x']},{task['crop_y']},{task['crop_w']},{task['crop_h']}"
        param_str = f"{task['format']} Q{task['quality']} {rot_display} {flip_str} {size_info}{crop_str}"
        if task.get('delete_original', False):
            param_str += " 删"
        status = ""  # 初始为空
        return (raw_filename, size_str, out_filename, param_str, status)

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
        """
        解析重复文件，返回 (待转换任务列表, 跳过的任务索引列表)
        逻辑：
        - 若任务自身设置了 duplicate_mode，则使用该模式。
        - 若任务未设置，则使用全局模式。
        - 所有 "询问" 模式统一处理，支持"全部应用"。
        """
        resolved = []
        skipped = []
        global_dup_mode = self.duplicate_mode_var.get()
        conflicts = []

        for idx, task in enumerate(tasks):
            task_dup_mode = task.get('duplicate_mode')
            if task_dup_mode is None:
                effective_mode = global_dup_mode
            else:
                effective_mode = task_dup_mode

            task_out_dir = task.get('output_dir')
            effective_out_dir = task_out_dir.strip() if task_out_dir and task_out_dir.strip() else out_dir
            base_out = self._build_output_path(task, effective_out_dir)

            if effective_mode == "询问":
                conflicts.append((idx, task, base_out))
                continue

            if effective_mode == "跳过":
                if os.path.exists(base_out):
                    skipped.append(idx)
                else:
                    task_copy = task.copy()
                    task_copy['out_path'] = base_out
                    resolved.append((task_copy, idx))
            elif effective_mode == "覆盖":
                task_copy = task.copy()
                task_copy['out_path'] = base_out
                resolved.append((task_copy, idx))
            elif effective_mode == "自动重命名":
                final_path = self._get_unique_filename(base_out, "自动重命名")
                task_copy = task.copy()
                task_copy['out_path'] = final_path
                resolved.append((task_copy, idx))
            else:
                final_path = self._get_unique_filename(base_out, "自动重命名")
                task_copy = task.copy()
                task_copy['out_path'] = final_path
                resolved.append((task_copy, idx))

        if conflicts:
            apply_to_all = None
            for idx, task, base_out in conflicts:
                if os.path.exists(base_out):
                    if apply_to_all is None:
                        result = self._ask_duplicate_action(base_out)
                        if result == "apply_overwrite":
                            apply_to_all = "overwrite"
                            task_copy = task.copy()
                            task_copy['out_path'] = base_out
                            resolved.append((task_copy, idx))
                        elif result == "apply_rename":
                            apply_to_all = "rename"
                            final_path = self._auto_rename_path(base_out)
                            task_copy = task.copy()
                            task_copy['out_path'] = final_path
                            resolved.append((task_copy, idx))
                        elif result == "apply_skip":
                            apply_to_all = "skip"
                            skipped.append(idx)
                        elif result == "overwrite":
                            task_copy = task.copy()
                            task_copy['out_path'] = base_out
                            resolved.append((task_copy, idx))
                        elif result == "rename":
                            final_path = self._auto_rename_path(base_out)
                            task_copy = task.copy()
                            task_copy['out_path'] = final_path
                            resolved.append((task_copy, idx))
                        elif result == "skip":
                            skipped.append(idx)
                        else:
                            task_copy = task.copy()
                            task_copy['out_path'] = base_out
                            resolved.append((task_copy, idx))
                    else:
                        if apply_to_all == "overwrite":
                            task_copy = task.copy()
                            task_copy['out_path'] = base_out
                            resolved.append((task_copy, idx))
                        elif apply_to_all == "rename":
                            final_path = self._auto_rename_path(base_out)
                            task_copy = task.copy()
                            task_copy['out_path'] = final_path
                            resolved.append((task_copy, idx))
                        elif apply_to_all == "skip":
                            skipped.append(idx)
                else:
                    task_copy = task.copy()
                    task_copy['out_path'] = base_out
                    resolved.append((task_copy, idx))

        return resolved, skipped

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

        self.template_container = ttk.LabelFrame(left_frame, text="当前模板（新任务将使用此设置）- 处理顺序: 旋转→翻转→裁剪→缩放→更多")
        self.template_container.pack(fill=tk.X, pady=5)

        self.template_editor = TemplateEditor(self.template_container, include_exif_date_delete=True, default_expanded=False)
        self.template_editor.pack(fill=tk.X, padx=5, pady=5)
        self.template_editor.bind_preview_callback(self.update_template_preview)
        def main_window_visual_crop():
            self.active_crop_editor = None
            self.visual_crop_mode()
        self.template_editor.set_visual_crop_callback(main_window_visual_crop)

        self.keep_exif_var = self.template_editor.keep_exif_var
        ToolTip(self.template_editor.visual_crop_btn,
            text="当前裁剪预览只供参考，裁剪数据作为模板应用到后续添加文件中。\n\n调整已有任务请使用右键编辑里的可视化。",
            wraplength=550)

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
        ttk.Label(row4, text="预设:").pack(side=tk.LEFT, padx=(10,2))
        self.preset_combo = ttk.Combobox(row4, state="readonly", width=16)
        self.preset_combo.pack(side=tk.LEFT, padx=2)
        self.load_preset_btn = ttk.Button(row4, text="加载", command=self.load_preset, width=6)
        self.load_preset_btn.pack(side=tk.LEFT, padx=2)
        self.save_preset_btn = ttk.Button(row4, text="保存", command=self.save_preset, width=6)
        self.save_preset_btn.pack(side=tk.LEFT, padx=2)
        self.delete_preset_btn = ttk.Button(row4, text="删除", command=self.delete_preset, width=6)
        self.delete_preset_btn.pack(side=tk.LEFT, padx=2)

        self.template_preview_label = ttk.Label(self.template_container, text="", relief="sunken")
        self.template_preview_label.pack(fill=tk.X, pady=5, padx=5)
        self.update_template_preview(self.template_editor.get_settings())

        # ---------- 任务列表（Treeview） ----------
        list_frame = ttk.LabelFrame(left_frame, text="转换任务（单击预览，右键编辑）")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        columns = ('orig', 'size', 'out', 'params', 'status')
        self.task_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=12)
        self.task_tree.heading('#0', text='')

        self.task_tree.heading('orig', text='来源')
        self.task_tree.heading('size', text='原始尺寸')
        self.task_tree.heading('out', text='输出')
        self.task_tree.heading('params', text='参数')
        self.task_tree.heading('status', text='状态')

        self.task_tree.column('orig', width=self.COL_WIDTHS['orig'], minwidth=40, anchor='w')
        self.task_tree.column('size', width=self.COL_WIDTHS['size'], minwidth=60, anchor='center')
        self.task_tree.column('out', width=self.COL_WIDTHS['out'], minwidth=100, anchor='w')
        self.task_tree.column('params', width=self.COL_WIDTHS['params'], minwidth=120, anchor='w')
        self.task_tree.column('status', width=self.COL_WIDTHS['status'], minwidth=50, anchor='center')

        # 配置交替行颜色
        self.task_tree.tag_configure('even', background='#f0f0f0')
        self.task_tree.tag_configure('odd', background='#ffffff')

        # 配置格式标签颜色（前景色）
        self.task_tree.tag_configure('fmt_jpeg', foreground='#0066CC')   # 蓝色
        self.task_tree.tag_configure('fmt_png', foreground='#008000')    # 绿色
        self.task_tree.tag_configure('fmt_webp', foreground='#800080')   # 紫色
        self.task_tree.tag_configure('fmt_ico', foreground='#FF8C00')    # 橙色
        self.task_tree.tag_configure('fmt_other', foreground='#000000')  # 黑色

        # 状态标签颜色（会覆盖格式颜色）
        self.task_tree.tag_configure('done', foreground='#00AA00')   # 亮绿色
        self.task_tree.tag_configure('error', foreground='#FF0000')  # 红色
        self.task_tree.tag_configure('skipped', foreground='#888888') # 灰色

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=scrollbar.set)
        self.task_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 统一右键处理
        self.task_tree.bind("<Button-3>", self.on_tree_right_click)
        self.task_tree.bind("<<TreeviewSelect>>", self.on_task_select)
        self.task_tree.bind("<Double-1>", self.on_double_click_edit)

        # 表头右键菜单（恢复列宽）
        self.header_menu = tk.Menu(self, tearoff=0)
        self.header_menu.add_command(label="恢复列宽", command=self.reset_column_widths)

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

        self.keep_exif_var = self.template_editor.keep_exif_var
        self.preserve_date_var = self.template_editor.preserve_date_var
        self.delete_original_var = self.template_editor.delete_original_var
        self.preserve_date_var.set(self.preserve_original_date)
        self.keep_exif_var.set(self.keep_exif)
        self.delete_original_var.set(self.delete_original)

    # ---------- 列宽恢复 ----------
    def reset_column_widths(self):
        for col, width in self.COL_WIDTHS.items():
            self.task_tree.column(col, width=width)

    # ---------- 统一右键处理 ----------
    def on_tree_right_click(self, event):
        """统一处理 Treeview 的右键单击（包含表头和行），保留多选状态"""
        if self.converting:
            return  # 转换过程中禁用右键
    
        region = self.task_tree.identify_region(event.x, event.y)
        if region == 'heading':
            # 表头区域 → 弹出列宽恢复菜单
            self.header_menu.post(event.x_root, event.y_root)
        else:
            # 行区域
            row_id = self.task_tree.identify_row(event.y)
            if row_id:
                # 如果该行不在当前选中集合中，则添加（不取消其他选中行）
                if row_id not in self.task_tree.selection():
                    self.task_tree.selection_add(row_id)
                # 延迟弹出菜单，让选中状态稳定
                self.after(10, lambda: self.context_menu.post(event.x_root, event.y_root))
            else:
                # 点击空白区域
                self.context_menu.post(event.x_root, event.y_root)

    # ---------- 模板预览 ----------
    def update_template_preview(self, settings=None):
        if settings is None:
            settings = self.template_editor.get_settings()
        if 'preview_size' in settings:
            self.global_preview_size = settings['preview_size']
        fmt = settings['format']
        qual = settings['quality']
        if fmt == "WEBP" and qual == 101:
            qual_display = "无损"
        else:
            qual_display = f"Q{qual}"
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
        fmt = settings.get('format', 'JPEG')
        if fmt == "保持原格式":
            ext = ".jpg"
        else:
            config = FORMAT_CONFIG.get(fmt, {})
            ext = config.get('extension', '.jpg')
        example_out = name_part + ext

        hint_text = self._get_quality_hint(settings)
        full_text = f"模板: {fmt} | {qual_display} | {rot_display} | {flip_str}{size_info}{crop_info} | 输出示例: {example_out}{hint_text}"
        self.template_preview_label.config(text=full_text)

    def _get_quality_hint(self, settings):
        fmt = settings.get('format')
        config = FORMAT_CONFIG.get(fmt, {})
        q_range = config.get('quality_range')
        if q_range is None:
            return ""
        min_q, max_q = q_range
        # 针对 WEBP 特殊提示
        if fmt == "WEBP":
            return f" (WEBP: {min_q}-{max_q}, 101=无损)"
        else:
            return f" ({fmt}: {min_q}-{max_q})"

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
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法添加新任务")
            return
        current = self.template_editor.get_settings()
        current.pop('preview_size', None)
        current['name_template'] = self.name_template_var.get()
        current['duplicate_mode'] = self.duplicate_mode_var.get()
        global_dir = self.output_dir.get().strip()
        if not global_dir or global_dir == '.':
            current['output_dir'] = None
        else:
            current['output_dir'] = os.path.normpath(global_dir)
        added = 0
        for fp in paths:
            try:
                with Image.open(fp) as img:
                    orig_w, orig_h = img.size
            except Exception:
                orig_w, orig_h = 0, 0
            task = {'path': fp, **current, 'orig_w': orig_w, 'orig_h': orig_h}
            self.tasks.append(task)
            added += 1
        if added > 0:
            self.refresh_task_tree()
            self.save_current_state_to_history()

    # ---------- 右键菜单命令 ----------
    def edit_selected_task(self):
        selection = self.get_selected_indices()
        if not selection:
            messagebox.showinfo("提示", "请先选中一个任务")
            return
        first_idx = selection[0]
        first_task = self.tasks[first_idx]
        self.edit_task_dialog(first_idx, first_task, selected_indices=selection)

    def on_double_click_edit(self, event=None):
        selection = self.get_selected_indices()
        if not selection:
            return
        idx = selection[0]
        task = self.tasks[idx]
        self.after(10, lambda: self.edit_task_dialog(idx, task,
                                                     selected_indices=selection if len(selection) > 1 else None))

    # ---------- 辅助函数 ----------
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
        dirname = os.path.dirname(file_path)
        folder_name = os.path.basename(dirname)
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        result = template
        result = result.replace("{Filename}", base_name)
        result = result.replace("{Folder name}", folder_name)
        result = result.replace("{Original}", dirname)
        result = os.path.normpath(result)
        return result

    # ---------- 拖放文件夹支持 ----------
    def on_drop(self, event):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法添加新任务")
            return

        raw_data = event.data.strip()
        if not raw_data:
            return

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

        if not cleaned:
            messagebox.showinfo("提示", "未检测到有效的文件或文件夹")
            return

        self.drop_target_unregister() if DND_AVAILABLE else None
        self.progress_label.config(text="正在扫描文件夹，请稍候...")
        self.update_idletasks()

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
            self.after(0, lambda: self._on_drop_scan_complete(cleaned, image_files))

        threading.Thread(target=scan_folders, daemon=True).start()

    def _on_drop_scan_complete(self, cleaned, image_files):
        if DND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.on_drop)

        if not image_files:
            self.progress_label.config(text="就绪")
            messagebox.showinfo("提示", "未检测到支持的图片")
            return

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
        center_window(self, dlg)
        dlg.deiconify()
        dlg.lift()
        dlg.focus_force()

        left_panel = ttk.Frame(dlg)
        left_panel.pack(fill=tk.X, padx=5, pady=0)

        editor = TemplateEditor(left_panel, include_exif_date_delete=True, default_expanded=True)
        editor.pack(fill=tk.X, pady=0)
        editor.set_settings(task)
        editor.preview_size_var.set(self.global_preview_size)
        current_edit_task = task.copy()

        def on_dlg_close():
            self.active_crop_editor = None
            dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", on_dlg_close)

        def start_visual_crop_with_release():
            dlg.grab_release()
            self.active_crop_editor = editor
            def finish_visual():
                dlg.grab_set()
                self.active_crop_editor = None
            self.visual_crop_mode(current_edit_task, on_finish=finish_visual)
        editor.set_visual_crop_callback(start_visual_crop_with_release)

        row_top = ttk.Frame(left_panel)
        row_top.pack(fill=tk.X, pady=(0,5))

        ttk.Label(row_top, text="输出名称模板:").pack(side=tk.LEFT, padx=5)
        name_var = tk.StringVar(value=task.get('name_template', '{Filename}'))
        name_combo = ttk.Combobox(row_top, textvariable=name_var,
                                  values=["{Filename}", "{Folder name}{Filename}", "{Original}/{Filename}", "{Folder name}_{Filename}", "{Original}/123/{Filename}", "{Folder name}/{Filename}", "{Original}/{Folder name}/{Filename}"],
                                  width=16)
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
        output_dir_entry.pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)

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

        preview_frame = ttk.LabelFrame(left_panel, text="详细输出预览")
        preview_frame.pack(fill=tk.X, pady=5, padx=5)
        preview_text = tk.Text(preview_frame, height=6, wrap=tk.WORD, bg='#f0f0f0', relief=tk.SUNKEN, font=("TkFixedFont", 9))
        preview_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        preview_text.config(state=tk.DISABLED)

        btn_frame = ttk.Frame(left_panel)
        btn_frame.pack(fill=tk.X, pady=10)

        def adjust_dialog_height():
            dlg.update_idletasks()
            total_height = 0
            for child in left_panel.winfo_children():
                total_height += child.winfo_reqheight()
            decoration = 40
            new_height = total_height + decoration
            if new_height < 280:
                new_height = 280
            cur_width = dlg.winfo_width()
            cur_x = dlg.winfo_x()
            cur_y = dlg.winfo_y()
            dlg.geometry(f"{cur_width}x{new_height}+{cur_x}+{cur_y}")
            dlg.update_idletasks()

        original_toggle = editor._toggle_enhance

        def toggle_with_resize():
            original_toggle()
            dlg.after(20, adjust_dialog_height)

        editor.toggle_btn.config(command=toggle_with_resize)
        editor._toggle_enhance = toggle_with_resize
        dlg.after(20, adjust_dialog_height)

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
                orig_w = task.get('orig_w', 0)
                orig_h = task.get('orig_h', 0)
                size_str = f" ({orig_w}x{orig_h})" if orig_w and orig_h else " (尺寸未知)"
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
                    f"原文件: {src_path_disp}{size_str}",
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

        on_any_change()
        dlg.after(30, adjust_dialog_height)

        def save_single():
            new_settings = editor.get_settings()
            new_settings.pop('preview_size', None)
            new_settings['name_template'] = name_var.get()
            new_settings['duplicate_mode'] = dup_var.get()
            new_settings['output_dir'] = output_dir_var.get().strip() or None
            task.update(new_settings)
            self.refresh_task_tree()
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
            self.refresh_task_tree()
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

        def get_from_main():
            # 反向操作：把主窗口模板的参数取回到当前任务编辑器
            main_settings = self.template_editor.get_settings()
            main_settings.pop('preview_size', None)
            editor.set_settings(main_settings)
            # 名称模板 / 重名处理 / 输出目录 同步主窗口当前值
            if hasattr(self, 'name_template_var'):
                name_var.set(self.name_template_var.get())
            if hasattr(self, 'duplicate_mode_var'):
                dup_var.set(self.duplicate_mode_var.get())
            if hasattr(self, 'output_dir'):
                output_dir_var.set(self.output_dir.get())
            on_any_change()
            messagebox.showinfo("获取完成", "已获取主窗口模板参数到当前（含输出目录）")

        is_multi = selected_indices is not None and len(selected_indices) > 1
        if not is_multi:
            ttk.Button(btn_frame, text="保存", command=save_single).pack(side=tk.LEFT, padx=10)
        else:
            ttk.Button(btn_frame, text="仅保存当前任务", command=save_single).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text=f"应用到所有 {len(selected_indices)} 个任务", command=save_batch).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=on_dlg_close).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="同步当前参数到主窗口", command=sync_to_main).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="获取主窗口参数到当前", command=get_from_main).pack(side=tk.LEFT, padx=5)

    # ---------- 任务管理 ----------
    def remove_selected(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法删除任务")
            return
        for i in reversed(self.get_selected_indices()):
            del self.tasks[i]
        self.refresh_task_tree()
        self.save_current_state_to_history()

    def clear_tasks(self):
        if self.converting:
            messagebox.showwarning("警告", "转换进行中，无法清空列表")
            return
        self.tasks.clear()
        self.refresh_task_tree()
        self.progress_var.set(0)
        self.progress_label.config(text="就绪")
        self.save_current_state_to_history()

    def cancel_convert_func(self):
        if self.converting:
            self.cancel_convert = True
            self.progress_label.config(text="正在取消...")
            self.cancel_btn.config(state=tk.DISABLED)

    # ---------- 预设功能 ----------
    def load_presets_list(self):
        names = list(self.presets.keys())
        self.preset_combo['values'] = names
        if names:
            self.preset_combo.set(names[0])
        else:
            self.preset_combo.set('')

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
        try:
            if 'output_dir' in p:
                self.output_dir.set(os.path.normpath(p['output_dir']))
            self.template_editor.set_settings(p)
            if 'name_template' in p:
                self.name_template_var.set(p['name_template'])
            if 'duplicate_mode' in p:
                self.duplicate_mode_var.set(p['duplicate_mode'])
        except Exception as e:
            messagebox.showerror("错误", f"加载预设失败: {e}")
            return
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

    # ---------- 多线程转换（优化版：后台预检查） ----------
    def _clear_task_status(self):
        """清除所有任务的状态列和状态标签，恢复格式颜色"""
        for idx, task in enumerate(self.tasks):
            item = self.get_task_item(idx)
            if not item:
                continue
            values = list(self.task_tree.item(item, 'values'))
            if values:
                values[-1] = ""  # 清空状态列
                bg_tag = 'even' if idx % 2 == 0 else 'odd'
                fmt_tag = self._get_format_tag(task)
                self.task_tree.item(item, values=values, tags=(bg_tag, fmt_tag))

    def start_convert(self):
        if self.converting:
            messagebox.showwarning("警告", "转换正在进行中，请稍后")
            return
        if not self.tasks:
            messagebox.showwarning("警告", "任务列表为空")
            return
    
        self._clear_task_status()
    
        # ========== 新增：计算输入总大小，重置输出总大小 ==========
        self.total_input_size = 0
        for task in self.tasks:
            if os.path.exists(task['path']):
                self.total_input_size += os.path.getsize(task['path'])
        self.total_output_size = 0
        # ========================================================
    
        self.start_btn.config(state=tk.DISABLED)
        self.enable_task_edit_buttons(False)
        self.progress_label.config(text="正在检查任务...")
        self.update_idletasks()
    
        threading.Thread(target=self._prepare_convert, daemon=True).start()

    def _prepare_convert(self):
        out_dir_input = self.output_dir.get().strip()
        out_dir = None if out_dir_input in ("", ".") else os.path.normpath(out_dir_input)

        resolved_items, skipped_indices = self.resolve_duplicate_paths(self.tasks, out_dir)

        dangerous_overwrite_with_delete = []
        dangerous_overwrite_no_delete = []
        for idx, task in enumerate(self.tasks):
            src_dir = os.path.dirname(os.path.normpath(task['path']))
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

        self.after(0, lambda: self._on_prepare_done(
            out_dir, resolved_items, skipped_indices,
            dangerous_overwrite_with_delete, dangerous_overwrite_no_delete
        ))

    def _on_prepare_done(self, out_dir, resolved_items, skipped_indices,
                         dangerous_overwrite_with_delete, dangerous_overwrite_no_delete):
        # 标记跳过的任务
        for idx in skipped_indices:
            item = self.get_task_item(idx)
            if item:
                # 获取当前标签，保留背景标签
                current_tags = list(self.task_tree.item(item, 'tags'))
                bg_tags = [tag for tag in current_tags if tag in ('even', 'odd')]
                # 添加跳过标签，移除格式标签
                new_tags = bg_tags + ['skipped']
                values = list(self.task_tree.item(item, 'values'))
                values[-1] = "⏭跳过"
                self.task_tree.item(item, values=values, tags=new_tags)

        if dangerous_overwrite_with_delete:
            msg = "❌ 安全保护：检测到以下任务将覆盖原文件的同时删除原文件，这会导致文件永久丢失！\n\n"
            for idx, task in dangerous_overwrite_with_delete[:10]:
                msg += f"• {os.path.basename(task['path'])}\n"
            if len(dangerous_overwrite_with_delete) > 10:
                msg += f"• ... 共 {len(dangerous_overwrite_with_delete)} 个任务\n"
            msg += "\n请将重名处理改为“自动重命名”或关闭“删除原文件”，或更改输出目录。"
            messagebox.showerror("严重错误", msg)
            self._reset_ui_after_prepare()
            return

        if dangerous_overwrite_no_delete:
            msg = "⚠️ 警告：检测到以下任务将直接覆盖原文件（原内容将被替换）。\n\n"
            for idx, task in dangerous_overwrite_no_delete[:10]:
                msg += f"• {os.path.basename(task['path'])}\n"
            if len(dangerous_overwrite_no_delete) > 10:
                msg += f"• ... 共 {len(dangerous_overwrite_no_delete)} 个任务\n"
            msg += "\n是否继续覆盖？如果不希望覆盖，请将重名处理改为“自动重命名”。"
            if not messagebox.askyesno("覆盖确认", msg, icon='warning'):
                self._reset_ui_after_prepare()
                return

        delete_count = sum(1 for task in self.tasks if task.get('delete_original', False))
        if delete_count:
            msg = f"检测到 {delete_count} 个任务开启了“删除原文件”选项。\n\n删除操作会将原文件移至回收站/废纸篓，不可恢复！\n\n是否继续转换？"
            if not messagebox.askyesno("确认删除", msg, icon='warning'):
                self._reset_ui_after_prepare()
                return

        if not resolved_items and not skipped_indices:
            messagebox.showinfo("提示", "没有需要转换的任务，且没有任务被跳过。\n请检查任务的重名处理模式设置。")
            self._reset_ui_after_prepare()
            return
        elif not resolved_items:
            self.progress_label.config(text="所有任务已跳过")
            self._reset_ui_after_prepare()
            return

        self._start_real_conversion(out_dir, resolved_items)

    def _start_real_conversion(self, out_dir, resolved_items):
        self.total_tasks = len(resolved_items)
        self.progress_bar['maximum'] = self.total_tasks
        self.progress_var.set(0)
        self.progress_label.config(text=f"0 / {self.total_tasks}")

        self.converting = True
        self.cancel_convert = False
        self.cancel_btn.config(state=tk.NORMAL)

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

    def _reset_ui_after_prepare(self):
        self.start_btn.config(state=tk.NORMAL)
        self.enable_task_edit_buttons(True)
        self.progress_label.config(text="就绪")
        self.cancel_btn.config(state=tk.DISABLED)
        self.converting = False

    def _poll_futures(self):
        if self.cancel_convert:
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
        item = self.get_task_item(idx)
        if not item:
            return
        # 获取当前标签，只保留背景标签（even/odd）
        current_tags = list(self.task_tree.item(item, 'tags'))
        bg_tags = [tag for tag in current_tags if tag in ('even', 'odd')]
        # 添加状态标签
        if success:
            status_tag = 'done'
            status_text = "✓"
        else:
            status_tag = 'error'
            status_text = f"✗ {error}" if error else "✗"
        # 更新状态列文本
        values = list(self.task_tree.item(item, 'values'))
        values[-1] = status_text
        # 最终标签 = 背景标签 + 状态标签（状态在最后，覆盖格式颜色）
        new_tags = bg_tags + [status_tag]
        self.task_tree.item(item, values=values, tags=new_tags)

    def _on_convert_finished(self):
        self.converting = False
        self.start_btn.config(state=tk.NORMAL)
        self.enable_task_edit_buttons(True)
        self.cancel_btn.config(state=tk.DISABLED)
        self.cancel_convert = False
        if self.executor:
            self.executor.shutdown(wait=False)
        success_count = 0
        for item in self.task_tree.get_children():
            values = self.task_tree.item(item, 'values')
            if values and values[-1] == "✓":
                success_count += 1
        msg = f"转换完成\n成功: {success_count}\n失败: {len(self.tasks)-success_count}\n输出目录: {self.output_dir.get()}"

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
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"

    def _find_font_file(self, font_name):
        font_map = {
            'Arial': 'arial.ttf',
            'Times New Roman': 'times.ttf',
            'Courier New': 'cour.ttf',
            'Verdana': 'verdana.ttf',
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
            '微软雅黑 Bold': 'msyhbd.ttc',
            'Arial Bold': 'arialbd.ttf',
            'Georgia': 'georgia.ttf',
            'Tahoma': 'tahoma.ttf',
            'Impact': 'impact.ttf',
        }

        filename = font_map.get(font_name)
        if not filename:
            filename = font_name.lower().replace(' ', '') + '.ttf'

        # ★ 用缓存的 文件名→路径 映射直接查表，免每次 os.listdir 扫字体目录
        # （这才是有用的缓存：原来只缓存族名，渲染时仍要扫目录，等于没省事）。
        file_map = get_font_file_map()
        _key = filename.lower()
        if _key in file_map:
            return file_map[_key]
        # 同根 .ttc / .otf 兜底
        _stem = os.path.splitext(filename)[0].lower()
        for _ext in ('.ttc', '.otf', '.ttf'):
            _alt = _stem + _ext
            if _alt in file_map:
                return file_map[_alt]

        # 兜底：缓存未覆盖（极少见，如目录变了但缓存尚未过期）→ 仍按原目录扫描
        import platform
        system = platform.system()
        if system == 'Windows':
            windir = os.environ.get('WINDIR', 'C:/Windows')
            font_dirs = [os.path.join(windir, 'Fonts'), 'C:/Windows/Fonts']
        elif system == 'Darwin':
            font_dirs = ['/System/Library/Fonts', '/Library/Fonts']
        else:
            font_dirs = ['/usr/share/fonts/truetype', '/usr/local/share/fonts']
        for font_dir in font_dirs:
            if not os.path.isdir(font_dir):
                continue
            candidate = os.path.join(font_dir, filename)
            if os.path.exists(candidate):
                return candidate
            try:
                for f in os.listdir(font_dir):
                    if f.lower() == filename.lower():
                        return os.path.join(font_dir, f)
            except OSError:
                continue
            if filename.endswith('.ttf'):
                ttc_name = filename[:-4] + '.ttc'
                if os.path.exists(os.path.join(font_dir, ttc_name)):
                    return os.path.join(font_dir, ttc_name)
        return None

    def _convert_single(self, task, out_dir, original_idx):
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
                # 如果格式为 WEBP 且质量101
                if fmt == "WEBP" and qual == 101:
                    # 使用无损模式
                    save_params = self._prepare_save_params(fmt, 100, original_path_for_config)  # 传入100避免钳制
                    save_params['lossless'] = True
                    save_params['quality'] = 100
                else:
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
