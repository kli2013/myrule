-- 配置方法
-- 
-- 在 mpv.conf 所在目录创建 script-opts/multi_cut.conf，内容示例：
-- ffmpeg_path=D:\ffmpeg\bin\ffmpeg.exe
-- log_dir=D:\cut_logs
-- use_bom=yes
-- prefer_copy=yes
-- 或通过命令行覆盖：
-- mpv --script-opts=multi_cut:ffmpeg_path=ffmpeg.exe,multi_cut:log_dir=C:\temp ...


local utils = require 'mp.utils'
local options = require 'mp.options'

local o = {
    ffmpeg_path = 'ffmpeg.exe',      -- 可通过 script-opts=multi_cut:ffmpeg_path=... 覆盖
    log_dir = 'c:/FFmpeg',            -- nil 表示保存在视频同目录；建议修改为有写入权限的目录
    use_bom = true,                  -- 是否写入 UTF-8 BOM
    prefer_copy = true,              -- 优先尝试无损复制
}
options.read_options(o, 'multi_cut')

local marking_mode = false
local segments = {}
local current_segment_start = nil

-- ====================== 日志写入（带警告） ======================
local function write_cut_log(content, log_file_path)
    if not log_file_path then return end

    local f = io.open(log_file_path, 'a')
    if not f then
        mp.msg.warn("无法写入日志文件: " .. log_file_path)
        return
    end

    -- 只在新文件时添加 BOM
    if o.use_bom then
        local size = f:seek("end")
        if size == 0 then
            f:write('\xef\xbb\xbf')
        end
    end

    f:write(content .. '\n')
    f:flush()
    f:close()
end

-- ====================== 章节标记 ======================
local function update_chapter_marks()
    local chapters = {}
    for i, seg in ipairs(segments) do
        if seg.start then
            table.insert(chapters, {
                title = string.format("Seg%d 开始 %.2fs", i, seg.start),
                time = seg.start
            })
        end
        if seg.end_ then
            table.insert(chapters, {
                title = string.format("Seg%d 结束 %.2fs", i, seg.end_),
                time = seg.end_
            })
        end
    end
    mp.set_property_native("chapter-list", chapters)
end

-- ====================== 模式切换 ======================
local function toggle_marking_mode()
    if not marking_mode then
        marking_mode = true
        segments = {}
        current_segment_start = nil
        update_chapter_marks()
        mp.osd_message("已进入标记模式！\n→ n : 标记起点/终点\n→ c : 确认切割\n→ Esc : 退出", 5)
    else
        marking_mode = false
        segments = {}
        current_segment_start = nil
        update_chapter_marks()
        mp.osd_message("已退出标记模式", 3)
    end
end

-- ====================== 标记时间点 ======================
local function mark_current_time()
    if not marking_mode then
        mp.osd_message("未进入标记模式！请按 Ctrl+m", 3)
        return
    end

    local pos = mp.get_property_number("time-pos")
    if not pos then return end

    if not current_segment_start then
        current_segment_start = pos
        table.insert(segments, {start = pos})
        mp.osd_message(string.format("✓ 开始点: %.2fs", pos), 2)
    else
        local n = #segments
        segments[n].end_ = pos
        current_segment_start = nil
        mp.osd_message(string.format("✓ 结束点: %.2fs\n当前共 %d 个片段", pos, n), 3)
    end

    update_chapter_marks()
end

-- ====================== 构建命令字符串（用于日志） ======================
local function build_command_string(args)
    local parts = {}
    -- 跳过 "cmd" 和 "/c"，从 ffmpeg 开始
    for i = 3, #args do
        local arg = tostring(args[i])
        if arg:find("[ \t]") or arg:find('"') then
            arg = '"' .. arg:gsub('"', '\\"') .. '"'
        end
        table.insert(parts, arg)
    end
    return table.concat(parts, " ")
end

