#NoEnv
#SingleInstance Force
SetBatchLines, -1

; ========== 全局公用函数 ==========
ParseOffsetInput(text) {
    text := RegExReplace(text, "^\s+|\s+$")
    if text is integer
        return text
    if RegExMatch(text, "^(-?)(\d{1,2}):(\d{2})\.(\d{1,3})$", m) {
        sign := (m1 = "-") ? -1 : 1
        minutes := m2
        seconds := m3
        ms_str := m4
        if (StrLen(ms_str) = 1)
            ms_str .= "00"
        else if (StrLen(ms_str) = 2)
            ms_str .= "0"
        total_ms := sign * (minutes * 60000 + seconds * 1000 + ms_str)
        return total_ms
    }
    return ""
}

DetectFormat(text) {
    tmp := RegExReplace(text, "\r\n?|\n", "`n")
    lines := StrSplit(tmp, "`n")
    cntLRC := 0, cntSRT := 0, cntSSA := 0
    for i, line in lines {
        if (line = "")
            continue
        if RegExMatch(line, "^\[\d{1,2}:\d{2}\.\d{1,3}\]")
            cntLRC++
        if RegExMatch(line, "\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")
            cntSRT++
        if RegExMatch(line, "^(Dialogue|Comment):")
            cntSSA++
    }
    if (cntLRC > cntSRT && cntLRC > cntSSA)
        return "LRC"
    if (cntSRT > cntLRC && cntSRT > cntSSA)
        return "SRT"
    if (cntSSA > cntLRC && cntSSA > cntSRT)
        return "SSA"
    return "Unknown"
}

FormatTimeLRC(total_ms) {
    if (total_ms < 0)
        total_ms := 0
    minutes := total_ms // 60000
    seconds := Mod(total_ms, 60000) // 1000
    milliseconds := Mod(total_ms, 1000) // 10
    return Format("[{:02d}:{:02d}.{:02d}]", minutes, seconds, milliseconds)
}

FormatTimeSRT(total_ms) {
    if (total_ms < 0)
        total_ms := 0
    hours := total_ms // 3600000
    remainder := Mod(total_ms, 3600000)
    minutes := remainder // 60000
    remainder := Mod(remainder, 60000)
    seconds := remainder // 1000
    milliseconds := Mod(remainder, 1000)
    return Format("{:02d}:{:02d}:{:02d},{:03d}", hours, minutes, seconds, milliseconds)
}

ParseSRTTime(srt_time) {
    srt_time := StrReplace(srt_time, ",", ".")
    parts := StrSplit(srt_time, ":")
    if (parts.Length() != 3)
        return 0
    hours := parts[1]
    minutes := parts[2]
    sec_parts := StrSplit(parts[3], ".")
    seconds := sec_parts[1]
    ms := (sec_parts[2] = "") ? 0 : sec_parts[2]
    if (StrLen(ms) = 1)
        ms .= "00"
    else if (StrLen(ms) = 2)
        ms .= "0"
    total_ms := hours * 3600000 + minutes * 60000 + seconds * 1000 + ms
    return total_ms
}

FormatTimeSSA(total_ms) {
    if (total_ms < 0)
        total_ms := 0
    hours := total_ms // 3600000
    remainder := Mod(total_ms, 3600000)
    minutes := remainder // 60000
    remainder := Mod(remainder, 60000)
    seconds := remainder // 1000
    centiseconds := Mod(remainder, 1000) // 10
    return Format("{:d}:{:02d}:{:02d}.{:02d}", hours, minutes, seconds, centiseconds)
}

ParseSSATime(ssa_time) {
    if RegExMatch(ssa_time, "^(\d+):(\d{2}):(\d{2})\.(\d{2})", m) {
        hours := m1, minutes := m2, seconds := m3, cs := m4
        total_ms := hours * 3600000 + minutes * 60000 + seconds * 1000 + cs * 10
        return total_ms
    }
    if RegExMatch(ssa_time, "^(\d+):(\d{2}):(\d{2})\.(\d{3})", m) {
        hours := m1, minutes := m2, seconds := m3, ms := m4
        total_ms := hours * 3600000 + minutes * 60000 + seconds * 1000 + ms
        return total_ms
    }
    return 0
}

