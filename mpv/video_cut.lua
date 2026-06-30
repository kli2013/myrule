-- 配置方法
-- 
-- 在 mpv.conf 所在目录创建 script-opts/multi_cut.conf，内容示例：
-- ffmpeg_path=D:\ffmpeg\bin\ffmpeg.exe
-- log_dir=D:\cut_logs
-- use_bom=yes
-- prefer_copy=yes


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
        mp.osd_message("已进入标记模式！\n→ n : 标记起止\n→ c : 无损切割 + 输出精确命令\n→ Esc : 退出", 5)
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

-- ====================== 构建命令字符串（智能引号） ======================
local function need_quote(arg)
    return arg:match("[ \t]") or arg:match('"') or arg == ""
end

local function quote_arg(arg)
    if need_quote(arg) then
        return '"' .. arg:gsub('"', '""') .. '"'
    else
        return arg
    end
end

local function build_ffmpeg_command(ffmpeg_path, args)
    local parts = { quote_arg(ffmpeg_path) }
    for _, a in ipairs(args) do
        table.insert(parts, quote_arg(a))
    end
    return table.concat(parts, " ")
end

-- ====================== 通用切割函数 ======================
local function run_cut()
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

    -- ========== 确定日志文件路径 ==========
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
    write_cut_log("模式: 无损切割 + 精确命令参考", log_file)
    write_cut_log("-------------------------------------", log_file)

    -- 测试 ffmpeg
    local test_res = utils.subprocess({ args = { ffmpeg, "-version" }, cancellable = false, playback_only = false })
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

        -- ========== 1. 生成精确转码命令（始终写入日志） ==========
        local scale_str = "scale=iw:ih,format=yuv420p"
        local precise_args = {
            "-accurate_seek",
            "-i", path,
            "-ss", string.format("%.3f", seg.start),
            "-t", string.format("%.3f", duration),
            "-vf", scale_str,
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
        local precise_cmd = build_ffmpeg_command(ffmpeg, precise_args)
        write_cut_log("[精确命令参考 " .. i .. "] " .. precise_cmd, log_file)

        -- ========== 2. 执行无损切割 ==========
        local cmd_args = nil
        local success = false

        if o.prefer_copy then
            local copy_args = {
                ffmpeg,
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
            local copy_cmd = build_ffmpeg_command(ffmpeg, { "-ss", string.format("%.3f", seg.start), "-i", path, "-t", string.format("%.3f", duration), "-c", "copy", "-map_metadata", "0", "-movflags", "+faststart", "-ignore_unknown", "-avoid_negative_ts", "make_zero", "-y", out })


            local res = utils.subprocess({ args = copy_args, cancellable = false, playback_only = false })
            if res.status == 0 then
                success = true
                cmd_args = copy_args
                mp.osd_message(string.format("片段 %d 无损完成", i), 2)
                local exec_cmd = build_ffmpeg_command(ffmpeg, { "-ss", string.format("%.3f", seg.start), "-i", path, "-t", string.format("%.3f", duration), "-c", "copy", "-map_metadata", "0", "-movflags", "+faststart", "-ignore_unknown", "-avoid_negative_ts", "make_zero", "-y", out })
                write_cut_log("[执行成功(无损)] " .. exec_cmd, log_file)
            else
                local err = res.stderr or "无错误输出"
                mp.msg.warn("片段 %d 无损复制失败，尝试转码... stderr: %s", i, err:sub(1, 200))

            end
        end

        -- 如果无损失败（或未启用），则转码
        if not success then
            local transcode_args = {
                ffmpeg,
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
            -- 记录转码尝试命令
            local args_for_cmd = {}
            for j = 2, #transcode_args do
                table.insert(args_for_cmd, transcode_args[j])
            end
            local trans_cmd = build_ffmpeg_command(ffmpeg, args_for_cmd)


            local res = utils.subprocess({ args = transcode_args, cancellable = false, playback_only = false })
            if res.status == 0 then
                success = true
                cmd_args = transcode_args
                mp.osd_message(string.format("片段 %d 转码完成", i), 2)
                local exec_cmd = build_ffmpeg_command(ffmpeg, args_for_cmd)
                write_cut_log("[执行成功(转码)] " .. exec_cmd, log_file)
            else
                local err = res.stderr or "无错误输出"
                mp.msg.error("片段 %d 转码失败，stderr: %s", i, err:sub(1, 200))

            end
        end
    end

    write_cut_log("-------------------------------------\n", log_file)

    -- 不清理状态，用户按 Esc 手动退出
    -- current_segment_start = nil
    -- marking_mode = false
    -- update_chapter_marks()

    mp.osd_message(string.format("✅ 全部完成！共 %d 个片段\n日志: %s", #valid, log_file or "无"), 6)
    mp.osd_message("标记状态已保留，可按 Esc 退出标记模式", 3)
end

-- ====================== 复制当前时间到剪贴板 ======================
local function copy_current_time_to_clipboard()
    local pos = mp.get_property_number("time-pos")
    if not pos then
        mp.osd_message("无法获取当前播放时间", 2)
        return
    end

    -- 格式化时间为 HH:MM:SS.mmm
    local hours = math.floor(pos / 3600)
    local minutes = math.floor((pos % 3600) / 60)
    local seconds = pos % 60
    local time_str = string.format("%02d:%02d:%06.3f", hours, minutes, seconds)

    -- 根据系统选择剪贴板命令
    local cmd
    if package.config:sub(1,1) == '\\' then
        -- Windows：使用 clip 命令（需要 cmd /c echo ... | clip）
        cmd = { "cmd", "/c", "echo " .. time_str .. " | clip" }
    else
        -- Linux / macOS：尝试 xclip / wl-copy / pbcopy
        local has_xclip = os.execute("which xclip >/dev/null 2>&1")
        local has_wlcopy = os.execute("which wl-copy >/dev/null 2>&1")
        local has_pbcopy = os.execute("which pbcopy >/dev/null 2>&1")
        if has_xclip then
            cmd = { "sh", "-c", "echo " .. time_str .. " | xclip -selection clipboard" }
        elseif has_wlcopy then
            cmd = { "sh", "-c", "echo " .. time_str .. " | wl-copy" }
        elseif has_pbcopy then
            cmd = { "sh", "-c", "echo " .. time_str .. " | pbcopy" }
        else
            mp.osd_message("未找到剪贴板工具（xclip/wl-copy/pbcopy）", 3)
            return
        end
    end

    local res = utils.subprocess({ args = cmd, cancellable = false, playback_only = false })
    if res.status == 0 then
        mp.osd_message(string.format("✅ 已复制时间: %s", time_str), 2)
    else
        mp.osd_message("❌ 复制失败", 2)
    end
end

-- ====================== 快捷键绑定 ======================
mp.add_key_binding("Ctrl+m", "toggle_marking_mode", toggle_marking_mode)
mp.add_key_binding("n", "mark_current_time", mark_current_time)
mp.add_key_binding("c", "confirm_marks", run_cut)  -- 执行无损切割 + 输出精确命令

mp.add_key_binding("Esc", "exit_marking_mode", function()
    if marking_mode then toggle_marking_mode() end
end)

-- 新增：复制当前时间到剪贴板
mp.add_key_binding("Ctrl+Shift+c", "copy_current_time", copy_current_time_to_clipboard)
