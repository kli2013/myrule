-- 配置方法
-- 
-- 在 mpv.conf 所在目录创建 script-opts/multi_cut.conf，内容示例：
-- ffmpeg_path=D:\ffmpeg\bin\ffmpeg.exe
-- log_dir=D:\cut_logs
-- use_bom=yes
-- prefer_copy=yes   （仅对 c 键有效，Ctrl+Shift+c 强制转码）


local utils = require 'mp.utils'
local options = require 'mp.options'

local o = {
    ffmpeg_path = 'ffmpeg.exe',
    log_dir = 'c:/FFmpeg',
    use_bom = true,
    prefer_copy = true,
}
options.read_options(o, 'multi_cut')

local marking_mode = false
local segments = {}
local current_segment_start = nil

-- ====================== 日志写入 ======================
local function write_cut_log(content, log_file_path)
    if not log_file_path then return end
    local f = io.open(log_file_path, 'a')
    if not f then
        mp.msg.warn("无法写入日志文件: " .. log_file_path)
        return
    end
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
            table.insert(chapters, { title = string.format("Seg%d 开始 %.2fs", i, seg.start), time = seg.start })
        end
        if seg.end_ then
            table.insert(chapters, { title = string.format("Seg%d 结束 %.2fs", i, seg.end_), time = seg.end_ })
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
        mp.osd_message("已进入标记模式！\n→ n : 标记起止\n→ c : 无损切割\n→ Ctrl+Shift+c : 精确转码切割\n→ Esc : 退出", 5)
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
        table.insert(segments, { start = pos })
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
    for i = 3, #args do
        local arg = tostring(args[i])
        if arg:find("[ \t]") or arg:find('"') then
            arg = '"' .. arg:gsub('"', '\\"') .. '"'
        end
        table.insert(parts, arg)
    end
    return table.concat(parts, " ")
end