; ========== LRC 处理 ==========
ProcessLRC(inputText, offset_ms) {
    TimePattern := "\[\d{1,2}:\d{2}\.\d{1,3}\]"
    NewLines := ""
    Loop, Parse, inputText, `n, `r
    {
        Line := A_LoopField
        if (Line = "") {
            NewLines .= "`n"
            continue
        }
        newLine := Line
        SearchPos := 1
        while (RegExMatch(newLine, TimePattern, Match, SearchPos))
        {
            StartPos := SearchPos
            EndPos := StartPos + StrLen(Match) - 1
            TimeStr := SubStr(Match, 2, StrLen(Match)-2)
            Parts := StrSplit(TimeStr, ":")
            minutes := Parts[1]
            rest := Parts[2]
            RestParts := StrSplit(rest, ".")
            seconds := RestParts[1]
            ms_part := RestParts[2]
            if (StrLen(ms_part) = 1)
                ms_part .= "00"
            else if (StrLen(ms_part) = 2)
                ms_part .= "0"
            original_ms := minutes * 60000 + seconds * 1000 + ms_part
            new_ms := original_ms + offset_ms
            if (new_ms < 0)
                new_ms := 0
            new_time_str := FormatTimeLRC(new_ms)
            prefix := SubStr(newLine, 1, StartPos-1)
            suffix := SubStr(newLine, EndPos+1)
            newLine := prefix . new_time_str . suffix
            SearchPos := StartPos + StrLen(new_time_str)
        }
        NewLines .= newLine "`n"
    }
    StringTrimRight, NewLines, NewLines, 1
    return NewLines
}

; ========== SRT 处理 ==========
ProcessSRT(inputText, offset_ms) {
    OutputLines := ""
    Loop, Parse, inputText, `n, `r
    {
        line := A_LoopField
        if RegExMatch(line, "(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})", m) {
            start_old := m1, end_old := m2
            start_ms := ParseSRTTime(start_old)
            end_ms := ParseSRTTime(end_old)
            start_new_ms := start_ms + offset_ms
            end_new_ms := end_ms + offset_ms
            if (start_new_ms < 0)
                start_new_ms := 0
            if (end_new_ms < 0)
                end_new_ms := 0
            start_new := FormatTimeSRT(start_new_ms)
            end_new := FormatTimeSRT(end_new_ms)
            new_line := start_new . " --> " . end_new
            OutputLines .= new_line . "`n"
        } else {
            OutputLines .= line . "`n"
        }
    }
    StringTrimRight, OutputLines, OutputLines, 1
    return OutputLines
}

; ========== SSA/ASS 处理（按字段分割，稳健版）==========
ProcessSSA(inputText, offset_ms) {
    OutputLines := ""
    Loop, Parse, inputText, `n, `r
    {
        line := A_LoopField
        if (line = "") {
            OutputLines .= "`n"
            continue
        }

        if RegExMatch(line, "^(Dialogue|Comment):") {
            fields := StrSplit(line, ",")
            if (fields.Length() >= 3) {
                startTime := Trim(fields[2])
                endTime   := Trim(fields[3])
                
                newStart := FormatTimeSSA(ParseSSATime(startTime) + offset_ms)
                newEnd   := FormatTimeSSA(ParseSSATime(endTime) + offset_ms)
                
                if (ParseSSATime(startTime) + offset_ms < 0)
                    newStart := "0:00:00.00"
                if (ParseSSATime(endTime) + offset_ms < 0)
                    newEnd := "0:00:00.00"
                
                fields[2] := newStart
                fields[3] := newEnd
                
                newLine := ""
                Loop % fields.Length()
                {
                    newLine .= fields[A_Index]
                    if (A_Index < fields.Length())
                        newLine .= ","
                }
                OutputLines .= newLine . "`n"
                continue
            }
        }
        OutputLines .= line . "`n"
    }
    StringTrimRight, OutputLines, OutputLines, 1
    return OutputLines
}

