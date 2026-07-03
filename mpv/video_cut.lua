-- 配置方法
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
        mp.osd_message("已进入标记模式！\n→ n : 标记起止\n→ c : 无损切割 + 输出精确命令\n→ Ctrl+Shift+c : 仅导出时间参数到剪贴板（日志保留完整命令）\n→ Esc : 退出", 5)
    else
        marking_mode = false
        segments = {}
        current_segment_start = nil
        update_chapter_marks()
        mp.osd_message("已退出标记模式", 3)
    end
end

-- ====================== 剪贴板复制（纯内存，无文件，无多余字符） ======================
local clipboard_cmd = nil

local function init_clipboard()
    local platform = mp.get_property("platform")
    if platform == "windows" then
        clipboard_cmd = function(text)
            local escaped = text:gsub('"', '\\"'):gsub('\n', '`n')
            utils.subprocess({
                args = {
                    "powershell", "-command",
                    "Set-Clipboard -Value \"" .. escaped .. "\""
                },
                cancellable = false
            })
        end
    elseif platform == "linux" then
        local has_xclip = (utils.subprocess({ args = { "which", "xclip" }, cancellable = false }).status == 0)
        local clip_cmd = has_xclip and "xclip -selection clipboard" or "xsel -b -i"
        clipboard_cmd = function(text)
            utils.subprocess({
                args = { "sh", "-c", "echo '" .. text .. "' | " .. clip_cmd },
                cancellable = false
            })
        end
    elseif platform == "darwin" then
        clipboard_cmd = function(text)
            utils.subprocess({
                args = { "sh", "-c", "echo '" .. text .. "' | pbcopy" },
                cancellable = false
            })
        end
    else
        clipboard_cmd = function() end
    end
end

init_clipboard()

local function copy_to_clipboard(text)
    if clipboard_cmd then
        clipboard_cmd(text)
    end
end

-- ====================== 标记时间点 ======================
local function mark_current_time()
    if not marking_mode then
        local pos = mp.get_property_number("time-pos")
        if pos then
            local hours = math.floor(pos / 3600)
            local minutes = math.floor((pos % 3600) / 60)
            local seconds = pos % 60
            local time_str = string.format("%02d:%02d:%06.3f", hours, minutes, seconds)
            copy_to_clipboard(time_str)
            mp.osd_message("未进入标记模式！请按 Ctrl+m\n已复制当前时间: " .. time_str, 3)
        else
            mp.osd_message("无法获取当前播放时间", 2)
        end
        return
    end

    local pos = mp.get_property_number("time-pos")
    if not pos then return end

    if not current_segment_start then
        current_segment_start = pos
        table.insert(segments, { start = pos })
        mp.osd_message(string.format("✓ 开始点: %.3f", pos), 2)
    else
        local n = #segments
        segments[n].end_ = pos
        current_segment_start = nil
        mp.osd_message(string.format("✓ 结束点: %.3f\n当前共 %d 个片段", pos, n), 3)
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

-- ====================== 【新增】公共函数 ======================

-- 获取有效片段（过滤未闭合、无效的），并输出警告
local function get_valid_segments()
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
    return valid
end

-- 获取文件信息：路径、目录、文件名、基础名、扩展名、输出扩展名
local function get_file_info()
    local path = mp.get_property("path")
    if not path or path == "" then
        return nil, "无法获取文件路径"
    end
    local dir, filename = utils.split_path(path)
    if not dir then dir = "" end
    local base = filename:match("(.+)%.[^%.]+$") or "output"
    local ext = filename:match("(%.[^%.]+)$") or ".mp4"
    local out_ext = (ext:lower() == ".ts" or ext:lower() == ".flv") and ".mp4" or ext
    return path, dir, filename, base, ext, out_ext
end

-- 获取日志文件路径（若指定了 log_dir 则使用，否则与源文件同目录）
local function get_log_file_path(dir)
    local log_file
    if o.log_dir and o.log_dir ~= "" then
        log_file = utils.join_path(o.log_dir, "cutlog.txt")
        utils.subprocess({ args = { "cmd", "/c", "mkdir", o.log_dir, "/p" }, cancellable = false, playback_only = false })
    else
        log_file = utils.join_path(dir, "cutlog.txt")
    end
    return log_file
end

-- 写入日志头部（时间、源文件、模式描述）
local function write_log_header(log_file, path, mode_desc)
    write_cut_log("=====================================", log_file)
    write_cut_log("切割时间: " .. os.date("%Y-%m-%d %H:%M:%S"), log_file)
    write_cut_log("源文件: " .. path, log_file)
    write_cut_log("模式: " .. mode_desc, log_file)
    write_cut_log("-------------------------------------", log_file)
end