-- ====================== 确认切割（核心修复版） ======================
local function confirm_marks()
    if not marking_mode or #segments == 0 then
        mp.osd_message("没有标记片段", 3)
        return
    end

    -- 检查未闭合片段（仅警告）
    local open_segments = {}
    for i, s in ipairs(segments) do
        if s.start and not s.end_ then
            table.insert(open_segments, i)
        end
    end
    if #open_segments > 0 then
        local warn_msg = string.format("⚠ 有 %d 个片段未标记终点（片段 %s），将被忽略",
            #open_segments, table.concat(open_segments, ", "))
        mp.osd_message(warn_msg, 5)
        mp.msg.warn(warn_msg)
    end

    local valid = {}
    for _, s in ipairs(segments) do
        if s.start and s.end_ and s.start < s.end_ then
            table.insert(valid, s)
        end
    end

    if #valid == 0 then
        mp.osd_message("没有有效片段", 3)
        return
    end

    -- ========== 新增：获取视频路径 ==========
    local path = mp.get_property("path")
    if not path or path == "" then
        mp.osd_message("无法获取文件路径", 3)
        return
    end
    -- =====================================


    -- ---------- 路径处理（完全依赖 utils.join_path，不手动加分隔符）----------
    local dir, filename = utils.split_path(path)
    if not dir then dir = "" end   -- 防止 nil
    local base = filename:match("(.+)%.[^%.]+$") or "output"
    local ext = filename:match("(%.[^%.]+)$") or ".mp4"
    local out_ext = (ext:lower() == ".ts" or ext:lower() == ".flv") and ".mp4" or ext

    local ffmpeg = o.ffmpeg_path or 'ffmpeg.exe'

    -- ---------- 确定日志文件路径并确保目录存在 ----------
    local log_file
    if o.log_dir and o.log_dir ~= "" then
        log_file = utils.join_path(o.log_dir, "cutlog.txt")
        -- 使用 mkdir /p 创建多级目录，忽略错误（目录可能已存在）
        utils.subprocess({args = {"cmd", "/c", "mkdir", o.log_dir, "/p"}, cancellable = false, playback_only = false})
    else
        log_file = utils.join_path(dir, "cutlog.txt")
    end

    -- 日志头部
    write_cut_log("=====================================", log_file)
    write_cut_log("切割时间: " .. os.date("%Y-%m-%d %H:%M:%S"), log_file)
    write_cut_log("源文件: " .. path, log_file)
    write_cut_log("-------------------------------------", log_file)

    -- ---------- 逐个片段处理 ----------
    for i, seg in ipairs(valid) do
        local duration = seg.end_ - seg.start
        local s_str = string.format("%.2f", seg.start):gsub("%.", "-")
        local e_str = string.format("%.2f", seg.end_):gsub("%.", "-")
        local out = utils.join_path(dir, string.format("%s_cut_seg%d_%s-%s%s", base, i, s_str, e_str, out_ext))

        mp.osd_message(string.format("正在处理片段 %d/%d...", i, #valid), 2)

        local cmd_args = nil
        local success = false

        -- 1. 尝试无损复制
        if o.prefer_copy then
            local copy_args = {
                "cmd", "/c", ffmpeg,
                "-ss", string.format("%.3f", seg.start),
                "-i", path,
                "-t", string.format("%.3f", duration),
                "-c", "copy",
                "-map_metadata", "0",
                "-movflags", "+faststart",
                "-ignore_unknown",
                "-avoid_negative_ts", "make_zero",
                "-y", out
            }

            local res = utils.subprocess({args = copy_args, cancellable = false, playback_only = false})
            if res.status == 0 then
                success = true
                cmd_args = copy_args
                mp.osd_message(string.format("片段 %d 无损完成", i), 2)
            else
                -- 输出错误信息到控制台/日志（可选）
                if res.stderr and res.stderr ~= "" then
                    mp.msg.warn("片段 %d 无损复制失败，FFmpeg stderr: %s", i, res.stderr:sub(1, 200))
                end
            end
        end

        -- 2. 无损失败则转码
        if not success then
            local transcode_args = {
                "cmd", "/c", ffmpeg,
                "-ss", string.format("%.3f", seg.start),
                "-i", path,
                "-t", string.format("%.3f", duration),
                "-map_metadata", "0",
                "-movflags", "+faststart",
                "-ignore_unknown",
                "-avoid_negative_ts", "make_zero",
                "-y", out
            }

            if out_ext:lower() == ".webm" then
                local vp9 = {"-c:v", "libvpx-vp9", "-crf", "23", "-b:v", "0", "-c:a", "libopus"}
                for _, v in ipairs(vp9) do table.insert(transcode_args, v) end
            else
                local x264 = {"-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "128k"}
                for _, v in ipairs(x264) do table.insert(transcode_args, v) end
            end

            local res = utils.subprocess({args = transcode_args, cancellable = false, playback_only = false})
            if res.status == 0 then
                success = true
                cmd_args = transcode_args
                mp.osd_message(string.format("片段 %d 转码完成", i), 2)
            else
                mp.osd_message(string.format("片段 %d 处理失败", i), 4)
                if res.stderr and res.stderr ~= "" then
                    mp.msg.error("片段 %d 转码失败，FFmpeg stderr: %s", i, res.stderr:sub(1, 200))
                end
                -- 失败时不记录该片段的命令（或可选择记录）
                cmd_args = nil
            end
        end

        -- 写入成功片段的命令到日志
        if success and cmd_args then
            local cmd_str = build_command_string(cmd_args)
            write_cut_log(cmd_str, log_file)
        end
    end

    write_cut_log("-------------------------------------\n", log_file)

    -- 完成清理
    current_segment_start = nil
    marking_mode = false
    update_chapter_marks()

    mp.osd_message(string.format("✅ 全部完成！共 %d 个片段\n日志文件: %s", #valid, log_file or "无"), 6)
end

-- ====================== 快捷键绑定 ======================
mp.add_key_binding("Ctrl+m", "toggle_marking_mode", toggle_marking_mode)
mp.add_key_binding("n", "mark_current_time", mark_current_time)
mp.add_key_binding("c", "confirm_marks", confirm_marks)
mp.add_key_binding("Esc", "exit_marking_mode", function()
    if marking_mode then toggle_marking_mode() end
end)

-- 可选：显示加载完成提示（默认注释）
-- mp.osd_message("多段切割脚本已加载！\n1. Ctrl+m 进入标记模式\n2. n 标记起止\n3. c 确认切割", 5)
