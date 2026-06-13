import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import os
import re
import ast
import sys
import threading

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

# ---------- 获取所有PIL支持的图片格式 ----------
def get_supported_extensions():
    try:
        exts = list(Image.registered_extensions().keys())
        return tuple(ext.lower() for ext in exts if ext.startswith('.'))
    except Exception:
        return ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp', '.gif')

SUPPORTED_IMG_EXT = get_supported_extensions()
SUPPORTED_IMG_FILTER = " ".join(f"*{ext}" for ext in SUPPORTED_IMG_EXT)

def is_image_file(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    return ext in SUPPORTED_IMG_EXT

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

# ---------- 批量任务项 ----------
class BatchItem:
    def __init__(self, filepath, template):
        self.filepath = filepath
        self.template = template

    def to_dict(self):
        return {"filepath": self.filepath, "template": self.template}

    @classmethod
    def from_dict(cls, data):
        return cls(data["filepath"], data["template"])

# ---------- 公用切割函数 ----------
def cut_grid(img, rows, cols, out_dir, ext, save_params, progress_callback=None, file_prefix=""):
    w, h = img.size
    if rows > h or cols > w:
        raise ValueError("网格超出图片边界")
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
            name = f"{i}_{j}"
            if file_prefix:
                name = f"{file_prefix}_{name}"
            cropped.save(os.path.join(out_dir, f"{name}.{ext}"), **save_params)
            count += 1
            if progress_callback:
                progress_callback(count)
    return count

def cut_smart(img, blocks, ratios, direction, out_dir, ext, save_params, progress_callback=None, file_prefix=""):
    w, h = img.size
    if direction == "horizontal":
        for blk in blocks:
            if blk > h:
                raise ValueError(f"块数超过图片高度")
    else:
        for blk in blocks:
            if blk > w:
                raise ValueError(f"块数超过图片宽度")
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
                name = f"S_c{col_idx+1}_r{blk_idx+1}"
                if file_prefix:
                    name = f"{file_prefix}_{name}"
                cropped.save(os.path.join(out_dir, f"{name}.{ext}"), **save_params)
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
                name = f"S_r{row_idx+1}_c{blk_idx+1}"
                if file_prefix:
                    name = f"{file_prefix}_{name}"
                cropped.save(os.path.join(out_dir, f"{name}.{ext}"), **save_params)
                count += 1
                if progress_callback:
                    progress_callback(count)
                left = right
            top = bottom
    return count

def cut_advanced(img, pattern, group_ratios, direction, out_dir, ext, save_params, progress_callback=None, file_prefix=""):
    w, h = img.size
    if direction == "horizontal":
        for (blk, _) in pattern:
            if blk > h:
                raise ValueError("块数超过高度")
    else:
        for (blk, _) in pattern:
            if blk > w:
                raise ValueError("块数超过宽度")
    count = 0
    if direction == "horizontal":
        n = len(pattern)
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
                    name = f"A_c{col_idx+1}_r{blk_idx+1}"
                    if file_prefix:
                        name = f"{file_prefix}_{name}"
                    cropped.save(os.path.join(out_dir, f"{name}.{ext}"), **save_params)
                    count += 1
                    if progress_callback:
                        progress_callback(count)
                    top = bottom
            else:
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
                    if ratios[blk_idx][1]:
                        cropped = img.crop((left, top, right, bottom))
                        name = f"A_c{col_idx+1}_r{blk_idx+1}"
                        if file_prefix:
                            name = f"{file_prefix}_{name}"
                        cropped.save(os.path.join(out_dir, f"{name}.{ext}"), **save_params)
                        count += 1
                        if progress_callback:
                            progress_callback(count)
                    top = bottom
            left = right
    else:
        n = len(pattern)
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
                    name = f"A_r{row_idx+1}_c{blk_idx+1}"
                    if file_prefix:
                        name = f"{file_prefix}_{name}"
                    cropped.save(os.path.join(out_dir, f"{name}.{ext}"), **save_params)
                    count += 1
                    if progress_callback:
                        progress_callback(count)
                    left = right
            else:
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
                    if ratios[blk_idx][1]:
                        cropped = img.crop((left, top, right, bottom))
                        name = f"A_r{row_idx+1}_c{blk_idx+1}"
                        if file_prefix:
                            name = f"{file_prefix}_{name}"
                        cropped.save(os.path.join(out_dir, f"{name}.{ext}"), **save_params)
                        count += 1
                        if progress_callback:
                            progress_callback(count)
                    left = right
            top = bottom
    return count

def cut_free(img, rects, out_dir, ext, save_params, progress_callback=None, file_prefix=""):
    img_w, img_h = img.size
    count = 0
    for idx, (x, y, w, h) in enumerate(rects):
        if x < 0 or y < 0 or x + w > img_w or y + h > img_h:
            raise ValueError(f"矩形 {idx+1} 超出图片边界")
        if w <= 0 or h <= 0:
            raise ValueError(f"矩形 {idx+1} 尺寸无效")
        cropped = img.crop((x, y, x + w, y + h))
        name = f"free_{idx+1}"
        if file_prefix:
            name = f"{file_prefix}_{name}"
        cropped.save(os.path.join(out_dir, f"{name}.{ext}"), **save_params)
        count += 1
        if progress_callback:
            progress_callback(count)
    return count

# ---------- 公用解析函数 ----------
def parse_smart_pattern(text):
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

def parse_advanced_pattern(text):
    if not text:
        return None, None
    text = re.sub(r'\bd(\d+(?:\.\d+)?)\b', r'"d\1"', text)
    group_ratios = None
    rest = text
    if '|' in text:
        parts = text.split('|', 1)
        ratio_part = parts[0].strip()
        rest = parts[1].strip()
        if not rest:
            return None, None
        try:
            ratio_list = [float(x.strip()) for x in ratio_part.split(',') if x.strip()]
            if any(r <= 0 for r in ratio_list):
                return None, None
            total = sum(ratio_list)
            group_ratios = [r / total * 100 for r in ratio_list]
        except:
            return None, None
    try:
        clean_text = re.sub(r'\s+', '', rest)
        data = ast.literal_eval(clean_text)
    except:
        return None, None
    if not isinstance(data, list):
        return None, None
    result = []
    for idx, item in enumerate(data):
        if isinstance(item, int):
            if item <= 0:
                return None, None
            result.append((item, None))
        elif isinstance(item, list):
            if len(item) == 1 and isinstance(item[0], int):
                blk = item[0]
                if blk <= 0:
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
                            return None, None
                    else:
                        return None, None
                total = sum(v for v, _ in parsed)
                if total <= 0:
                    return None, None
                norm_ratios = [(v / total * 100, flag) for v, flag in parsed]
                result.append((blk, norm_ratios))
            else:
                return None, None
        else:
            return None, None
    if group_ratios is not None and len(group_ratios) != len(result):
        return None, None
    return group_ratios, result

def parse_free_pattern(text):
    if not text:
        return []
    rects = []
    lines = text.replace('\r', '').split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
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
                return None
        else:
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
                        return None
            else:
                return None
    return rects

# ---------- 主程序 ----------
class App:
    def __init__(self, master):
        self.master = master
        master.title("图片切割程序")
        self.preview_window = None
        self.original_img = None
        self.preview_img_pos = (0, 0, 0, 0)
        self.preview_canvas = None
        self.preview_photo = None

        # ----- 左侧控件区域 -----
        tk.Label(master, text="切割的图片:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.entry1 = tk.Entry(master, width=50)
        self.entry1.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        tk.Button(master, text="选择文件", command=self.select_file).grid(row=0, column=2, padx=5, pady=5)

        tk.Label(master, text="保存的路径:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.entry2 = tk.Entry(master, width=50)
        self.entry2.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        tk.Button(master, text="选择文件夹", command=self.select_folder).grid(row=1, column=2, padx=5, pady=5)

        master.columnconfigure(0, weight=0)
        master.columnconfigure(1, weight=1)
        master.columnconfigure(2, weight=0)

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

        # 公共方向选择
        self.dir_frame = tk.LabelFrame(master, text="切割方向 (仅对智能/高级模式有效)", padx=5, pady=5)
        self.dir_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        dir_inner = tk.Frame(self.dir_frame)
        dir_inner.pack(anchor="w")
        self.direction = tk.StringVar(value="horizontal")
        tk.Radiobutton(dir_inner, text="水平方向", variable=self.direction,
                       value="horizontal", command=self.on_dir_changed).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(dir_inner, text="垂直方向", variable=self.direction,
                       value="vertical", command=self.on_dir_changed).pack(side=tk.LEFT, padx=5)

        # 标准网格参数区域
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
        self.advanced_text.insert("1.0", "2,2,6 | [[1,[100]], [2,[30,70]], [3,[20,30,50]]]")
        self.advanced_text.bind("<KeyRelease>", self.on_advanced_param_changed)

        # 自由模式参数区域（增强交互）
        self.free_frame = tk.LabelFrame(master, text="自由模式参数 (矩形定义)", padx=5, pady=5)
        self.free_frame.grid(row=7, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        
        # 自由模式交互控件行
        free_controls = tk.Frame(self.free_frame)
        free_controls.pack(fill=tk.X, padx=5, pady=2)
        self.interactive_btn = tk.Button(free_controls, text="启用交互绘制", command=self.toggle_interactive_mode,
                                         bg="#f0f0f0", width=12)
        self.interactive_btn.pack(side=tk.LEFT, padx=2)
        self.lock_ratio = tk.BooleanVar(value=False)
        self.ratio_lock_cb = tk.Checkbutton(free_controls, text="锁定比例：", variable=self.lock_ratio,
                                            command=self.on_ratio_lock_changed)
        self.ratio_lock_cb.pack(side=tk.LEFT, padx=5)
        
        # 比例输入控件：带预设下拉的输入框，允许手动输入任意比例

        self.ratio_var = tk.StringVar(value="16:9")
        self.ratio_entry = tk.Entry(free_controls, textvariable=self.ratio_var, width=8)
        self.ratio_entry.pack(side=tk.LEFT, padx=2)
        # 常用比例下拉（方便选择）
        self.ratio_preset = ttk.Combobox(free_controls, values=["1:1", "4:3", "16:9", "9:16", "3:2", "2:3"],
                                         state="readonly", width=6)
        self.ratio_preset.set("16:9")
        self.ratio_preset.pack(side=tk.LEFT, padx=2)
        self.ratio_preset.bind("<<ComboboxSelected>>", self.on_preset_ratio)

        
        tk.Button(free_controls, text="清除所有", command=self.clear_all_rects).pack(side=tk.LEFT, padx=5)
        tk.Button(free_controls, text="撤销最后", command=self.delete_last_rect).pack(side=tk.LEFT, padx=2)
        ToolTip(self.ratio_lock_cb, 
            "勾选后绘制矩形时将强制保持所输入的比例。\n\n"
            "比例可以自由输入，也可选择常用预设。\n\n"
            "格式: 宽:高 (例如 16:9, 10:16, 3.5:2)"
        )
        
        # 自由模式文本框
        self.free_text = tk.Text(self.free_frame, height=8, width=60, font=("Consolas", 10))
        self.free_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.free_text.insert("1.0", "10,10,200,150\n250,30,180,200;50,200,300,100")
        self.free_text.bind("<KeyRelease>", self.on_free_param_changed)
        self.on_free_param_changed()
        
        self.free_rects = []

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

        # 底部按钮（添加批量按钮）
        bottom_frame = tk.Frame(master)
        bottom_frame.grid(row=9, column=0, columnspan=3, pady=10, sticky="ew")
        self.batch_btn = tk.Button(bottom_frame, text="批量", command=self.toggle_batch_panel, width=4, bg="#d9d9d9")
        self.batch_btn.pack(side=tk.LEFT, padx=5)
        ToolTip(self.batch_btn, 
                "【批量处理模式】\n"
                "点击按钮展开/收起批量面板，方便批量切割多张图片。\n\n"
                "使用说明：\n"
                "1. 添加图片：\n"
                "   - 点击「浏览图片」多选文件；\n"
                "   - 点击「遍历文件夹」递归添加目录下所有图片；\n"
                "   - 直接拖拽文件/文件夹到列表中；\n"
                "   - 点击「添加当前图片」将主界面当前图片按当前模板加入列表。\n"
                "   - 每个图片会记录添加时的切割模板（模式、参数、输出格式等），同一图片可多次添加不同模板。\n"
                "2. 批量切割：\n"
                "   - 默认每个图片输出到根目录下的单独子文件夹（按原文件名）；\n"
                "   - 勾选「输出同目录」后，所有切片平铺在根目录，文件名格式：序号_模式标识_原内部名称（如 001_G_0_0.png）。\n"
                "   - 切割前需指定输出根目录（若未填写，会弹出选择框）。\n",
                wraplength=600)
        self.preview_btn = tk.Button(bottom_frame, text="打开预览窗口", command=self.toggle_preview_window)
        self.preview_btn.pack(side=tk.LEFT, padx=(30,5))
        tk.Button(bottom_frame, text="开始切割", command=self.start_cutting).pack(side=tk.LEFT, padx=10)
        tk.Button(bottom_frame, text="恢复默认", command=self.reset_parameters).pack(side=tk.LEFT, padx=10)
        tk.Button(bottom_frame, text="退出", command=self.quit_app).pack(side=tk.LEFT, padx=10)

        # 批量处理面板（初始隐藏）
        self.batch_frame = tk.Frame(master, bd=2, relief=tk.GROOVE)
        self.batch_frame.grid(row=10, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        self.batch_frame.grid_remove()
        batch_btn_frame = tk.Frame(self.batch_frame)
        batch_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        tk.Button(batch_btn_frame, text="浏览图片", command=self.batch_add_images).pack(side=tk.LEFT, padx=5)
        tk.Button(batch_btn_frame, text="遍历文件夹", command=self.batch_add_folder).pack(side=tk.LEFT, padx=5)
        tk.Button(batch_btn_frame, text="开始批量切割", command=self.batch_start_cutting).pack(side=tk.LEFT, padx=5)
        tk.Button(batch_btn_frame, text="清空列表", command=self.batch_clear_list).pack(side=tk.LEFT, padx=5)
        tk.Button(batch_btn_frame, text="删除选中", command=self.batch_remove_selected).pack(side=tk.LEFT, padx=5)
        # 新增：输出同目录复选框
        self.output_same_dir = tk.BooleanVar(value=False)
        self.same_dir_cb = tk.Checkbutton(batch_btn_frame, text="输出同目录", variable=self.output_same_dir)
        self.same_dir_cb.pack(side=tk.LEFT, padx=5)
        # 添加详细提示
        ToolTip(self.same_dir_cb, 
                text="【输出同目录】\n"
                     "勾选后，所有切割结果将直接保存在所选输出根目录下，不再为每个源图片创建子文件夹。\n"
                     "文件名格式：{序号}_{模式标识}_{原内部名称}.ext\n"
                     "  序号：001,002... 对应列表中的顺序\n"
                     "  模式标识：G(网格), S(智能), A(高级), F(自由)\n\n"
                     "⚠️ 警告：如果图片数量多或单张图切块数多，会导致单个文件夹内文件数量巨大，可能影响文件系统性能！\n"
                     "建议仅在图片数量少（如<50）且每张图切块数少（如<20）时勾选。",
                wraplength=450)
        # 添加“添加当前图片”按钮
        tk.Button(batch_btn_frame, text="添加当前图片", command=self.add_current_image).pack(side=tk.LEFT, padx=5)
        
        list_frame = tk.Frame(self.batch_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.batch_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=8)
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.batch_listbox.yview)
        self.batch_listbox.config(yscrollcommand=scrollbar.set)
        self.batch_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.batch_items = []

        if HAS_DND:
            self.batch_listbox.drop_target_register(DND_FILES)
            self.batch_listbox.dnd_bind('<<Drop>>', self.on_drop_to_batch_list)
            self.entry1.drop_target_register(DND_FILES)
            self.entry1.dnd_bind('<<Drop>>', self.on_drop_to_entry1)
            self.entry2.drop_target_register(DND_FILES)
            self.entry2.dnd_bind('<<Drop>>', self.on_drop_to_entry2)

        self.drawing_enabled = False
        self.start_x = None
        self.start_y = None
        self.rect_id = None

        self.on_mode_changed()
        self.update_dir_frame_visibility()
        master.protocol("WM_DELETE_WINDOW", self.quit_app)

    # ---------- 批量模式方法 ----------
    def toggle_batch_panel(self):
        if self.batch_frame.winfo_ismapped():
            self.batch_frame.grid_remove()
        else:
            self.batch_frame.grid()
            self.master.update_idletasks()
            self.master.geometry("")

    def capture_current_template(self):
        mode = self.cut_mode.get()
        template = {
            "mode": mode,
            "direction": self.direction.get(),
            "format": self.format_var.get(),
            "quality": self.quality_var.get(),
        }
        if mode == "grid":
            template["rows"] = self.rows_entry.get()
            template["cols"] = self.cols_entry.get()
        elif mode == "smart":
            template["digit_entry"] = self.digit_entry.get()
        elif mode == "advanced":
            template["advanced_text"] = self.advanced_text.get("1.0", tk.END).strip()
        elif mode == "free":
            template["free_rects"] = self.free_rects.copy()
        return template

    def add_batch_item(self, filepath):
        if not os.path.isfile(filepath) or not is_image_file(filepath):
            messagebox.showwarning("警告", f"跳过非图片文件：{filepath}")
            return
        # 移除去重检查，允许同一文件不同模板多次添加
        template = self.capture_current_template()
        item = BatchItem(filepath, template)
        self.batch_items.append(item)
        mode_name = {"grid":"网格", "smart":"智能", "advanced":"高级", "free":"自由"}.get(template["mode"], template["mode"])
        # 显示详细信息
        detail = ""
        if template["mode"] == "grid":
            detail = f"{template['rows']}x{template['cols']}"
        elif template["mode"] == "smart":
            detail = template["digit_entry"][:10]
        elif template["mode"] == "advanced":
            detail = "嵌套"
        elif template["mode"] == "free":
            detail = f"{len(template.get('free_rects', []))}矩形"
        display = f"{os.path.basename(filepath)} [{mode_name}] {detail}".strip()
        self.batch_listbox.insert(tk.END, display)

    def add_current_image(self):
        img_path = self.entry1.get().strip()
        if not img_path or not os.path.isfile(img_path):
            messagebox.showwarning("提示", "请先在主界面选择一张图片")
            return
        if not is_image_file(img_path):
            messagebox.showerror("错误", "当前文件不是支持的图片格式")
            return
        self.add_batch_item(img_path)

    def batch_add_images(self):
        paths = filedialog.askopenfilenames(
            title="选择图片文件",
            filetypes=[("所有支持的图片", SUPPORTED_IMG_FILTER), ("所有文件", "*.*")]
        )
        for p in paths:
            self.add_batch_item(p)

    def batch_add_folder(self):
        folder = filedialog.askdirectory(title="选择包含图片的文件夹")
        if not folder:
            return
        for root, dirs, files in os.walk(folder):
            for f in files:
                full = os.path.join(root, f)
                if is_image_file(full):
                    self.add_batch_item(full)

    def batch_clear_list(self):
        if messagebox.askyesno("确认", "清空批量列表？"):
            self.batch_items.clear()
            self.batch_listbox.delete(0, tk.END)

    def batch_remove_selected(self):
        selected = self.batch_listbox.curselection()
        if not selected:
            return
        for idx in reversed(selected):
            del self.batch_items[idx]
            self.batch_listbox.delete(idx)

    def on_drop_to_batch_list(self, event):
        files = self.master.tk.splitlist(event.data)
        for f in files:
            if os.path.isfile(f):
                self.add_batch_item(f)
            elif os.path.isdir(f):
                for root, dirs, files_in_dir in os.walk(f):
                    for file in files_in_dir:
                        full = os.path.join(root, file)
                        if is_image_file(full):
                            self.add_batch_item(full)

    def batch_start_cutting(self):
        if not self.batch_items:
            messagebox.showinfo("提示", "批量列表为空，请先添加图片")
            return
        base_out_dir = self.entry2.get().strip()
        if not base_out_dir:
            base_out_dir = filedialog.askdirectory(title="选择批量输出的根目录")
            if not base_out_dir:
                return
    
        total = len(self.batch_items)
        # 创建进度窗口
        self.batch_progress_win = tk.Toplevel(self.master)
        self.batch_progress_win.title("批量切割进度")
        self.batch_progress_win.transient(self.master)
        self.batch_progress_win.grab_set()
        self.batch_progress_win.geometry("350x120")
        self.batch_progress_win.update_idletasks()
        x = (self.batch_progress_win.winfo_screenwidth() - 350) // 2
        y = (self.batch_progress_win.winfo_screenheight() - 120) // 2
        self.batch_progress_win.geometry(f"+{x}+{y}")
        tk.Label(self.batch_progress_win, text=f"批量切割进行中，共 {total} 个文件").pack(pady=5)
        self.batch_progress_var = tk.IntVar(value=0)
        self.batch_progress_bar = ttk.Progressbar(self.batch_progress_win, variable=self.batch_progress_var, maximum=total, length=300)
        self.batch_progress_bar.pack(pady=5)
        self.batch_progress_label = tk.Label(self.batch_progress_win, text="0 / {}".format(total))
        self.batch_progress_label.pack(pady=5)
    
        # 禁用批量相关按钮
        for btn in self.master.winfo_children():
            if isinstance(btn, tk.Button) and btn.cget("text") in ("开始批量切割", "批量"):
                btn.config(state=tk.DISABLED)
    
        self.cancel_batch = False
        threading.Thread(target=self._batch_worker, args=(base_out_dir, total), daemon=True).start()

    def _batch_worker(self, base_out_dir, total):
        success_count = 0
        errors = []
        for idx, item in enumerate(self.batch_items, 1):
            if getattr(self, 'cancel_batch', False):
                break
            try:
                self.process_batch_item(item, base_out_dir, idx)
                success_count += 1
            except Exception as e:
                errors.append(f"{item.filepath}: {str(e)}")
            self.master.after(0, self._batch_update_progress, idx)
        self.master.after(0, self._batch_done, success_count, total, errors)
    
    def _batch_update_progress(self, current):
        if hasattr(self, 'batch_progress_win') and self.batch_progress_win.winfo_exists():
            self.batch_progress_var.set(current)
            self.batch_progress_label.config(text=f"{current} / {self.batch_progress_var.get('maximum')}")
            self.batch_progress_win.update_idletasks()
    
    def _batch_done(self, success_count, total, errors):
        # 恢复按钮
        for btn in self.master.winfo_children():
            if isinstance(btn, tk.Button) and btn.cget("text") in ("开始批量切割", "批量"):
                btn.config(state=tk.NORMAL)
    
        if hasattr(self, 'batch_progress_win') and self.batch_progress_win.winfo_exists():
            self.batch_progress_win.destroy()
            self.batch_progress_win = None
    
        if errors:
            err_msg = "\n".join(errors[:5])
            if len(errors) > 5:
                err_msg += f"\n... 共 {len(errors)} 个错误"
            messagebox.showerror("批量切割完成（有错误）", f"成功 {success_count}/{total} 个文件\n错误详情：\n{err_msg}")
        else:
            messagebox.showinfo("批量完成", f"成功处理 {success_count}/{total} 个文件")



    def process_batch_item(self, item, base_out_dir, seq_num):
        img = Image.open(item.filepath)
        template = item.template
        mode = template["mode"]
        fmt = template.get("format", "WEBP")
        quality = template.get("quality", "85")
        
        # 根据复选框决定输出目录和文件前缀
        if self.output_same_dir.get():
            out_dir = base_out_dir
            # 模式标识
            mode_flag = {"grid":"G", "smart":"S", "advanced":"A", "free":"F"}.get(mode, "X")
            prefix = f"{seq_num:03d}_{mode_flag}"
        else:
            basename = os.path.splitext(os.path.basename(item.filepath))[0]
            out_dir = os.path.join(base_out_dir, basename)
            prefix = ""  # 无前缀
        os.makedirs(out_dir, exist_ok=True)
        
        save_params = {"format": fmt}
        if fmt == "JPEG":
            try:
                q = max(1, min(100, int(quality)))
                save_params["quality"] = q
            except:
                save_params["quality"] = 95
        elif fmt == "PNG":
            try:
                l = max(0, min(9, int(quality)))
                save_params["compress_level"] = l
            except:
                save_params["compress_level"] = 6
        elif fmt == "WEBP":
            try:
                q = max(1, min(100, int(quality)))
                save_params["quality"] = q
            except:
                save_params["quality"] = 80
        ext = fmt.lower()
        if fmt in ("JPEG", "WEBP") and img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        
        if mode == "grid":
            rows = int(template["rows"])
            cols = int(template["cols"])
            cut_grid(img, rows, cols, out_dir, ext, save_params, None, prefix)
        elif mode == "smart":
            digit_entry = template["digit_entry"]
            direction = template.get("direction", "horizontal")
            blocks, ratios = parse_smart_pattern(digit_entry)
            if blocks is None:
                raise ValueError("智能数字模式输入格式错误")
            cut_smart(img, blocks, ratios, direction, out_dir, ext, save_params, None, prefix)
        elif mode == "advanced":
            advanced_text = template["advanced_text"]
            direction = template.get("direction", "horizontal")
            group_ratios, pattern = parse_advanced_pattern(advanced_text)
            if pattern is None:
                raise ValueError("高级嵌套模式输入格式错误")
            cut_advanced(img, pattern, group_ratios, direction, out_dir, ext, save_params, None, prefix)
        elif mode == "free":
            rects = template.get("free_rects", [])
            if not rects:
                raise ValueError("自由模式下未定义矩形")
            cut_free(img, rects, out_dir, ext, save_params, None, prefix)

    # ---------- 其他原有方法 ----------
    def reset_parameters(self):
        if not messagebox.askyesno("确认恢复", "确定要将所有切割参数恢复为默认值吗？\n（图片路径和保存路径不会改变）"):
            return
        self.cut_mode.set("grid")
        self.on_mode_changed()
        self.rows_entry.delete(0, tk.END)
        self.rows_entry.insert(0, "2")
        self.cols_entry.delete(0, tk.END)
        self.cols_entry.insert(0, "2")
        self.digit_entry.delete(0, tk.END)
        self.digit_entry.insert(0, "323")
        self.advanced_text.delete("1.0", tk.END)
        self.advanced_text.insert("1.0", "[[1,[100]], [2,[30,70]], [3,[20,30,50]]]")
        self.free_text.delete("1.0", tk.END)
        self.free_text.insert("1.0", "10,10,200,150\n250,30,180,200;50,200,300,100")
        self.direction.set("horizontal")
        self.format_var.set("WEBP")
        self.quality_var.set("85")
        self.on_format_change()
        self.on_free_param_changed()
        self.refresh_preview()
        self.master.update_idletasks()
        self.master.geometry("")
    def toggle_preview_window(self):
        if self.preview_window is not None and self.preview_window.winfo_exists():
            self.close_preview_window()
            self.preview_btn.config(text="打开预览窗口")
        else:
            self.open_preview_window()
            self.preview_btn.config(text="关闭预览窗口")
    
    def resize_preview_window_for_image(self):
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
        main_x = self.master.winfo_x()
        main_y = self.master.winfo_y()
        main_w = self.master.winfo_width()
        if main_x + main_w + new_w + 10 <= screen_w:
            pos_x = main_x + main_w + 10
        else:
            pos_x = screen_w - new_w - 10
        pos_y = main_y
        if pos_y + new_h > screen_h:
            pos_y = max(10, screen_h - new_h - 10)
        self.preview_window.geometry(f"{new_w}x{new_h}+{pos_x}+{pos_y}")
    def open_preview_window(self):
        if self.preview_window is not None and self.preview_window.winfo_exists():
            self.preview_window.lift()
            return
        main_x = self.master.winfo_x()
        main_y = self.master.winfo_y()
        main_w = self.master.winfo_width()
        if self.original_img:
            img_w, img_h = self.original_img.size
            screen_w = self.master.winfo_screenwidth()
            screen_h = self.master.winfo_screenheight()
            max_w = int(screen_w * 0.7)
            max_h = int(screen_h * 0.7)
            scale = min(max_w / img_w, max_h / img_h)
            preview_w = max(300, int(img_w * scale))
            preview_h = max(200, int(img_h * scale))
        else:
            preview_w, preview_h = 600, 500
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
        if self.cut_mode.get() == "free":
            self.on_free_param_changed()
            self.refresh_preview()
        if self.cut_mode.get() == "free" and self.drawing_enabled:
            self.toggle_interactive_mode()
            self.toggle_interactive_mode()
    def close_preview_window(self):
        if self.preview_window:
            self.preview_window.destroy()
            self.preview_window = None
            self.preview_canvas = None
        self.preview_btn.config(text="打开预览窗口")
        self.drawing_enabled = False
        self.interactive_btn.config(text="启用交互绘制", bg="#f0f0f0")
    def on_preview_canvas_resize(self, event):
        if self.original_img and self.preview_canvas:
            self.update_preview_in_subwindow()
    def update_preview_in_subwindow(self):
        if not self.original_img or not self.preview_canvas:
            return
        cw = self.preview_canvas.winfo_width()
        ch = self.preview_canvas.winfo_height()
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
        blocks, ratios = parse_smart_pattern(self.digit_entry.get().strip())
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

    def _parse_advanced_pattern(self, text):
        group_ratios, pattern = parse_advanced_pattern(text)
        if pattern is None:
            self.advanced_parse_error = "高级模式格式错误，请检查语法"
        else:
            self.advanced_parse_error = None
        return group_ratios, pattern

    def draw_advanced_lines_sub(self):
        if not self.original_img or not self.preview_canvas:
            return
        self.preview_canvas.delete("cut_line")
        text = self.advanced_text.get("1.0", tk.END).strip()
        group_ratios, pattern = self._parse_advanced_pattern(text)
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
            for i in range(1, n):
                self.preview_canvas.create_line(cum_x[i], y0, cum_x[i], y0+ph, fill="red", width=2, tags="cut_line")
            for col_idx, (blk, ratios) in enumerate(pattern):
                left = cum_x[col_idx]
                right = cum_x[col_idx+1]
                if ratios is None:
                    blk_h = ph / blk
                    for b in range(1, blk):
                        line_y = y0 + b * blk_h
                        self.preview_canvas.create_line(left, line_y, right, line_y, fill="blue", width=2, tags="cut_line")
                else:
                    cum_y = y0
                    for b, r in enumerate(ratios):
                        seg_h = ph * (r[0] / 100.0)
                        next_y = cum_y + seg_h
                        if b < blk - 1:
                            self.preview_canvas.create_line(left, next_y, right, next_y, fill="blue", width=2, tags="cut_line")
                        cum_y = next_y
        else:
            n = len(pattern)
            if group_ratios is None:
                row_heights = [ph / n] * n
            else:
                row_heights = [ph * (r / 100.0) for r in group_ratios]
            cum_y = [y0]
            for h in row_heights:
                cum_y.append(cum_y[-1] + h)
            for i in range(1, n):
                self.preview_canvas.create_line(x0, cum_y[i], x0+pw, cum_y[i], fill="red", width=2, tags="cut_line")
            for row_idx, (blk, ratios) in enumerate(pattern):
                top = cum_y[row_idx]
                bottom = cum_y[row_idx+1]
                if ratios is None:
                    blk_w = pw / blk
                    for b in range(1, blk):
                        line_x = x0 + b * blk_w
                        self.preview_canvas.create_line(line_x, top, line_x, bottom, fill="blue", width=2, tags="cut_line")
                else:
                    cum_x = x0
                    for b, r in enumerate(ratios):
                        seg_w = pw * (r[0] / 100.0)
                        next_x = cum_x + seg_w
                        if b < blk - 1:
                            self.preview_canvas.create_line(next_x, top, next_x, bottom, fill="blue", width=2, tags="cut_line")
                        cum_x = next_x
    def draw_free_lines_sub(self):
        if not self.original_img or not self.preview_canvas:
            return
        self.preview_canvas.delete("cut_line")
        rects = self.free_rects
        if not rects:
            return
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
    # 事件处理
    def on_mode_changed(self):
        self.update_dir_frame_visibility()
        if self.cut_mode.get() == "grid":
            self.grid_frame.grid()
            self.smart_frame.grid_remove()
            self.advanced_frame.grid_remove()
            self.free_frame.grid_remove()
            self.refresh_preview()
        elif self.cut_mode.get() == "smart":
            self.grid_frame.grid_remove()
            self.smart_frame.grid()
            self.advanced_frame.grid_remove()
            self.free_frame.grid_remove()
            self.refresh_preview()
        elif self.cut_mode.get() == "advanced":
            self.grid_frame.grid_remove()
            self.smart_frame.grid_remove()
            self.advanced_frame.grid()
            self.free_frame.grid_remove()
            self.refresh_preview()
        else:
            self.grid_frame.grid_remove()
            self.smart_frame.grid_remove()
            self.advanced_frame.grid_remove()
            self.free_frame.grid()
            self.on_free_param_changed()
        self.master.update_idletasks()
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
            rects = parse_free_pattern(self.free_text.get("1.0", tk.END).strip())
            if rects is None:
                messagebox.showwarning("格式错误", "自由模式矩形定义无效，请检查语法")
                return
            self.free_rects = rects
            self.refresh_preview()
    def update_dir_frame_visibility(self):
        if self.cut_mode.get() in ("grid", "free"):
            self.dir_frame.grid_remove()
        else:
            self.dir_frame.grid()
    def refresh_preview(self):
        if self.preview_window and self.preview_canvas and self.original_img:
            self.update_preview_in_subwindow()
    # 图片加载
    def load_preview_image(self, file_path):
        if not file_path or not os.path.isfile(file_path):
            return
        if not is_image_file(file_path):
            messagebox.showerror("错误", f"不支持的文件格式！\n请选择以下图片格式：\n{', '.join(SUPPORTED_IMG_EXT)}")
            return
        try:
            self.original_img = Image.open(file_path)
            if not (self.preview_window and self.preview_window.winfo_exists()):
                self.open_preview_window()
            else:
                self.resize_preview_window_for_image()
                self.refresh_preview()
        except Exception as e:
            messagebox.showerror("错误", f"图片加载失败: {e}")
    # 文件操作
    def select_file(self):
        path = filedialog.askopenfilename(
            title="选择图片文件",
            filetypes=[
                ("所有支持的图片", SUPPORTED_IMG_FILTER),
                ("所有文件", "*.*")
            ]
        )
        if path:
            if not is_image_file(path):
                messagebox.showerror("错误", f"不支持的文件格式！\n请选择以下图片格式：\n{', '.join(SUPPORTED_IMG_EXT)}")
                return
            self.entry1.delete(0, tk.END)
            self.entry1.insert(0, path)
            self.load_preview_image(path)
    def on_drop_to_entry1(self, event):
        files = self.master.tk.splitlist(event.data)
        if files and os.path.isfile(files[0]):
            filepath = files[0]
            if not is_image_file(filepath):
                messagebox.showerror("错误", f"不支持的文件格式！\n请拖拽以下图片格式：\n{', '.join(SUPPORTED_IMG_EXT)}")
                return
            self.entry1.delete(0, tk.END)
            self.entry1.insert(0, filepath)
            self.load_preview_image(filepath)
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
        if not is_image_file(img_path):
            messagebox.showerror("错误", f"不支持的文件格式！\n请选择以下图片格式：\n{', '.join(SUPPORTED_IMG_EXT)}")
            return
        out_dir = self.entry2.get().strip()
        if not out_dir:
            out_dir = os.path.dirname(img_path)
        elif not os.path.isdir(out_dir):
            messagebox.showerror("错误", f"保存目录不存在: {out_dir}")
            return
        os.makedirs(out_dir, exist_ok=True)
    
        try:
            image = Image.open(img_path)
            fmt = self.format_var.get()
            if fmt in ("JPEG", "WEBP") and image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGB")
            save_params = self.get_save_params(fmt)
            ext = fmt.lower()
            mode = self.cut_mode.get()
    
            # 计算总块数（用于进度条）
            if mode == "grid":
                rows = int(self.rows_entry.get())
                cols = int(self.cols_entry.get())
                total_pieces = rows * cols
            elif mode == "smart":
                blocks, _ = parse_smart_pattern(self.digit_entry.get().strip())
                if blocks is None:
                    raise ValueError("智能数字模式输入格式错误")
                total_pieces = sum(blocks)
            elif mode == "advanced":
                _, pattern = parse_advanced_pattern(self.advanced_text.get("1.0", tk.END).strip())
                if pattern is None:
                    raise ValueError("高级嵌套模式输入格式错误")
                total_pieces = 0
                for blk, ratios in pattern:
                    if ratios is None:
                        total_pieces += blk
                    else:
                        total_pieces += sum(1 for _, flag in ratios if flag)
            else:
                rects = parse_free_pattern(self.free_text.get("1.0", tk.END).strip())
                if rects is None:
                    raise ValueError("自由模式矩形定义错误")
                total_pieces = len(rects)
    
            # 创建进度窗口（稍后由后台线程更新）
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
            tk.Label(self.progress_win, text=f"正在切割，共 {total_pieces} 张...").pack(pady=5)
            self.progress_var = tk.IntVar(value=0)
            self.progress_bar = ttk.Progressbar(self.progress_win, variable=self.progress_var, maximum=total_pieces, length=250)
            self.progress_bar.pack(pady=5)
            self.progress_label = tk.Label(self.progress_win, text="0 / {}".format(total_pieces))
            self.progress_label.pack(pady=5)
    
            # 禁用开始按钮，防止重复启动
            for btn in self.master.winfo_children():
                if isinstance(btn, tk.Button) and btn.cget("text") in ("开始切割", "批量"):
                    btn.config(state=tk.DISABLED)
    
            # 启动后台线程
            self.cancel_cut = False
            threading.Thread(target=self._cut_worker, args=(
                image, mode, out_dir, ext, save_params, total_pieces
            ), daemon=True).start()
    
        except Exception as e:
            messagebox.showerror("错误", f"准备切割时出错: {e}")
            if hasattr(self, 'progress_win') and self.progress_win.winfo_exists():
                self.progress_win.destroy()

    def _cut_worker(self, image, mode, out_dir, ext, save_params, total_pieces):
        try:
            # 进度回调（线程安全）
            def progress_callback(current):
                self.master.after(0, self._update_progress, current)
    
            if mode == "grid":
                rows = int(self.rows_entry.get())
                cols = int(self.cols_entry.get())
                cut_grid(image, rows, cols, out_dir, ext, save_params, progress_callback)
                msg = f"标准网格切割完成！共生成 {rows*cols} 张小图"
            elif mode == "smart":
                blocks, ratios = parse_smart_pattern(self.digit_entry.get().strip())
                cut_smart(image, blocks, ratios, self.direction.get(), out_dir, ext, save_params, progress_callback)
                msg = f"智能数字模式切割完成！共生成 {sum(blocks)} 张小图"
            elif mode == "advanced":
                group_ratios, pattern = parse_advanced_pattern(self.advanced_text.get("1.0", tk.END).strip())
                cut_advanced(image, pattern, group_ratios, self.direction.get(), out_dir, ext, save_params, progress_callback)
                total = 0
                for blk, ratios in pattern:
                    if ratios is None:
                        total += blk
                    else:
                        total += sum(1 for _, flag in ratios if flag)
                msg = f"高级嵌套模式切割完成！共生成 {total} 张小图"
            else:
                rects = self.free_rects
                cut_free(image, rects, out_dir, ext, save_params, progress_callback)
                msg = f"自由模式切割完成！共生成 {len(rects)} 张小图"
    
            self.master.after(0, self._cut_done, True, msg, out_dir)
    
        except Exception as e:
            self.master.after(0, self._cut_done, False, str(e), None)

    def _update_progress(self, current):
        if hasattr(self, 'progress_win') and self.progress_win.winfo_exists():
            self.progress_var.set(current)
            self.progress_label.config(text=f"{current} / {self.progress_var.get('maximum')}")
            self.progress_win.update_idletasks()
    
    def _cut_done(self, success, info, out_dir=None):
        # 恢复按钮
        for btn in self.master.winfo_children():
            if isinstance(btn, tk.Button) and btn.cget("text") in ("开始切割", "批量"):
                btn.config(state=tk.NORMAL)
    
        if hasattr(self, 'progress_win') and self.progress_win.winfo_exists():
            self.progress_win.destroy()
            self.progress_win = None
    
        if success:
            messagebox.showinfo("完成", f"{info}\n格式：{self.format_var.get()}\n保存在：{out_dir}")
        else:
            messagebox.showerror("错误", f"切割失败: {info}")


    # 交互绘制方法（自由模式）
    def on_preset_ratio(self, event=None):
        self.ratio_var.set(self.ratio_preset.get())
    def parse_ratio(self, ratio_str):
        ratio_str = ratio_str.strip()
        if ':' not in ratio_str:
            return None
        parts = ratio_str.split(':', 1)
        try:
            w = float(parts[0])
            h = float(parts[1])
            if w <= 0 or h <= 0:
                return None
            return w / h
        except:
            return None
    def toggle_interactive_mode(self):
        if self.cut_mode.get() != "free":
            messagebox.showinfo("提示", "交互绘制仅在自由模式下可用")
            return
        if not self.preview_canvas:
            messagebox.showinfo("提示", "请先打开预览窗口并加载图片")
            return
        self.drawing_enabled = not self.drawing_enabled
        if self.drawing_enabled:
            self.interactive_btn.config(text="禁用交互绘制", bg="#90ee90")
            self.preview_canvas.bind("<ButtonPress-1>", self.on_mouse_down)
            self.preview_canvas.bind("<B1-Motion>", self.on_mouse_move)
            self.preview_canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
            self.preview_canvas.bind("<Delete>", self.delete_selected_rect)
            self.preview_canvas.focus_set()
        else:
            self.interactive_btn.config(text="启用交互绘制", bg="#f0f0f0")
            self.preview_canvas.unbind("<ButtonPress-1>")
            self.preview_canvas.unbind("<B1-Motion>")
            self.preview_canvas.unbind("<ButtonRelease-1>")
            self.preview_canvas.unbind("<Delete>")
            if self.rect_id:
                self.preview_canvas.delete(self.rect_id)
                self.rect_id = None
    def on_mouse_down(self, event):
        if not self.drawing_enabled or not self.original_img:
            return
        canvas_x = event.x
        canvas_y = event.y
        x0, y0, w, h = self.preview_img_pos
        if not (x0 <= canvas_x <= x0 + w and y0 <= canvas_y <= y0 + h):
            return
        self.start_x = canvas_x
        self.start_y = canvas_y
        self.rect_id = self.preview_canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="orange", width=2, tags="temp_rect"
        )
    def on_mouse_move(self, event):
        if self.start_x is None or self.rect_id is None:
            return
        canvas_x = event.x
        canvas_y = event.y
        x0, y0, w, h = self.preview_img_pos
        canvas_x = max(x0, min(x0 + w, canvas_x))
        canvas_y = max(y0, min(y0 + h, canvas_y))
        if self.lock_ratio.get():
            ratio_str = self.ratio_var.get()
            ratio = self.parse_ratio(ratio_str)
            if ratio is not None:
                dx = canvas_x - self.start_x
                dy = canvas_y - self.start_y
                if abs(dx) >= abs(dy):
                    new_dx = dx
                    new_dy = abs(dx) / ratio if dx != 0 else 0
                    if dy < 0:
                        new_dy = -new_dy
                    canvas_y = self.start_y + new_dy
                else:
                    new_dy = dy
                    new_dx = abs(dy) * ratio if dy != 0 else 0
                    if dx < 0:
                        new_dx = -new_dx
                    canvas_x = self.start_x + new_dx
                canvas_x = max(x0, min(x0 + w, canvas_x))
                canvas_y = max(y0, min(y0 + h, canvas_y))
        self.preview_canvas.coords(self.rect_id, self.start_x, self.start_y, canvas_x, canvas_y)
    def on_mouse_up(self, event):
        if self.start_x is None or self.rect_id is None:
            return
        canvas_x = event.x
        canvas_y = event.y
        x0, y0, w, h = self.preview_img_pos
        canvas_x = max(x0, min(x0 + w, canvas_x))
        canvas_y = max(y0, min(y0 + h, canvas_y))
        if self.lock_ratio.get():
            ratio_str = self.ratio_var.get()
            ratio = self.parse_ratio(ratio_str)
            if ratio is not None:
                dx = canvas_x - self.start_x
                dy = canvas_y - self.start_y
                if abs(dx) >= abs(dy):
                    new_dx = dx
                    new_dy = abs(dx) / ratio if dx != 0 else 0
                    if dy < 0:
                        new_dy = -new_dy
                    canvas_y = self.start_y + new_dy
                else:
                    new_dy = dy
                    new_dx = abs(dy) * ratio if dy != 0 else 0
                    if dx < 0:
                        new_dx = -new_dx
                    canvas_x = self.start_x + new_dx
                canvas_x = max(x0, min(x0 + w, canvas_x))
                canvas_y = max(y0, min(y0 + h, canvas_y))
        img_w, img_h = self.original_img.size
        scale_x = img_w / w
        scale_y = img_h / h
        left = min(self.start_x, canvas_x)
        right = max(self.start_x, canvas_x)
        top = min(self.start_y, canvas_y)
        bottom = max(self.start_y, canvas_y)
        orig_left = int((left - x0) * scale_x)
        orig_top = int((top - y0) * scale_y)
        orig_right = int((right - x0) * scale_x)
        orig_bottom = int((bottom - y0) * scale_y)
        if orig_right > orig_left and orig_bottom > orig_top:
            x = orig_left
            y = orig_top
            w = orig_right - orig_left
            h = orig_bottom - orig_top
            self.free_rects.append((x, y, w, h))
            self.update_free_text_from_rects()
            self.refresh_preview()
        self.preview_canvas.delete(self.rect_id)
        self.rect_id = None
        self.start_x = None
        self.start_y = None
    def delete_selected_rect(self, event):
        if self.free_rects:
            self.free_rects.pop()
            self.update_free_text_from_rects()
            self.refresh_preview()
    def clear_all_rects(self):
        self.free_rects.clear()
        self.update_free_text_from_rects()
        self.refresh_preview()
    def delete_last_rect(self):
        if self.free_rects:
            self.free_rects.pop()
            self.update_free_text_from_rects()
            self.refresh_preview()
    def update_free_text_from_rects(self):
        lines = []
        for x, y, w, h in self.free_rects:
            lines.append(f"{x},{y},{w},{h}")
        self.free_text.delete("1.0", tk.END)
        self.free_text.insert("1.0", "\n".join(lines))
        self.on_free_param_changed()
    def on_ratio_lock_changed(self):
        pass
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
    root.withdraw()
    app = App(root)

    # 接收外部图片路径
    if len(sys.argv) > 1:
        external_path = sys.argv[1]
        if os.path.isfile(external_path) and is_image_file(external_path):
            app.entry1.delete(0, tk.END)
            app.entry1.insert(0, external_path)
            app.load_preview_image(external_path)
        else:
            print(f"警告：传入的参数不是有效的图片文件：{external_path}")

    center_window(root)
    root.deiconify()
    root.mainloop()
