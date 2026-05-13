#NoEnv
SendMode Input
SetWorkingDir %A_ScriptDir%

; --- GUI 设计 ---
Gui, Font, s10, Microsoft YaHei
Gui, Add, Text, x10 y10, 目标文件夹:
Gui, Add, Edit, x85 y8 w300 vTargetFolder ReadOnly
Gui, Add, Button, x395 y6 w80 gBtnSelect, 选择文件夹

Gui, Add, Text, x10 y45, 别名:
Gui, Add, Edit, x85 y43 w300 vAliasName
Gui, Add, Button, x395 y41 w80 gBtnSet, 设置别名


; 新增：显示ini状态的文本标签，初始为“无”
Gui, Add, Text, x40 y85 w80 h20 vIniStatus, 无
; 新增：打开INI 和 刷新 按钮（放在退出按钮左侧）
Gui, Add, Button, x200 y80 w80 h30 gBtnOpenIni, 打开INI
Gui, Add, Button, x290 y80 w80 h30 gBtnRefresh, 刷新
Gui, Add, Button, x395 y80 w80 h30 gBtnExit, 退出
Gui, Show, w485 h130, 文件夹别名设置工具

; 初始化：刚启动时没有文件夹，禁用两个新按钮，状态显示“无”
GoSub UpdateIniButtons
Return

; ========== 更新“打开INI”和“刷新”按钮的状态，以及ini状态文本 ==========
UpdateIniButtons:
    Gui, Submit, NoHide  ; 获取当前 TargetFolder
    if (TargetFolder != "") {
        IniPath = %TargetFolder%\desktop.ini
        if FileExist(IniPath) {
            GuiControl, Enable, BtnOpenIni
            GuiControl, Enable, BtnRefresh
            GuiControl,, IniStatus, desktop.ini   ; 显示ini文件名
        } else {
            GuiControl, Disable, BtnOpenIni
            GuiControl, Disable, BtnRefresh
            GuiControl,, IniStatus, 无
        }
    } else {
        GuiControl, Disable, BtnOpenIni
        GuiControl, Disable, BtnRefresh
        GuiControl,, IniStatus, 无
    }
Return

; ========== 拖拽事件优化 ==========
; 原注释保留：处理拖拽事件
; 新增功能：如果是文件，则自动填入该文件所在的目录（而不是报错）
GuiDropFiles:
    ; A_GuiEvent 包含拖拽进来的文件路径，如果有多个用换行符分隔
    ; 取第一个路径（原注释保留）
    ; 使用更现代的 StrSplit 替代已过时的 StringSplit（但保留原逻辑）
    FirstPath := StrSplit(A_GuiEvent, "`n")[1]
    ; 去除首尾空格（原注释保留）
    FirstPath := Trim(FirstPath)

    ; 检查是否存在（增加异常处理）
    if !FileExist(FirstPath) {
        MsgBox, 48, 提示, 无效的路径！
        Return
    }

    ; 判断是文件夹还是文件（新增逻辑）
    if InStr(FileExist(FirstPath), "D") {
        ; 是文件夹 → 直接使用（原注释“检查是否是文件夹”保留）
        TargetFolder := FirstPath
        ToolTip, 已载入文件夹, 100, 100
    } else {
        ; 是文件 → 提取其所在目录（新增功能）
        SplitPath, FirstPath,, TargetFolder
        ToolTip, 已载入文件所在目录, 100, 100
    }

    ; 更新界面控件（原注释保留）
    GuiControl,, TargetFolder, %TargetFolder%
    ; 更新两个新按钮的状态以及ini状态文本
    GoSub UpdateIniButtons
    SetTimer, RemoveToolTip, 1000
return

; --- 按钮事件 ---

; 选择文件夹
BtnSelect:
    FileSelectFolder, SelectedFolder, , 3, 请选择要设置别名的文件夹
    if (SelectedFolder != "") {
        GuiControl,, TargetFolder, %SelectedFolder%
        GoSub UpdateIniButtons   ; 检测并更新按钮状态和文本
    }