ProcessAuto(inputText, offset_ms) {
    fmt := DetectFormat(inputText)
    if (fmt = "LRC")
        return ProcessLRC(inputText, offset_ms)
    else if (fmt = "SRT")
        return ProcessSRT(inputText, offset_ms)
    else if (fmt = "SSA")
        return ProcessSSA(inputText, offset_ms)
    else
        return "错误：无法识别的字幕格式，请确保内容包含 LRC、SRT 或 SSA/ASS 的时间标签。"
}

; ========== GUI 界面（固定坐标，均已右移20像素避免遮挡）==========
Gui, New, +Resize, 字幕时间整体偏移工具 (LRC / SRT / SSA / 智能)
Gui, Margin, 10, 10
Gui, Add, Tab3, vTabSel, LRC歌词偏移|SRT字幕偏移|SSA/ASS字幕偏移|智能模式

; -------------------- Tab1 : LRC --------------------
Gui, Tab, 1
Gui, Add, Text, x30 y55 w1160 h20, 在此粘贴原始 LRC 歌词内容：
Gui, Add, Edit, x30 y75 w1160 h280 vInputLRC +Multi +WantTab +HScroll +VScroll
Gui, Add, Text, x30 y369 w350 h20, 请输入偏移量（纯数字 1500 -1500 或标准格式 -00:01.12）：
Gui, Add, Edit, x380 y365 w300 h20 vOffsetLRC
Gui, Add, Button, x700 y363 w120 h24 gShiftLRC, 开始整体偏移
Gui, Add, Text, x30 y400 w1160 h20, 处理后的 LRC 歌词结果：
Gui, Add, Edit, x30 y420 w1160 h320 vOutputLRC +Multi +WantTab +HScroll +VScroll +ReadOnly
Gui, Add, Button, x540 y750 w120 h30 gCopyLRC, 复制结果到剪贴板

; -------------------- Tab2 : SRT --------------------
Gui, Tab, 2
Gui, Add, Text, x30 y55 w1160 h20, 在此粘贴原始 SRT 字幕内容：
Gui, Add, Edit, x30 y75 w1160 h280 vInputSRT +Multi +WantTab +HScroll +VScroll
Gui, Add, Text, x30 y369 w350 h20, 请输入偏移量（纯数字 1500 -1500 或标准格式 -00:01.12）：
Gui, Add, Edit, x380 y365 w300 h20 vOffsetSRT
Gui, Add, Button, x700 y363 w120 h24 gShiftSRT, 开始整体偏移
Gui, Add, Text, x30 y400 w1160 h20, 处理后的 SRT 字幕结果：
Gui, Add, Edit, x30 y420 w1160 h320 vOutputSRT +Multi +WantTab +HScroll +VScroll +ReadOnly
Gui, Add, Button, x540 y750 w120 h30 gCopySRT, 复制结果到剪贴板

; -------------------- Tab3 : SSA --------------------
Gui, Tab, 3
Gui, Add, Text, x30 y55 w1160 h20, 在此粘贴原始 SSA/ASS 字幕内容（支持 Dialogue 行时间偏移）：
Gui, Add, Edit, x30 y75 w1160 h280 vInputSSA +Multi +WantTab +HScroll +VScroll
Gui, Add, Text, x30 y369 w350 h20, 请输入偏移量（纯数字 1500 -1500 或标准格式 -00:01.12）：
Gui, Add, Edit, x380 y365 w300 h20 vOffsetSSA
Gui, Add, Button, x700 y363 w120 h24 gShiftSSA, 开始整体偏移
Gui, Add, Text, x30 y400 w1160 h20, 处理后的 SSA/ASS 字幕结果：
Gui, Add, Edit, x30 y420 w1160 h320 vOutputSSA +Multi +WantTab +HScroll +VScroll +ReadOnly
Gui, Add, Button, x540 y750 w120 h30 gCopySSA, 复制结果到剪贴板

