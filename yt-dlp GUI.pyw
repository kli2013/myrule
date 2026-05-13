#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import sqlite3
import re
import time
import shutil
import threading
import configparser
import ctypes
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ==================== 隐藏 GUI 自身的控制台 ====================
if sys.platform == 'win32':
    try:
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except:
        pass

#-----提示类-----
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

        # Clamp 坐标到屏幕内
        x = max(0, min(ideal_x, screen_width - win_width))
        y = max(0, min(ideal_y, screen_height - win_height))

        # 防止窗口遮挡鼠标（可选增强）
        if x <= mouse_x <= x + win_width and y <= mouse_y <= y + win_height:
            # 简单反方向偏移 10 像素
            dx = 10 if ideal_x < screen_width // 2 else -10
            dy = 10 if ideal_y < screen_height // 2 else -10
            x = max(0, min(ideal_x + dx, screen_width - win_width))
            y = max(0, min(ideal_y + dy, screen_height - win_height))

        tw.wm_geometry(f"+{x}+{y}")

    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

# ==================== 常量定义 ====================
DEFAULT_CACHE_DIR = Path(r"C:\ffmpeg")
DEFAULT_DB_PATH = DEFAULT_CACHE_DIR / "downloaded.db"

DEFAULT_ARCHIVE_PATH = DEFAULT_CACHE_DIR / "ytdl_archive_log.txt"

# ==================== 语音提示 ====================
def speak(message):
    safe_msg = message.replace('"', '`"')
    script = f'Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak("{safe_msg}")'
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-NoProfile", "-Command", script],
            capture_output=True, startupinfo=startupinfo, timeout=5
        )
    except Exception:


        pass

# ==================== 核心下载类 ====================
class DownloaderCore:
    def __init__(self, log_callback=None, db_path=None, archive_path=None):
        self.log_callback = log_callback
        self.db_path = str(db_path) if db_path else str(DEFAULT_DB_PATH)
        self.archive_path = archive_path
        self.conn = None
        self.cursor = None
        self.init_database()
        if self.archive_path:
            Path(self.archive_path).parent.mkdir(parents=True, exist_ok=True)

        # ----- 中断控制 -----
        self.stop_event = threading.Event()     # 停止标志（线程安全）
        self.current_process = None             # 当前运行的 yt-dlp 进程

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)

    def init_database(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS urls (
                    vid TEXT PRIMARY KEY,
                    full_url TEXT,
                    download_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.cursor.execute("PRAGMA table_info(urls)")
            cols = [c[1] for c in self.cursor.fetchall()]
            if "download_time" not in cols:
                self.cursor.execute("ALTER TABLE urls ADD COLUMN download_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            self.conn.commit()
            self.log("数据库初始化成功。")
        except Exception as e:
            self.log(f"警告：数据库初始化失败 ({e})，写入功能不可用。")
            self.conn = None

    def extract_video_id(self, url):
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11})(?:[?&]|$)',
            r'youtu\.be\/([0-9A-Za-z_-]{11})',
            r'shorts\/([0-9A-Za-z_-]{11})',
            r'embed\/([0-9A-Za-z_-]{11})',
        ]
        for pat in patterns:
            m = re.search(pat, url)
            if m:
                return m.group(1)
        return None

    def clean_url(self, url):
        if re.search(r'youtube\.com|youtu\.be', url, re.I):
            return re.sub(r'&.*$', '', url)
        return url

    def mark_downloaded(self, vid, full_url):
        """先查询数据库是否存在该vid，若存在则输出提示，否则插入新记录"""
        if self.conn is None or not vid:
            return
        try:
            self.cursor.execute("SELECT 1 FROM urls WHERE vid = ?", (vid,))
            exists = self.cursor.fetchone() is not None
            if exists:
                self.log(f"数据库已存在视频ID [{vid}]，跳过录入。")
            else:
                self.cursor.execute(
                    "INSERT INTO urls (vid, full_url, download_time) VALUES (?, ?, datetime('now', 'localtime'))",
                    (vid, full_url)
                )
                self.conn.commit()
                self.log(f"已记录视频ID [{vid}] 到数据库。")
        except Exception as e:
            self.log(f"警告：数据库操作失败 - {e}")

    def get_formats(self, url, cookies_opt, proxy_opt, playlist_opt):
        cmd = ["yt-dlp", "--no-colors", "-F", *cookies_opt, *proxy_opt, *playlist_opt, url]
        try:
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, creationflags=creation_flags)
            if result.returncode != 0:
                return None, result.stderr
            return result.stdout, None
        except Exception as e:
            return None, str(e)

    def download_video(self, url, format_code, outpath, cookies_opt, proxy_opt, playlist_opt, max_retry, retry_delay, use_archive=True):
        Path(outpath).mkdir(parents=True, exist_ok=True)
        output_template = os.path.join(outpath, "%(title)s [%(id)s].%(ext)s")
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0


        self.stop_event.clear()
        self.current_process = None

        for attempt in range(1, max_retry + 1):

            if self.stop_event.is_set():
                self.log("用户取消了下载，停止重试。")
                return False, "已取消"

            self.log(f"\n===== 第{attempt}次尝试下载（剩余重试：{max_retry - attempt}次） （格式：{format_code if format_code else '默认'}）=====")
            cmd = [
                "yt-dlp",
                "--no-colors",
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/120.0",
                *cookies_opt,
                *proxy_opt,
                "-o", output_template,
                *playlist_opt,
                "--newline",
                "--continue",
                "--no-overwrites"
            ]
            if format_code:
                cmd.extend(["-f", format_code])
            if use_archive and self.archive_path:
                cmd.extend(["--download-archive", self.archive_path])
            cmd.append(url)

            # 启动进程并保存引用
            self.current_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                    text=True, bufsize=1, creationflags=creation_flags)
            # 实时输出日志，同时检查停止标志
            try:
                for line in self.current_process.stdout:
                    if self.stop_event.is_set():
                        self.current_process.terminate()
                        self.log("检测到停止信号，正在终止下载进程...")
                        break
                    self.log(line.rstrip())
                self.current_process.wait()
            except Exception as e:
                self.log(f"下载过程异常: {e}")
            finally:
                returncode = self.current_process.returncode
                self.current_process = None

            if self.stop_event.is_set():
                return False, "已取消"

            if returncode == 0:
                self.log("下载成功！")
                speak("下载完毕")
                return True, "下载完成"
            else:
                self.log(f"下载失败，退出码 {returncode}")
                if attempt < max_retry:
                    # 重试前也检查停止标志
                    for i in range(retry_delay):
                        if self.stop_event.is_set():
                            return False, "已取消"
                        time.sleep(1)
        # 所有重试均失败
        speak("下载失败")
        return False, f"重试 {max_retry} 次后仍然失败"

    def request_stop(self):
        """外部调用的停止方法"""
        self.stop_event.set()
        if self.current_process:
            self.current_process.terminate()