Return

; 设置别名
BtnSet:
    Gui, Submit, NoHide

    ; 1. 基础检查
    if (TargetFolder = "") {
        MsgBox, 48, 错误, 请先选择一个文件夹！
        Return
    }
    if (AliasName = "") {
        MsgBox, 48, 错误, 别名不能为空！
        Return
    }
    if !InStr(FileExist(TargetFolder), "D") {
        MsgBox, 48, 错误, 选中的路径不是有效的文件夹！
        Return
    }

    ; 2. 构建 desktop.ini 内容
    IniContent =
    (
[.ShellClassInfo]
LocalizedResourceName=%AliasName%
IconResource=
    )

    IniPath = %TargetFolder%\desktop.ini

    ; 3. 写入文件
    FileDelete, %IniPath% ; 删除旧的
    FileAppend, %IniContent%, %IniPath%

    ; 4. 设置文件属性 (关键步骤)
    ; 将 desktop.ini 设置为 隐藏(H) + 系统(S)
    ;+S 不是必须的,加上 +S 主要是为了防止用户意外删除或修改该文件。
    FileSetAttrib, +H+S, %IniPath%

    ; 将目标文件夹设置为 只读(R)  
    ;    Windows 资源管理器需要通过文件夹的只读标记来判断是否启用“自定义文件夹”功能（如读取 desktop.ini 显示别名、图标等）。
    ;    如果不加 +R，即使 desktop.ini 存在且属性正确，系统也不会尝试读取其中的 LocalizedResourceName，别名也就不会生效。
    FileSetAttrib, +R, %TargetFolder%

    ; 5. 刷新 Shell (实现“瞬间变化”的效果)
    ; 通知系统该文件夹的内容已更新
    DllCall("Shell32.dll\SHChangeNotify", "Int", 0x08000000, "Int", 0, "UInt", 0, "UInt", 0)

    ToolTip, 设置成功！, 100, 100
    SetTimer, RemoveToolTip, -1000
    ; 设置完成后，新创建了 desktop.ini，更新按钮状态和文本
    GoSub UpdateIniButtons
Return

; ========== 新增：打开INI按钮 ==========
; 用记事本打开当前文件夹下的 desktop.ini
BtnOpenIni:
    Gui, Submit, NoHide
    if (TargetFolder = "") {
        MsgBox, 48, 错误, 请先选择一个文件夹！
        Return
    }
    IniPath = %TargetFolder%\desktop.ini
    if FileExist(IniPath) {
        Run, notepad.exe "%IniPath%"
    } else {
        MsgBox, 48, 提示, 该文件夹下没有 desktop.ini 文件！
    }
Return

; ========== 新增：刷新按钮 ==========
; 刷新当前文件夹的 Shell 视图，使别名更改立即生效（如果手动修改了 desktop.ini 可用此按钮）
BtnRefresh:
    Gui, Submit, NoHide
    if (TargetFolder = "") {
        MsgBox, 48, 错误, 请先选择一个文件夹！
        Return
    }
    if !InStr(FileExist(TargetFolder), "D") {
        MsgBox, 48, 错误, 选中的路径不是有效的文件夹！
        Return
    }
    ; 通知系统该文件夹的内容已更新（相当于让资源管理器重新读取 desktop.ini）
    DllCall("Shell32.dll\SHChangeNotify", "Int", 0x08000000, "Int", 0, "UInt", 0, "UInt", 0)
    ToolTip, 已刷新显示, 100, 100
    SetTimer, RemoveToolTip, -1000
    ; 刷新后重新检测ini状态（例如用户手动删除了ini）
    GoSub UpdateIniButtons
Return

BtnExit:
    GuiClose:
    ExitApp
Return

RemoveToolTip:
    ToolTip
Return
