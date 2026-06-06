import tkinter as tk
from tkinter import scrolledtext, messagebox
import re

class LrcTimeShifter:
    def __init__(self, root):
        self.root = root
        self.root.title("LRC 歌词时间整体偏移工具")
        self.root.geometry("1200x900")

        window_width = 1200
        window_height = 900
        screen_width = self.root.winfo_screenwidth()   # 获取屏幕宽度
        screen_height = self.root.winfo_screenheight() # 获取屏幕高度
        center_x = int((screen_width - window_width) / 2)
        center_y = int((screen_height - window_height) / 2)
        self.root.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
        
        # --- 界面布局 ---
        # 1. 原始歌词输入区
        tk.Label(root, text="在此粘贴原始 LRC 歌词内容：", font=("微软雅黑", 10)).pack(pady=5, anchor="w", padx=10)
        self.input_text = scrolledtext.ScrolledText(root, height=15, font=("Consolas", 9))
        self.input_text.pack(padx=10, fill="both", expand=True)

        # 2. 偏移量输入与控制区
        control_frame = tk.Frame(root)
        control_frame.pack(pady=10, fill="x", padx=10)

        tk.Label(control_frame, text="请输入偏移量(纯数字或标准格式)：", font=("微软雅黑", 10)).pack(side="left")
        
        # 提示语同时展示两种支持的格式
        self.offset_entry = tk.Entry(control_frame, font=("Consolas", 10), width=40)
        self.offset_entry.insert(0, "如 1500 -1500 或 -00:01.12") 
        self.offset_entry.config(fg='grey') 
        
        def on_focus_in(event):
            if self.offset_entry.get() == "如 1500 -1500 或 -00:01.12":
                self.offset_entry.delete(0, tk.END)
                self.offset_entry.config(fg='black')
                
        def on_focus_out(event):
            if self.offset_entry.get() == "":
                self.offset_entry.insert(0, "如 1500 -1500 或 -00:01.12")
                self.offset_entry.config(fg='grey')

        self.offset_entry.bind("<FocusIn>", on_focus_in)
        self.offset_entry.bind("<FocusOut>", on_focus_out)
        self.offset_entry.pack(side="left", padx=5)

        self.process_btn = tk.Button(control_frame, text="开始整体偏移", bg="#4CAF50", fg="white", font=("微软雅黑", 10), command=self.shift_time)
        self.process_btn.pack(side="left", padx=10)

        # 3. 结果输出区
        tk.Label(root, text="处理后的 LRC 歌词结果：", font=("微软雅黑", 10)).pack(pady=5, anchor="w", padx=10)
        self.output_text = scrolledtext.ScrolledText(root, height=10, font=("Consolas", 9))
        self.output_text.pack(padx=10, fill="both", expand=True)

        # 4. 底部复制按钮
        self.copy_btn = tk.Button(root, text="复制结果到剪贴板", bg="#2196F3", fg="white", font=("微软雅黑", 10), command=self.copy_result)
        self.copy_btn.pack(pady=10)

    def parse_offset_input(self, text):
        """智能解析偏移量输入：支持纯数字(毫秒) 或 时间格式(如 -00:01.12)"""
        text = text.strip()
        # 1. 尝试直接解析为纯数字（毫秒）
        try:
            return int(text)
        except ValueError:
            pass
        
        # 2. 尝试解析为时间格式 [分:秒.毫秒]，支持负号
        # 匹配可选的负号，以及分:秒.毫秒(2到3位)
        match = re.match(r'^(-?)(\d{1,2}):(\d{2})\.(\d{2,3})$', text)
        if match:
            sign = -1 if match.group(1) == '-' else 1
            minutes = int(match.group(2))
            seconds = int(match.group(3))
            # 补齐毫秒为3位 (如 12 -> 120ms, 123 -> 123ms)
            ms_str = match.group(4).ljust(3, '0')
            milliseconds = int(ms_str)
            
            total_ms = sign * (minutes * 60000 + seconds * 1000 + milliseconds)
            return total_ms
        
        return None

    def format_time(self, total_ms):
        """将总毫秒数转换回 [mm:ss.xx] 格式"""
        if total_ms < 0:
            total_ms = 0
        minutes = total_ms // 60000
        seconds = (total_ms % 60000) // 1000
        milliseconds = (total_ms % 1000) // 10 # 保留两位毫秒
        return f"[{minutes:02d}:{seconds:02d}.{milliseconds:02d}]"

    def shift_time(self):
        """核心逻辑：读取输入，计算偏移，输出结果"""
        raw_content = self.input_text.get("1.0", tk.END).strip()
        offset_input = self.offset_entry.get().strip()

        if offset_input == "如 1500 -1500 或 -00:01.12":
            messagebox.showwarning("提示", "请先输入正确的偏移量！")
            return

        if not raw_content:
            messagebox.showwarning("提示", "请先输入原始 LRC 歌词内容！")
            return

        # 【核心修复】使用智能解析函数
        offset_ms = self.parse_offset_input(offset_input)
        
        if offset_ms is None:
            messagebox.showerror("错误", "偏移量格式不正确！\n请输入纯数字（如 1500）或标准时间格式（如 00:01.12）。")
            return

        # 正则表达式匹配 LRC 时间标签 [分:秒.毫秒]
        time_pattern = re.compile(r'\[\d{1,2}:\d{2}\.\d{2,3}\]')
        
        lines = raw_content.split('\n')
        new_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                new_lines.append("")
                continue
            
            matches = time_pattern.findall(line)
            if matches:
                new_line = line
                # 从后往前替换，防止索引错乱
                for match in reversed(matches):
                    # 提取原时间并转为毫秒
                    time_str = match.strip('[]')
                    parts = time_str.split(':')
                    minutes = int(parts[0])
                    sec_parts = parts[1].split('.')
                    seconds = int(sec_parts[0])
                    ms_part = sec_parts[1].ljust(3, '0')
                    milliseconds = int(ms_part)
                    
                    original_ms = minutes * 60000 + seconds * 1000 + milliseconds
                    
                    # 加上偏移量
                    new_ms = original_ms + offset_ms
                    new_time_str = self.format_time(new_ms)
                    
                    new_line = new_line.replace(match, new_time_str, 1)
                new_lines.append(new_line)
            else:
                new_lines.append(line)

        result = '\n'.join(new_lines)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", result)
        messagebox.showinfo("完成", f"已成功按 {offset_ms} 毫秒进行整体偏移！")

    def copy_result(self):
        """复制结果到剪贴板"""
        result = self.output_text.get("1.0", tk.END).strip()
        if result:
            self.root.clipboard_clear()
            self.root.clipboard_append(result)
            messagebox.showinfo("成功", "结果已复制到剪贴板！")
        else:
            messagebox.showwarning("提示", "没有可复制的内容！")

if __name__ == "__main__":
    root = tk.Tk()
    app = LrcTimeShifter(root)
    root.mainloop()