-- ====================== 通用切割函数 ======================
local function run_cut(precise)
    if not marking_mode or #segments == 0 then
        mp.osd_message("没有标记片段", 3)
        return
    end

    -- 检查未闭合片段
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

    -- 获取视频路径
    local path = mp.get_property("path")
    if not path or path == "" then
        mp.osd_message("无法获取文件路径", 3)
        return
    end

    local dir, filename = utils.split_path(path)
    if not dir then dir = "" end
    local base = filename:match("(.+)%.[^%.]+$") or "output"
    local ext = filename:match("(%.[^%.]+)$") or ".mp4"
    local out_ext = (ext:lower() == ".ts" or ext:lower() == ".flv") and ".mp4" or ext

    local ffmpeg = o.ffmpeg_path or 'ffmpeg.exe'

    -- 日志文件
    local log_file
    if o.log_dir and o.log_dir ~= "" then
        log_file = utils.join_path(o.log_dir, "cutlog.txt")
        utils.subprocess({ args = { "cmd", "/c", "mkdir", o.log_dir, "/p" }, cancellable = false, playback_only = false })
    else
        log_file = utils.join_path(dir, "cutlog.txt")
    end

    write_cut_log("=====================================", log_file)
    write_cut_log("切割时间: " .. os.date("%Y-%m-%d %H:%M:%S"), log_file)
    write_cut_log("源文件: " .. path, log_file)
    write_cut_log("模式: " .. (precise and "精确转码" or "无损优先"), log_file)
    write_cut_log("-------------------------------------", log_file)

    -- 先测试 ffmpeg 是否可用
    local test_args = { "cmd", "/c", ffmpeg, "-version" }
    local test_res = utils.subprocess({ args = test_args, cancellable = false, playback_only = false })
    if test_res.status ~= 0 then
        local err_msg = "FFmpeg 不可用，请检查路径： " .. ffmpeg
        mp.osd_message(err_msg, 5)
        write_cut_log("错误: " .. err_msg, log_file)
        write_cut_log("-------------------------------------\n", log_file)
        return
    end

    -- 逐个处理片段
    for i, seg in ipairs(valid) do
        local duration = seg.end_ - seg.start
        local s_str = string.format("%.2f", seg.start):gsub("%.", "-")
        local e_str = string.format("%.2f", seg.end_):gsub("%.", "-")
        local out = utils.join_path(dir, string.format("%s_cut_seg%d_%s-%s%s", base, i, s_str, e_str, out_ext))

        mp.osd_message(string.format("正在处理片段 %d/%d ...", i, #valid), 2)

        local cmd_args = nil
        local success = false

        if precise then
            -- ========== 精确转码模式 ==========
            local transcode_args = {
                "cmd", "/c", ffmpeg,
                "-accurate_seek",
                "-i", path,
                "-ss", string.format("%.3f", seg.start),
                "-t", string.format("%.3f", duration),
                "-vf", "format=yuv420p",
                "-c:v", "libx265",
                "-preset", "medium",
                "-crf", "28",
                "-c:a", "aac",
                "-b:a", "128k",
                "-ar", "44100",
                "-map_metadata", "0",
                "-movflags", "+faststart",
                "-ignore_unknown",
                "-avoid_negative_ts", "make_zero",
                "-y", out
            }
            local res = utils.subprocess({ args = transcode_args, cancellable = false, playback_only = false })
            if res.status == 0 then
                success = true
                cmd_args = transcode_args
                mp.osd_message(string.format("片段 %d 精确转码完成", i), 2)
            else
                local err = res.stderr or "无错误输出"
                mp.msg.error("片段 %d 精确转码失败，stderr: %s", i, err:sub(1, 200))
                write_cut_log(string.format("片段 %d 失败: %s", i, err:gsub("\n", " ")), log_file)
            end
        else
            -- ========== 无损优先模式 ==========
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
                local res = utils.subprocess({ args = copy_args, cancellable = false, playback_only = false })
                if res.status == 0 then
                    success = true
                    cmd_args = copy_args
                    mp.osd_message(string.format("片段 %d 无损完成", i), 2)
                else
                    local err = res.stderr or "无错误输出"
                    mp.msg.warn("片段 %d 无损复制失败，尝试转码... stderr: %s", i, err:sub(1, 200))
                    write_cut_log(string.format("片段 %d 无损失败，尝试转码: %s", i, err:gsub("\n", " ")), log_file)
                end
            end

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
                    local vp9 = { "-c:v", "libvpx-vp9", "-crf", "23", "-b:v", "0", "-c:a", "libopus" }
                    for _, v in ipairs(vp9) do table.insert(transcode_args, v) end
                else
                    local x264 = { "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "128k" }
                    for _, v in ipairs(x264) do table.insert(transcode_args, v) end
                end
                local res = utils.subprocess({ args = transcode_args, cancellable = false, playback_only = false })
                if res.status == 0 then
                    success = true
                    cmd_args = transcode_args
                    mp.osd_message(string.format("片段 %d 转码完成", i), 2)
                else
                    local err = res.stderr or "无错误输出"
                    mp.msg.error("片段 %d 转码失败，stderr: %s", i, err:sub(1, 200))
                    write_cut_log(string.format("片段 %d 转码失败: %s", i, err:gsub("\n", " ")), log_file)
                end
            end
        end

        if success and cmd_args then
            local cmd_str = build_command_string(cmd_args)
            write_cut_log(cmd_str, log_file)
        end
    end

    write_cut_log("-------------------------------------\n", log_file)

    current_segment_start = nil
    marking_mode = false
    update_chapter_marks()

    mp.osd_message(string.format("✅ 全部完成！共 %d 个片段\n日志: %s", #valid, log_file or "无"), 6)
end

-- ====================== 快捷键绑定 ======================
mp.add_key_binding("Ctrl+m", "toggle_marking_mode", toggle_marking_mode)
mp.add_key_binding("n", "mark_current_time", mark_current_time)
mp.add_key_binding("c", "confirm_marks", function() run_cut(false) end)


mp.add_key_binding("Ctrl+Shift+c", "confirm_marks_precise", function() run_cut(true) end, "force")

mp.add_key_binding("Esc", "exit_marking_mode", function()
    if marking_mode then toggle_marking_mode() end
end)