# ==================== GUI 界面 ====================
class YouTubeDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("yt-dlp GUI工具")
        self.config_file = self._find_config_path()
        self.config_valid = False
        self.disable_proxy = tk.BooleanVar(value=False)
        self.disable_archive = tk.BooleanVar(value=False)
        self.load_config()
        self.setup_ui()
        db_path = self.config['Settings'].get('db_path', str(DEFAULT_DB_PATH))
        archive_path = self.config['Settings'].get('archive_path', '')
        if archive_path and archive_path.strip():
            archive_path = archive_path.strip()
        else:
            archive_path = None
        self.core = DownloaderCore(log_callback=self.append_log, db_path=db_path, archive_path=archive_path)
        self.js_status = self.check_js_runtime()
        self.ffmpeg_status = self.check_ffmpeg()
        self.disable_proxy.trace_add('write', lambda *_: self.update_proxy_status())
        self.disable_archive.trace_add('write', lambda *_: self.update_archive_status())
        self.root.after(100, self.update_status_display)

    def _find_config_path(self):
        local_config = "ytGUIconfig.ini"
        user_config_dir = Path.home() / ".youtube_downloader"
        user_config = user_config_dir / "ytGUIconfig.ini"
        if Path(local_config).exists():
            return local_config
        elif user_config.exists():
            return str(user_config)
        return local_config

    def check_js_runtime(self):
        deno_ok = shutil.which("deno") is not None
        node_ok = shutil.which("node") is not None
        if deno_ok:
            return "Deno已安装"
        elif node_ok:
            return "Node.js已安装"
        else:
            return "未安装(可能影响受限视频)"

    def check_ffmpeg(self):
        return "已安装" if shutil.which("ffmpeg") else "未安装(无法合并音视频)"

    def update_status_display(self):
        if hasattr(self, 'js_status_label') and hasattr(self, 'ffmpeg_status_label'):
            js_color = "red" if "未安装" in self.js_status else "green"
            ff_color = "red" if "未安装" in self.ffmpeg_status else "green"
            self.js_status_label.config(text=f"JS: {self.js_status}", foreground=js_color)
            self.ffmpeg_status_label.config(text=f"FFmpeg: {self.ffmpeg_status}", foreground=ff_color)
            self.update_proxy_status()
            self.update_playlist_status()
            self.update_archive_status()
        else:
            self.root.after(100, self.update_status_display)

    def update_proxy_status(self):
        if hasattr(self, 'proxy_status_label'):
            if self.disable_proxy.get():
                self.proxy_status_label.config(text="代理: 无代理", foreground="blue")
            else:
                proxy_addr = self.proxy_var.get().strip()
                if proxy_addr:
                    self.proxy_status_label.config(text=f"代理: {proxy_addr}", foreground="blue")
                else:
                    self.proxy_status_label.config(text="代理: 未配置", foreground="orange")

    def update_playlist_status(self):
        if hasattr(self, 'playlist_status_label'):
            if self.playlist_var.get():
                self.playlist_status_label.config(text="播放列表模式", foreground="green")
            else:
                self.playlist_status_label.config(text="单视频模式", foreground="blue")

    def update_archive_status(self):
        if hasattr(self, 'archive_status_label'):
            if self.disable_archive.get():
                self.archive_status_label.config(text="存档: 当前可重复下载", foreground="orange")
            else:
                self.archive_status_label.config(text="存档: 比对跳过重复", foreground="green")

    def load_config(self):
        self.config = configparser.ConfigParser()
        if os.path.exists(self.config_file):
            try:
                self.config.read(self.config_file, encoding='utf-8')
                required_keys = {
                    'outpath': str,
                    'proxy': str,
                    'use_browser': str,
                    'enable_playlist': bool,
                    'max_retry': int,
                    'retry_delay': int,
                    'db_path': str
                }
                if all(key in self.config['Settings'] for key in required_keys):
                    self.config_valid = True
                    if 'editor_path' not in self.config['Settings']:
                        self.config['Settings']['editor_path'] = ''
                    if 'disable_proxy' in self.config['Settings']:
                        self.disable_proxy.set(self.config['Settings'].getboolean('disable_proxy'))
                    if 'disable_archive' in self.config['Settings']:
                        self.disable_archive.set(self.config['Settings'].getboolean('disable_archive'))
                    if 'archive_path' not in self.config['Settings']:
                        self.config['Settings']['archive_path'] = str(DEFAULT_ARCHIVE_PATH)
                else:
                    self.config_valid = False
                    self._set_default_config()
            except Exception:
                self.config_valid = False
                self._set_default_config()
        else:
            self.config_valid = False
            self._set_default_config()

    def _set_default_config(self):
        self.config['Settings'] = {
            'outpath': str(Path.home() / "Downloads"),
            'proxy': 'http://127.0.0.1:8100',
            'use_browser': 'firefox',
            'portable_browser_path': r'I:\mysoft\firefox\KliData\AppData\Mozilla\Firefox\Profiles\wwqoemxu.default-release',
            'enable_playlist': 'false',
            'max_retry': '5',
            'retry_delay': '10',
            'db_path': str(DEFAULT_DB_PATH),
            'editor_path': '',
            'disable_proxy': 'false',
            'disable_archive': 'false',
            'archive_path': str(DEFAULT_ARCHIVE_PATH)
        }

    def _save_config_to_file(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'win32' and Path(path).exists():
            try:
                FILE_ATTRIBUTE_HIDDEN = 0x2
                attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
                if attrs != -1 and (attrs & FILE_ATTRIBUTE_HIDDEN):
                    ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs & ~FILE_ATTRIBUTE_HIDDEN)
            except Exception:
                pass
        if 'Settings' not in self.config:
            self.config['Settings'] = {}
        self.config['Settings']['outpath'] = self.outpath_var.get()
        self.config['Settings']['proxy'] = self.proxy_var.get()
        self.config['Settings']['use_browser'] = self.browser_var.get()
        self.config['Settings']['portable_browser_path'] = self.portable_path_var.get()
        self.config['Settings']['enable_playlist'] = str(self.playlist_var.get()).lower()
        self.config['Settings']['max_retry'] = self.max_retry_var.get()
        self.config['Settings']['retry_delay'] = self.retry_delay_var.get()
        self.config['Settings']['db_path'] = self.db_path_var.get()
        self.config['Settings']['editor_path'] = self.editor_path_var.get()
        self.config['Settings']['disable_proxy'] = str(self.disable_proxy.get()).lower()
        self.config['Settings']['disable_archive'] = str(self.disable_archive.get()).lower()
        self.config['Settings']['archive_path'] = self.archive_path_var.get()
        with open(path, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def save_config(self):
        try:
            self._save_config_to_file(self.config_file)
            new_db_path = self.db_path_var.get()
            new_archive_path = self.archive_path_var.get().strip()
            if not new_archive_path:
                new_archive_path = None
            self.core.db_path = new_db_path
            self.core.archive_path = new_archive_path
            self.core.init_database()
            self.config_valid = True
            self.update_proxy_status()
            abs_path = os.path.abspath(self.config_file)
            messagebox.showinfo("提示", f"配置已保存到：{abs_path}")
        except PermissionError:
            user_config_dir = Path.home() / ".youtube_downloader"
            user_config_dir.mkdir(parents=True, exist_ok=True)
            fallback_path = user_config_dir / "ytGUIconfig.ini"
            try:
                self._save_config_to_file(str(fallback_path))
                self.config_file = str(fallback_path)
                new_db_path = self.db_path_var.get()
                new_archive_path = self.archive_path_var.get().strip() or None
                self.core.db_path = new_db_path
                self.core.archive_path = new_archive_path
                self.core.init_database()
                self.config_valid = True
                self.update_proxy_status()
                abs_path = os.path.abspath(fallback_path)
                messagebox.showwarning("配置已保存",
                    f"由于原路径权限不足，配置文件已保存到用户目录：\n{abs_path}\n\n后续启动将自动使用此路径。")
            except Exception as e2:
                messagebox.showerror("保存失败", f"无法保存配置文件到任何位置：\n{e2}\n\n请检查文件是否被其他程序占用或目录权限。")
        except Exception as e:
            messagebox.showerror("保存失败", f"无法保存配置文件：{e}\n\n请检查磁盘空间或文件权限。")

    def setup_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="配置")
        download_frame = ttk.Frame(notebook)
        notebook.add(download_frame, text="下载")

        self.create_config_tab(config_frame)
        self.create_download_tab(download_frame)

        if self.config_valid:
            notebook.select(download_frame)
        else:
            notebook.select(config_frame)

    def create_config_tab(self, parent):
        frame = ttk.LabelFrame(parent, text="基本设置", padding=10)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ========== 像素坐标参数 (可自行微调) ==========
        start_x_label = 10      # 标签列 X 起点
        start_x_entry = 125     # 输入框列 X 起点
        start_x_button = 830    # 按钮列 X 起点
        start_y = 10            # 第一行 Y 起点
        row_height = 35         # 行高（像素）
        label_width = 120       # 标签固定宽度（像素）
        entry_width = 660       # 长输入框宽度（像素）
        combo_width = 150       # 浏览器组合框宽度（像素）
        spinbox_width = 80      # Spinbox 宽度（像素）
        proxy_combo_width = 300 # 代理地址组合框宽度（像素）
        btn_width = 100          # 按钮宽度（像素）
        ctrl_height = 24        # 所有控件统一高度（像素）

        row = 0

        # 1. 输出目录
        ttk.Label(frame, text="输出目录:").place(x=start_x_label, y=start_y + row * row_height, width=label_width, height=ctrl_height)
        self.outpath_var = tk.StringVar(value=self.config['Settings']['outpath'])
        ttk.Entry(frame, textvariable=self.outpath_var).place(x=start_x_entry, y=start_y + row * row_height, width=entry_width, height=ctrl_height)
        ttk.Button(frame, text="浏览", command=self.browse_outpath).place(x=start_x_button, y=start_y + row * row_height, width=btn_width, height=ctrl_height)
        row += 1

        # 2. 代理地址
        ttk.Label(frame, text="代理地址:").place(x=start_x_label, y=start_y + row * row_height, width=label_width, height=ctrl_height)
        self.proxy_var = tk.StringVar(value=self.config['Settings']['proxy'])
        proxy_combo = ttk.Combobox(frame, textvariable=self.proxy_var)
        proxy_combo['values'] = (
            'http://127.0.0.1:8100',
            'http://127.0.0.1:10809',
            'socks5://127.0.0.1:1080',
            'socks5://127.0.0.1:10808',
            'socks5://127.0.0.1:9050'
        )
        proxy_combo.place(x=start_x_entry, y=start_y + row * row_height, width=proxy_combo_width, height=ctrl_height)
        self.proxy_var.trace_add('write', lambda *_: self.update_proxy_status())
        row += 1

        # 3. 浏览器名称
        ttk.Label(frame, text="浏览器名称:").place(x=start_x_label, y=start_y + row * row_height, width=label_width, height=ctrl_height)
        self.browser_var = tk.StringVar(value=self.config['Settings']['use_browser'])
        ttk.Combobox(frame, textvariable=self.browser_var, values=["firefox", "chrome", "brave", "edge"]).place(x=start_x_entry, y=start_y + row * row_height, width=combo_width, height=ctrl_height)
        row += 1

        # 4. 便携版路径 (可选)
        ttk.Label(frame, text="便携版路径 (可选):").place(x=start_x_label, y=start_y + row * row_height, width=label_width, height=ctrl_height)
        self.portable_path_var = tk.StringVar(value=self.config['Settings']['portable_browser_path'])
        ttk.Entry(frame, textvariable=self.portable_path_var).place(x=start_x_entry, y=start_y + row * row_height, width=entry_width, height=ctrl_height)
        ttk.Button(frame, text="浏览", command=self.browse_portable).place(x=start_x_button, y=start_y + row * row_height, width=btn_width, height=ctrl_height)
        row += 1

        # 注意：原先的 self.playlist_var 未在本函数中使用，但保留定义
        self.playlist_var = tk.BooleanVar(value=self.config['Settings'].getboolean('enable_playlist'))

        # 5. 最大重试次数
        ttk.Label(frame, text="最大重试次数:").place(x=start_x_label, y=start_y + row * row_height, width=label_width, height=ctrl_height)
        self.max_retry_var = tk.StringVar(value=self.config['Settings']['max_retry'])
        ttk.Spinbox(frame, from_=1, to=20, textvariable=self.max_retry_var).place(x=start_x_entry, y=start_y + row * row_height, width=spinbox_width, height=ctrl_height)
        row += 1

        # 6. 重试延迟(秒)
        ttk.Label(frame, text="重试延迟(秒):").place(x=start_x_label, y=start_y + row * row_height, width=label_width, height=ctrl_height)
        self.retry_delay_var = tk.StringVar(value=self.config['Settings']['retry_delay'])
        ttk.Spinbox(frame, from_=1, to=60, textvariable=self.retry_delay_var).place(x=start_x_entry, y=start_y + row * row_height, width=spinbox_width, height=ctrl_height)
        row += 1

        # 7. 数据库路径
        ttk.Label(frame, text="数据库路径:").place(x=start_x_label, y=start_y + row * row_height, width=label_width, height=ctrl_height)
        self.db_path_var = tk.StringVar(value=self.config['Settings']['db_path'])
        ttk.Entry(frame, textvariable=self.db_path_var).place(x=start_x_entry, y=start_y + row * row_height, width=entry_width, height=ctrl_height)
        ttk.Button(frame, text="浏览", command=self.browse_db).place(x=start_x_button, y=start_y + row * row_height, width=btn_width, height=ctrl_height)
        row += 1

        # 8. 存档文件
        lbl_archive = ttk.Label(frame, text="存档文件:")
        lbl_archive.place(x=start_x_label, y=start_y + row * row_height, width=label_width, height=ctrl_height)
        ToolTip(lbl_archive, "指定 --download-archive 文件路径，用于记录已下载的视频/音频ID，避免重复下载")
        self.archive_path_var = tk.StringVar(value=self.config['Settings'].get('archive_path', str(DEFAULT_ARCHIVE_PATH)))
        entry_archive = ttk.Entry(frame, textvariable=self.archive_path_var)
        entry_archive.place(x=start_x_entry, y=start_y + row * row_height, width=entry_width, height=ctrl_height)
        ToolTip(entry_archive, "存档文件的完整路径，建议使用 .txt 或 .log 后缀")
        ttk.Button(frame, text="浏览", command=self.browse_archive).place(x=start_x_button, y=start_y + row * row_height, width=btn_width, height=ctrl_height)
        row += 1

        # 9. 编辑器路径 (可选)
        ttk.Label(frame, text="编辑器路径 (可选):").place(x=start_x_label, y=start_y + row * row_height, width=label_width, height=ctrl_height)
        self.editor_path_var = tk.StringVar(value=self.config['Settings'].get('editor_path', ''))
        ttk.Entry(frame, textvariable=self.editor_path_var).place(x=start_x_entry, y=start_y + row * row_height, width=entry_width, height=ctrl_height)
        ttk.Button(frame, text="浏览", command=self.browse_editor).place(x=start_x_button, y=start_y + row * row_height, width=btn_width, height=ctrl_height)
        row += 1

        # 按钮行 (单独一行)
        btn_frame = ttk.Frame(frame)
        btn_frame.place(x=start_x_label, y=start_y + row * row_height)
        ttk.Button(btn_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="打开配置文件", command=self.open_config_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="编辑当前脚本", command=self.edit_current_script).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="重启 GUI", command=self.restart_gui).pack(side=tk.LEFT, padx=5)

    def create_download_tab(self, parent):
        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        status_frame = ttk.Frame(frame)
        status_frame.pack(fill=tk.X, pady=(0, 5))
        self.js_status_label = ttk.Label(status_frame, text="JS: 检测中...")
        self.js_status_label.pack(side=tk.LEFT, padx=(0, 10))
        self.ffmpeg_status_label = ttk.Label(status_frame, text="FFmpeg: 检测中...")
        self.ffmpeg_status_label.pack(side=tk.LEFT, padx=(0, 10))
        self.proxy_status_label = ttk.Label(status_frame, text="代理: 检测中...", foreground="blue")
        self.proxy_status_label.pack(side=tk.LEFT, padx=(0, 10))
        self.playlist_status_label = ttk.Label(status_frame, text="单视频模式", foreground="blue")
        self.playlist_status_label.pack(side=tk.LEFT, padx=(0, 10))
        self.archive_status_label = ttk.Label(status_frame, text="存档: 比对跳过重复", foreground="green")
        self.archive_status_label.pack(side=tk.LEFT)

        ttk.Label(frame, text="视频 URL:").pack(anchor=tk.W)
        self.url_var = tk.StringVar()
        url_entry = ttk.Entry(frame, textvariable=self.url_var, width=80)
        url_entry.pack(fill=tk.X, pady=5)

        btn_container = ttk.Frame(frame)
        btn_container.pack(fill=tk.X, pady=5)

        left_btns = ttk.Frame(btn_container)
        left_btns.pack(side=tk.LEFT)
        right_frame = ttk.Frame(btn_container)
        right_frame.pack(side=tk.RIGHT)

        # 右侧复选框
        self.playlist_check = ttk.Checkbutton(right_frame, text="播放列表模式", variable=self.playlist_var,
                                              command=self.update_playlist_status)
        self.playlist_check.pack(side=tk.RIGHT, padx=5)
        
        self.disable_archive_check = ttk.Checkbutton(right_frame, text="禁用存档比对", variable=self.disable_archive)
        self.disable_archive_check.pack(side=tk.RIGHT, padx=5)
        
        self.proxy_check = ttk.Checkbutton(right_frame, text="禁用代理", variable=self.disable_proxy)
        self.proxy_check.pack(side=tk.RIGHT, padx=5)

        # 右侧按钮 (先赋值给变量，以便添加 ToolTip)
        self.btn_copy_cmd = ttk.Button(right_frame, text="复制当前命令", command=self.copy_current_command)
        self.btn_copy_cmd.pack(side=tk.RIGHT, padx=2)
        
        self.btn_help = ttk.Button(right_frame, text="格式快捷帮助", command=self.show_format_help)
        self.btn_help.pack(side=tk.RIGHT, padx=2)

        # 左侧按钮 (先赋值给变量，以便添加 ToolTip)
        self.btn_formats = ttk.Button(left_btns, text="获取格式列表", command=self.fetch_formats)
        self.btn_formats.pack(side=tk.LEFT, padx=2)
        
        self.btn_download = ttk.Button(left_btns, text="下载", command=self.start_download)
        self.btn_download.pack(side=tk.LEFT, padx=2)
        
        self.btn_direct = ttk.Button(left_btns, text="立即下载〔最佳画质〕", command=self.start_direct_download)
        self.btn_direct.pack(side=tk.LEFT, padx=2)
        
        self.btn_stop = ttk.Button(left_btns, text="停止下载", command=self.stop_download)
        self.btn_stop.pack(side=tk.LEFT, padx=2)

        # --- 添加悬停提示 ---
        # 左侧按钮提示
   #     ToolTip(self.btn_formats, "test123")
        ToolTip(self.btn_download, "格式代码为空时，使用b参数下载，有代码时，使用代码组合下载")
        ToolTip(self.btn_direct, "强制使用b参数开始下载")
   #     ToolTip(self.btn_stop, "test123")

        # 右侧按钮提示 (补上了这两个！)
        ToolTip(self.btn_copy_cmd, "复制当前内部拼接的命令，可以用来cmd里测试")
        ToolTip(self.btn_help, "点击后显示格式代码的组合方式")

        # 右侧复选框提示
        ToolTip(self.playlist_check, "勾选后可以下载整个播放列表")
        ToolTip(self.disable_archive_check, "勾选后可以强制下载当前链接")
        ToolTip(self.proxy_check, "国内下载请关闭代理")

        ttk.Label(frame, text="格式代码 (例如 137+140, 或快捷词 1080, 4k, 3152; 留空则自动选择最佳格式):").pack(anchor=tk.W)
        self.format_var = tk.StringVar()
        format_entry = ttk.Entry(frame, textvariable=self.format_var, width=30)
        format_entry.pack(fill=tk.X, pady=5)

        ttk.Label(frame, text="可用格式列表:").pack(anchor=tk.W)
        self.formats_text = scrolledtext.ScrolledText(frame, height=12, width=100, wrap=tk.WORD)
        self.formats_text.pack(fill=tk.BOTH, expand=True, pady=5)
        self.formats_text.config(bg='#EAF4FC')
        self.formats_text.tag_config('sel', background='#CCF09C', foreground='black')




        ttk.Label(frame, text="下载日志:").pack(anchor=tk.W)
        self.log_text = scrolledtext.ScrolledText(frame, height=12, width=100, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text.config(bg='#EAF4FC')
        self.log_text.tag_config('sel', background='#CCF09C', foreground='black')



        self.update_playlist_status()
        self.update_archive_status()

    def get_current_command(self):
        """生成当前界面对应的完整 yt-dlp 命令（格式代码先转换简写）"""
        url = self.url_var.get().strip()
        if not url:
            return None
        format_input = self.format_var.get().strip()
        if format_input:
            format_code = self.resolve_format_code(format_input)
        else:
            format_code = None

        cookies_opt = self.get_cookies_opt()
        proxy_opt = [] if self.disable_proxy.get() else self.get_proxy_opt()

        cmd_parts = ["yt-dlp"]
        if format_code:
            cmd_parts.extend(["-f", format_code])
        if len(cookies_opt) == 2:
            cmd_parts.extend(["--cookies-from-browser", cookies_opt[1]])
        if proxy_opt and len(proxy_opt) == 2:
            cmd_parts.extend(["--proxy", proxy_opt[1]])
        if not self.playlist_var.get():
            cmd_parts.append("--no-playlist")
        use_archive = not self.disable_archive.get()
        if use_archive and self.core.archive_path:
            cmd_parts.extend(["--download-archive", self.core.archive_path])
        cmd_parts.append(url)
        return " ".join(cmd_parts)

    def copy_current_command(self):
        cmd = self.get_current_command()
        if cmd is None:
            messagebox.showwarning("警告", "请先输入 URL")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(cmd)
        self.append_log("当前命令已复制到剪贴板")

    def show_format_help(self):
        help_text = """【格式快捷关键字】
b   = 最佳音画
4k  = 315+251   4k2 = 313+251   4khdr = 337+251
2k  = 303+251   2khdr = 335+251  1440 = 248+251
1080 = 137+140  720 = 136+140
3152 = 315+251  3132 = 313+251  3032 = 303+251
3372 = 337+251  3352 = 335+251  2482 = 248+251
2472 = 247+251  1371 = 137+140  1361 = 136+140
3011 = 301+140  3021 = 302+140  2991 = 299+140
1351 = 135+140  1341 = 134+140  1331 = 133+140
音频: 251(opus无损), 140(m4a), 139(低质m4a)
留空格式代码：yt-dlp 自动选择最佳格式（通常为 best）"""
        messagebox.showinfo("格式快捷帮助", help_text)

    def browse_outpath(self):
        path = filedialog.askdirectory()
        if path:
            self.outpath_var.set(os.path.normpath(path))

    def browse_portable(self):
        path = filedialog.askdirectory()
        if path:
            self.portable_path_var.set(os.path.normpath(path))

    def browse_db(self):
        path = filedialog.asksaveasfilename(defaultextension=".db", filetypes=[("SQLite DB", "*.db")])
        if path:
            self.db_path_var.set(os.path.normpath(path))

    def browse_archive(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            self.archive_path_var.set(os.path.normpath(path))

    def browse_editor(self):
        path = filedialog.askopenfilename(title="选择编辑器程序", filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")])
        if path:
            self.editor_path_var.set(os.path.normpath(path))

    def open_config_file(self):
        config_path = os.path.abspath(self.config_file)
        if not os.path.exists(config_path):
            self.save_config()
        editor = self.editor_path_var.get().strip()
        try:
            if editor and os.path.exists(editor):
                subprocess.Popen([editor, config_path])
            else:
                if sys.platform == 'win32':
                    os.startfile(config_path)
                else:
                    subprocess.Popen(['xdg-open', config_path])
        except Exception as e:
            messagebox.showerror("错误", f"无法打开配置文件：{e}")

    def edit_current_script(self):
        script_path = os.path.abspath(__file__)
        editor = self.editor_path_var.get().strip()
        try:
            if editor and os.path.exists(editor):
                subprocess.Popen([editor, script_path])
            else:
                if sys.platform == 'win32':
                    notepad = r'C:\Windows\System32\notepad.exe'
                    if os.path.exists(notepad):
                        subprocess.Popen([notepad, script_path])
                    else:
                        os.startfile(script_path)
                else:
                    subprocess.Popen(['xdg-open', script_path])
        except Exception as e:
            messagebox.showerror("错误", f"无法打开脚本编辑器：{e}\n请手动设置自定义编辑器路径。")

    def restart_gui(self):
        try:
            script = os.path.abspath(__file__)
            if sys.platform == 'win32':
                if script.endswith('.pyw'):
                    python = sys.executable.replace('python.exe', 'pythonw.exe')
                else:
                    python = sys.executable
                subprocess.Popen([python, script], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen([sys.executable, script])
            self.root.quit()
            self.root.destroy()
        except Exception as e:
            messagebox.showerror("错误", f"重启失败：{e}")

    def append_log(self, message):
        def _append():
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
        self.root.after(0, _append)

    def fetch_formats(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("警告", "请输入视频 URL")
            return
        cleaned = self.core.clean_url(url)
        cookies_opt = self.get_cookies_opt()
        proxy_opt = [] if self.disable_proxy.get() else self.get_proxy_opt()
        playlist_opt = self.get_playlist_opt()
        self.formats_text.delete(1.0, tk.END)
        self.append_log(f"正在获取格式列表: {url}")
        def fetch():
            formats, error = self.core.get_formats(url, cookies_opt, proxy_opt, playlist_opt)
            if formats:
                self.root.after(0, lambda: self.formats_text.insert(tk.END, formats))
                self.append_log("格式列表获取成功。")
            else:
                self.append_log(f"获取失败: {error}")
        threading.Thread(target=fetch, daemon=True).start()

    def get_cookies_opt(self):
        browser = self.browser_var.get()
        portable = self.portable_path_var.get().strip()
        if portable:
            return ["--cookies-from-browser", f"{browser}:{portable}"]
        else:
            return ["--cookies-from-browser", browser]

    def get_proxy_opt(self):
        proxy = self.proxy_var.get().strip()
        if proxy:
            return ["--proxy", proxy]
        return []

    def get_playlist_opt(self):
        if self.playlist_var.get():
            return []
        else:
            return ["--no-playlist"]

    def resolve_format_code(self, code):
        if not code:
            return None
        shortcuts = {
            "b": "bestvideo*+bestaudio/best",
            "4k": "315+251", "4k2": "313+251", "4khdr": "337+251",
            "2k": "303+251", "2khdr": "335+251", "1440": "248+251",
            "1080": "137+140", "720": "136+140",
            "315251": "315+251", "313251": "313+251", "303251": "303+251",
            "337251": "337+251", "335251": "335+251", "248251": "248+251",
            "247251": "247+251", "137140": "137+140", "136140": "136+140",
            "3152": "315+251", "3132": "313+251", "3032": "303+251",
            "3372": "337+251", "3352": "335+251", "2482": "248+251",
            "2472": "247+251", "1371": "137+140", "1361": "136+140",
            "3011": "301+140", "3021": "302+140", "2991": "299+140",
            "1351": "135+140", "1341": "134+140", "1331": "133+140",
        }
        return shortcuts.get(code.lower(), code)

    def stop_download(self):
        """用户点击停止按钮时调用"""
        self.append_log("用户请求停止下载...")
        self.core.request_stop()

    def start_direct_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("警告", "请输入视频 URL")
            return
        format_code = self.resolve_format_code("b")
        outpath = self.outpath_var.get()
        max_retry = int(self.max_retry_var.get())
        retry_delay = int(self.retry_delay_var.get())
        cookies_opt = self.get_cookies_opt()
        proxy_opt = [] if self.disable_proxy.get() else self.get_proxy_opt()
        playlist_opt = self.get_playlist_opt()
        use_archive = not self.disable_archive.get()

        cleaned = self.core.clean_url(url)
        vid = self.core.extract_video_id(cleaned)

        proxy_info = "代理" if proxy_opt else "无代理"
        archive_info = "，禁用存档比对" if not use_archive else ""
        self.append_log(f"开始下载（{proxy_info}最佳画质{archive_info}）: {url}")

        def download_task():
            success, msg = self.core.download_video(
                cleaned, format_code, outpath, cookies_opt, proxy_opt, playlist_opt,
                max_retry, retry_delay, use_archive=use_archive
            )
            if success and vid:
                self.root.after(0, lambda: self.core.mark_downloaded(vid, cleaned))
            self.append_log(msg)
            if success:
                self.append_log(f"文件保存在: {outpath}")
        threading.Thread(target=download_task, daemon=True).start()

    def start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("警告", "请输入视频 URL")
            return
        format_input = self.format_var.get().strip()
        format_code = self.resolve_format_code(format_input) if format_input else None
        outpath = self.outpath_var.get()
        max_retry = int(self.max_retry_var.get())
        retry_delay = int(self.retry_delay_var.get())
        cookies_opt = self.get_cookies_opt()
        proxy_opt = [] if self.disable_proxy.get() else self.get_proxy_opt()
        playlist_opt = self.get_playlist_opt()
        use_archive = not self.disable_archive.get()

        cleaned = self.core.clean_url(url)
        vid = self.core.extract_video_id(cleaned)

        archive_info = "，禁用存档比对" if not use_archive else ""
        format_info = f"格式：{format_code}" if format_code else "自动选择最佳格式"
        self.append_log(f"开始下载（{format_info}{archive_info}）: {url}")

        def download_task():
            success, msg = self.core.download_video(
                cleaned, format_code, outpath, cookies_opt, proxy_opt, playlist_opt,
                max_retry, retry_delay, use_archive=use_archive
            )
            if success and vid:
                self.root.after(0, lambda: self.core.mark_downloaded(vid, cleaned))
            self.append_log(msg)
            if success:
                self.append_log(f"文件保存在: {outpath}")
        threading.Thread(target=download_task, daemon=True).start()

if __name__ == "__main__":
    if not shutil.which("yt-dlp"):
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("错误", "未找到 yt-dlp，请安装并加入 PATH")
        sys.exit(1)
    root = tk.Tk()
    width = 1000
    height = 750
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.resizable(False, False)
    app = YouTubeDownloaderGUI(root)
    root.mainloop()