; -------------------- Tab4 : 智能模式 --------------------
Gui, Tab, 4
Gui, Add, Text, x30 y55 w1160 h20, 智能识别模式：粘贴任意格式字幕（LRC / SRT / SSA/ASS），自动处理偏移：
Gui, Add, Edit, x30 y75 w1160 h280 vInputAuto +Multi +WantTab +HScroll +VScroll
Gui, Add, Text, x30 y369 w350 h20, 请输入偏移量（纯数字 1500 -1500 或标准格式 -00:01.12）：
Gui, Add, Edit, x380 y365 w300 h20 vOffsetAuto
Gui, Add, Button, x700 y363 w120 h24 gShiftAuto, 开始整体偏移
Gui, Add, Text, x30 y400 w1160 h20, 处理后的结果（自动匹配格式）：
Gui, Add, Edit, x30 y420 w1160 h320 vOutputAuto +Multi +WantTab +HScroll +VScroll +ReadOnly
Gui, Add, Button, x540 y750 w120 h30 gCopyAuto, 复制结果到剪贴板


GuiControl, Font, InputLRC
GuiControl, Font, OutputLRC
GuiControl, Font, InputSRT
GuiControl, Font, OutputSRT
GuiControl, Font, InputSSA
GuiControl, Font, OutputSSA
GuiControl, Font, InputAuto
GuiControl, Font, OutputAuto
Gui, Font

Gui, Show, w1200 h815
WinGetPos,,, WinW, WinH, A
ScreenW := A_ScreenWidth, ScreenH := A_ScreenHeight
WinMove, A,, (ScreenW-WinW)//2, (ScreenH-WinH)//2
return