-- 构建精确转码命令的参数表（用于日志，也可用于执行）
local function build_precise_args(ffmpeg, path, seg, out)
    local duration = seg.end_ - seg.start
    return {
        ffmpeg,
        "-accurate_seek",
        "-i", path,
        "-ss", string.format("%.3f", seg.start),
        "-t", string.format("%.3f", duration),
        "-vf", "scale=iw:ih,format=yuv420p",
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
end

-- 测试 ffmpeg 是否可用
local function check_ffmpeg(ffmpeg)
    local test_res = utils.subprocess({ args = { ffmpeg, "-version" }, cancellable = false, playback_only = false })
    return test_res.status == 0
end

-- ====================== 通用切割函数 ======================
local function run_cut()
    if not marking_mode or #segments == 0 then
        mp.osd_message("没有标记片段", 3)
        return
    end

    local valid = get_valid_segments()
    if #valid == 0 then
        mp.osd_message("没有有效片段", 3)
        return
    end

    local path, dir, filename, base, ext, out_ext = get_file_info()
    if not path then
        mp.osd_message(dir, 3)  -- dir 存放错误信息
        return
    end

    local log_file = get_log_file_path(dir)
    write_log_header(log_file, path, "无损切割 + 精确命令参考")

    local ffmpeg = o.ffmpeg_path or 'ffmpeg.exe'
    if not check_ffmpeg(ffmpeg) then
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

        -- 生成并记录精确转码命令（始终写入日志）
        local precise_args = build_precise_args(ffmpeg, path, seg, out)
        local precise_cmd = build_ffmpeg_command(ffmpeg, precise_args)
        write_cut_log("[精确命令参考 " .. i .. "] " .. precise_cmd, log_file)

        -- 执行无损切割
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
            local res = utils.subprocess({ args = copy_args, cancellable = false, playback_only = false })
            if res.status == 0 then
                success = true
                mp.osd_message(string.format("片段 %d 无损完成", i), 2)
                local exec_cmd = build_ffmpeg_command(ffmpeg, copy_args)
                write_cut_log("[执行成功(无损)] " .. exec_cmd, log_file)
            else
                local err = res.stderr or "无错误输出"
                mp.msg.warn("片段 %d 无损复制失败，尝试转码... stderr: %s", i, err:sub(1, 200))
            end
        end

        -- 若无损失败则转码
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
                local x264 = { "-c:v", "libx265", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "128k" }
                for _, v in ipairs(x264) do table.insert(transcode_args, v) end
            end
            local res = utils.subprocess({ args = transcode_args, cancellable = false, playback_only = false })
            if res.status == 0 then
                success = true
                mp.osd_message(string.format("片段 %d 转码完成", i), 2)
                local exec_cmd = build_ffmpeg_command(ffmpeg, transcode_args)
                write_cut_log("[执行成功(转码)] " .. exec_cmd, log_file)
            else
                local err = res.stderr or "无错误输出"
                mp.msg.error("片段 %d 转码失败，stderr: %s", i, err:sub(1, 200))
            end
        end
    end

    write_cut_log("-------------------------------------\n", log_file)
    mp.osd_message(string.format("✅ 全部完成！共 %d 个片段\n日志: %s", #valid, log_file or "无"), 6)
    mp.osd_message("标记状态已保留，可按 Esc 退出标记模式", 3)
end

-- ====================== 仅导出时间参数到剪贴板（日志保留完整命令） ======================
local function export_commands_only()
    if not marking_mode or #segments == 0 then
        mp.osd_message("没有标记片段", 3)
        return
    end

    local valid = get_valid_segments()
    if #valid == 0 then
        mp.osd_message("没有有效片段", 3)
        return
    end

    local path, dir, filename, base, ext, out_ext = get_file_info()
    if not path then
        mp.osd_message(dir, 3)
        return
    end

    local log_file = get_log_file_path(dir)
    write_log_header(log_file, path, "仅导出精确命令（未执行切割）")

    local ffmpeg = o.ffmpeg_path or 'ffmpeg.exe'
    local time_lines = {}

    for i, seg in ipairs(valid) do
        local duration = seg.end_ - seg.start
        local s_str = string.format("%.2f", seg.start):gsub("%.", "-")
        local e_str = string.format("%.2f", seg.end_):gsub("%.", "-")
        local out = utils.join_path(dir, string.format("%s_cut_seg%d_%s-%s%s", base, i, s_str, e_str, out_ext))

        -- 构建并记录精确命令
        local precise_args = build_precise_args(ffmpeg, path, seg, out)
        local precise_cmd = build_ffmpeg_command(ffmpeg, precise_args)
        write_cut_log("[精确命令 " .. i .. "] " .. precise_cmd, log_file)

        -- 提取时间参数
        table.insert(time_lines, string.format("-ss %.3f -t %.3f", seg.start, duration))
    end

    write_cut_log("-------------------------------------\n", log_file)

    if #time_lines > 0 then
        local all_times = table.concat(time_lines, "\n")
        copy_to_clipboard(all_times)
        mp.osd_message(string.format("✅ 时间参数已复制到剪贴板（%d 条）\n日志完整命令已保存至: %s", #time_lines, log_file), 5)
    else
        mp.osd_message("没有有效的时间参数可导出", 3)
    end
end

-- ====================== 快捷键绑定 ======================
mp.add_key_binding("Ctrl+m", "toggle_marking_mode", toggle_marking_mode)
mp.add_key_binding("n", "mark_current_time", mark_current_time)
mp.add_key_binding("c", "confirm_marks", run_cut)
mp.add_key_binding("Ctrl+Shift+c", "export_commands_only", export_commands_only)

mp.add_key_binding("Esc", "exit_marking_mode", function()
    if marking_mode then toggle_marking_mode() end
end)