; ========== 各标签页偏移处理（修复切换后不执行偏移）==========
ShiftLRC:
    Gui, Submit, NoHide
    if (OffsetLRC = "") {
        MsgBox, 48, 提示, 请输入偏移量！
        return
    }
    if (InputLRC = "") {
        MsgBox, 48, 提示, 请先输入原始 LRC 歌词内容！
        return
    }
    realFormat := DetectFormat(InputLRC)
    if (realFormat != "LRC") {
        if (realFormat = "SRT")
            msg := "检测到输入内容为 SRT 字幕格式，但当前在 LRC 标签页。`n是否切换到 SRT 标签页？"
        else if (realFormat = "SSA")
            msg := "检测到输入内容为 SSA/ASS 字幕格式，但当前在 LRC 标签页。`n是否切换到 SSA 标签页？"
        else
            msg := "无法识别输入内容的格式，处理可能无效。`n是否继续？"
        MsgBox, 4, 格式不匹配, %msg%
        IfMsgBox, Yes
        {
            if (realFormat = "SRT")
                GuiControl, Choose, TabSel, 2
            else if (realFormat = "SSA")
                GuiControl, Choose, TabSel, 3
            ; 切换后立即返回，不执行偏移
            return
        }
        else
            return
    }
    offset_ms := ParseOffsetInput(OffsetLRC)
    if (offset_ms = "") {
        MsgBox, 16, 错误, 偏移量格式不正确！`n请输入纯数字（如 1500）或标准时间格式（如 00:01.12）。
        return
    }
    newContent := ProcessLRC(InputLRC, offset_ms)
    GuiControl,, OutputLRC, %newContent%
    MsgBox, 64, 完成, 已成功按 %offset_ms% 毫秒进行 LRC 整体偏移！
return

ShiftSRT:
    Gui, Submit, NoHide
    if (OffsetSRT = "") {
        MsgBox, 48, 提示, 请输入偏移量！
        return
    }
    if (InputSRT = "") {
        MsgBox, 48, 提示, 请先输入原始 SRT 字幕内容！
        return
    }
    realFormat := DetectFormat(InputSRT)
    if (realFormat != "SRT") {
        if (realFormat = "LRC")
            msg := "检测到输入内容为 LRC 歌词格式，但当前在 SRT 标签页。`n是否切换到 LRC 标签页？"
        else if (realFormat = "SSA")
            msg := "检测到输入内容为 SSA/ASS 字幕格式，但当前在 SRT 标签页。`n是否切换到 SSA 标签页？"
        else
            msg := "无法识别输入内容的格式，处理可能无效。`n是否继续？"
        MsgBox, 4, 格式不匹配, %msg%
        IfMsgBox, Yes
        {
            if (realFormat = "LRC")
                GuiControl, Choose, TabSel, 1
            else if (realFormat = "SSA")
                GuiControl, Choose, TabSel, 3
            ; 切换后立即返回，不执行偏移
            return
        }
        else
            return
    }
    offset_ms := ParseOffsetInput(OffsetSRT)
    if (offset_ms = "") {
        MsgBox, 16, 错误, 偏移量格式不正确！`n请输入纯数字（如 1500）或标准时间格式（如 00:01.12）。
        return
    }
    newContent := ProcessSRT(InputSRT, offset_ms)
    GuiControl,, OutputSRT, %newContent%
    MsgBox, 64, 完成, 已成功按 %offset_ms% 毫秒进行 SRT 整体偏移！
return

ShiftSSA:
    Gui, Submit, NoHide
    if (OffsetSSA = "") {
        MsgBox, 48, 提示, 请输入偏移量！
        return
    }
    if (InputSSA = "") {
        MsgBox, 48, 提示, 请先输入原始 SSA/ASS 字幕内容！
        return
    }
    realFormat := DetectFormat(InputSSA)
    if (realFormat != "SSA") {
        if (realFormat = "LRC")
            msg := "检测到输入内容为 LRC 歌词格式，但当前在 SSA 标签页。`n是否切换到 LRC 标签页？"
        else if (realFormat = "SRT")
            msg := "检测到输入内容为 SRT 字幕格式，但当前在 SSA 标签页。`n是否切换到 SRT 标签页？"
        else
            msg := "无法识别输入内容的格式，处理可能无效。`n是否继续？"
        MsgBox, 4, 格式不匹配, %msg%
        IfMsgBox, Yes
        {
            if (realFormat = "LRC")
                GuiControl, Choose, TabSel, 1
            else if (realFormat = "SRT")
                GuiControl, Choose, TabSel, 2
            ; 切换后立即返回，不执行偏移
            return
        }
        else
            return
    }
    offset_ms := ParseOffsetInput(OffsetSSA)
    if (offset_ms = "") {
        MsgBox, 16, 错误, 偏移量格式不正确！`n请输入纯数字（如 1500）或标准时间格式（如 00:01.12）。
        return
    }
    newContent := ProcessSSA(InputSSA, offset_ms)
    GuiControl,, OutputSSA, %newContent%
    MsgBox, 64, 完成, 已成功按 %offset_ms% 毫秒进行 SSA/ASS 整体偏移！
return

ShiftAuto:
    Gui, Submit, NoHide
    if (OffsetAuto = "") {
        MsgBox, 48, 提示, 请输入偏移量！
        return
    }
    if (InputAuto = "") {
        MsgBox, 48, 提示, 请先输入字幕内容！
        return
    }
    offset_ms := ParseOffsetInput(OffsetAuto)
    if (offset_ms = "") {
        MsgBox, 16, 错误, 偏移量格式不正确！`n请输入纯数字（如 1500）或标准时间格式（如 00:01.12）。
        return
    }
    newContent := ProcessAuto(InputAuto, offset_ms)
    GuiControl,, OutputAuto, %newContent%
    MsgBox, 64, 完成, 已自动识别格式并成功按 %offset_ms% 毫秒偏移！
return

; ========== 复制功能 ==========
CopyLRC:
    Gui, Submit, NoHide
    if (OutputLRC != "") {
        Clipboard := OutputLRC
        MsgBox, 64, 成功, LRC 结果已复制到剪贴板！
    } else {
        MsgBox, 48, 提示, 没有可复制的内容！
    }
return

CopySRT:
    Gui, Submit, NoHide
    if (OutputSRT != "") {
        Clipboard := OutputSRT
        MsgBox, 64, 成功, SRT 结果已复制到剪贴板！
    } else {
        MsgBox, 48, 提示, 没有可复制的内容！
    }
return

CopySSA:
    Gui, Submit, NoHide
    if (OutputSSA != "") {
        Clipboard := OutputSSA
        MsgBox, 64, 成功, SSA/ASS 结果已复制到剪贴板！
    } else {
        MsgBox, 48, 提示, 没有可复制的内容！
    }
return

CopyAuto:
    Gui, Submit, NoHide
    if (OutputAuto != "") {
        Clipboard := OutputAuto
        MsgBox, 64, 成功, 智能模式结果已复制到剪贴板！
    } else {
        MsgBox, 48, 提示, 没有可复制的内容！
    }
return

GuiClose:
ExitApp
