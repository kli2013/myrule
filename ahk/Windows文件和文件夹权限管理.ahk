;=============================================================================
;  NTFS 权限 & 文件属性管理工具（最终版：用户/组列表正确填充）
;=============================================================================

debugFile := A_Temp . "\NTFS_Tool_Debug.txt"
; FileDelete, %debugFile%
; FileAppend, ====== 脚本启动 %A_Now% ======`n, %debugFile%
earlyLog := ""

DebugOut(msg, toFile:=true) {
    global earlyLog, debugFile
;     if (toFile)
;         FileAppend, %msg%`n, %debugFile%
    try {
        GuiControlGet, curLog, , LogBox
        if (curLog != "")
            newLog := msg . "`n" . curLog
        else
            newLog := msg
        GuiControl, , LogBox, %newLog%
    } catch {
        earlyLog .= msg . "`n"
    }
}



;------------------------------- 获取用户和组 -------------------------------
GetUsersByWMI() {
    users := []
    try {
        wmi := ComObjGet("winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2")
        accounts := wmi.ExecQuery("SELECT Name FROM Win32_UserAccount WHERE LocalAccount = True")
        for account in accounts {
            users.Push(account.Name)
            ; DebugOut("  - 用户: " . account.Name)
        }
        ; DebugOut("调试: WMI 获取到 " . users.Length() . " 个本地用户")
    } catch e {
        ; DebugOut("调试: WMI 获取用户失败 - " . e.Message)
        return []
    }
    return users
}

GetGroupsByWMI() {
    groups := []
    try {
        wmi := ComObjGet("winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2")
        grps := wmi.ExecQuery("SELECT Name FROM Win32_Group")
        for grp in grps {
            groups.Push(grp.Name)
            ; DebugOut("  - 组: " . grp.Name)
        }
        ; DebugOut("调试: WMI 获取到 " . groups.Length() . " 个本地组")
    } catch e {
        ; DebugOut("调试: WMI 获取组失败 - " . e.Message)
        return []
    }
    return groups
}

GetLocalUsersAndGroups() {
    ; DebugOut("调试: 开始获取用户/组列表...")
    users := GetUsersByWMI()
    groups := GetGroupsByWMI()
    fullList := []
    if (users.Length() > 0) {
        fullList.Push("--- 本地用户 ---")
        for index, name in users
            fullList.Push(name)
    }
    if (groups.Length() > 0) {
        fullList.Push("--- 本地组 ---")
        for index, name in groups
            fullList.Push(name)
    }
    ; 添加特殊主体（内置安全主体，不会被WMI枚举）
    fullList.Push("--- 特殊主体 ---")
    specials := ["Everyone", "Authenticated Users", "SYSTEM", "CREATOR OWNER", "Users", "TrustedInstaller"]
    for index, name in specials
        fullList.Push(name)
    
    if (fullList.Length() = 0) {
        ; DebugOut("调试: 未能获取任何本地用户或组，使用备用列表")
        fullList.Push("--- 备用用户/组 ---")
        fullList.Push(A_UserName)
        fullList.Push("Everyone")
        fullList.Push("Administrators")
        fullList.Push("Users")
    } else {
        ; DebugOut("调试: 已添加特殊主体，最终列表项总数 = " . fullList.Length())
    }
    return fullList
}

; 构建下拉列表
userGroupsArray := GetLocalUsersAndGroups()
listStr := ""
for i, item in userGroupsArray
    listStr .= (i=1 ? "" : "|") . item
; DebugOut("调试: 列表字符串前200字符: " . SubStr(listStr, 1, 200))

;-------------------------------- 界面 ---------------------------------
Gui, +Resize +MinSize400x300
Gui, Font, s10, Segoe UI

Gui, Add, Text, x12 y12 w80, 目标路径：
Gui, Add, Edit, x92 y10 w260 h25 vTargetPath, 浏览文件或者拖拽到此文本框
Gui, Add, Button, x362 y8 w80 gBrowseFile, 浏览文件
Gui, Add, Button, x452 y8 w90 gBrowseFolder, 浏览文件夹

Gui, Add, Text, x12 y50 w80, 用户/组：
Gui, Add, ComboBox, x92 y48 w200 vUserName, 
Gui, Add, Button, x402 y47 w80 h25 gShowUserIntro, 用户介绍


Gui, Add, Text, x12 y90 w80, 权限类型：
Gui, Add, DropDownList, x92 y88 w120 vPermType, 允许|拒绝
Gui, Add, Button, x262 y87 w100 h25 gShowPermHelp, 掩码介绍
Gui, Add, Button, x372 y87 w100 h25 gShowAttrIntro, 属性介绍

Gui, Add, Text, x12 y130 w80, 权限掩码：
Gui, Add, DropDownList, x92 y128 w180 vPermMask gOnPermMaskChange, F (完全控制)|M (修改)|RX (读取和执行)|R (只读)|W (写入)|自定义
Gui, Add, Edit, x282 y128 w120 h23 vCustomMask,



Gui, Add, Button, x12 y170 w140 h30 vBtnSetNtfs gSetNtfs, 修改 NTFS 权限
Gui, Add, Button, x170 y170 w140 h30 vBtnSetFileAttr gSetFileAttr, 修改文件/夹属性
Gui, Add, Button, x340 y170 w210 h30 gRemoveUser, 从安全列表里删除当前用户

Gui, Add, GroupBox, x12 y210 w540 h85, 文件属性选项 (文件夹也有效)
Gui, Add, CheckBox, x22 y230 w80 vAttrReadOnly, 只读 (+R)
Gui, Add, CheckBox, x120 y230 w80 vAttrHidden, 隐藏 (+H)
Gui, Add, CheckBox, x220 y230 w80 vAttrSystem, 系统 (+S)
Gui, Add, CheckBox, x320 y230 w80 vAttrArchive, 存档 (+A)
Gui, Add, CheckBox, x320 y265 w220 vAttrRemove, 移除勾选的属性 (-R/-H/-S/-A)
Gui, Add, CheckBox, x22 y265 w260 vRecurseSubfolders, 递归应用到子文件/文件夹 (小心)

Gui, Add, ListBox, x12 y320 w540 h130 vLogBox
Gui, Add, Text, x12 y460 w430 h30 vStatusText, 状态：就绪
Gui, Add, Button, x462 y455 w90 gClearLog, 清空日志

; 填充下拉列表
GuiControl, , UserName, % listStr
if (listStr != "")
    GuiControl, Choose, UserName, 1

Gui, Show, w570 h500, 权限管理工具

; 将早期日志追加到日志框
if (earlyLog != "") {
    GuiControlGet, curLog, , LogBox
    newLog := earlyLog . curLog
    GuiControl, , LogBox, %newLog%
}
 DebugOut("---支持拖拽文件/夹到目标编辑框---")
return

;-------------------------------- 事件处理 --------------------------------
OnPermMaskChange:
    GuiControlGet, PermMask
    if (PermMask = "自定义") {
        GuiControlGet, CustomMask
        if (CustomMask = "") {
            GuiControl, , CustomMask, (OI)(CI)F
         DebugOut("提示：已自动填充自定义掩码示例 (OI)(CI)F")
        }
    } else {
        GuiControl, , CustomMask,
    }
return

ShowPermHelp:
    helpText =
(
【权限掩码说明】
F        = 完全控制 (允许所有操作)
M        = 修改 (读取、写入、删除)
RX       = 读取和执行
R        = 只读
W        = 写入

【自定义掩码】
可组合多个权限，例如：
(CI)       = 容器继承（子文件夹继承）
(OI)       = 对象继承（文件继承）
(IO)       = 仅继承
(GR)       = 一般读取
(GW)       = 一般写入
(GE)       = 一般执行
(GA)       = 一般所有
(WD)       = 删除
(WO)       = 取得所有权
(RC)       = 读取控制

常见示例：
(OI)(CI)F   = 文件夹及文件完全控制并继承
(OI)(CI)RX  = 文件夹及文件只读继承
(OI)M       = 文件修改，但子文件夹不继承

点击确定关闭。
)
    MsgBox, 0, 权限掩码帮助, %helpText%
return

ShowAttrIntro:
    introText =
(
【文件属性 vs 文件夹属性】

只读 (+R)：
- 对文件：禁止修改、删除（可强制覆盖）
- 对文件夹：不影响写入/创建/删除子项目；仅作为是否自定义名称等的识别标记（资源管理器显示锁图标）

隐藏 (+H)：
- 对文件：资源管理器默认不显示
- 对文件夹：完全有效，文件夹默认隐藏

系统 (+S)：
- 对文件：标记为系统文件（受保护）
- 对文件夹：有效，标记为系统文件夹

存档 (+A)：
- 对文件：标记为需要备份
- 对文件夹：有效，备份软件会处理

【常见误区】
- 给文件夹加“只读”无法阻止别人修改文件夹内的文件 → 请使用 NTFS 权限（本工具的“修改 NTFS 权限”）
- 给文件夹加“隐藏”可以安全隐藏整个目录

点击确定关闭。
)
    MsgBox, 0, 文件属性与文件夹属性区别, %introText%
return

ShowUserIntro:
    UserintroText =
(
【用户/组类型说明】

=== 本地用户 ===
- Administrator : 系统内置管理员账户，拥有最高权限，默认禁用（建议保持禁用）。
- Guest : 来宾账户，权限极低，默认禁用。
- DefaultAccount : 系统默认账户，用于运行某些系统服务。
- WDAGUtilityAccount : Windows Defender 应用防护使用的虚拟账户。

--- 普通用户 ---
您自己创建的用户账户（如 John, Alice），属于 Users 组，可被授予文件/文件夹权限。

=== 本地组 ===
- Administrators : 管理员组。成员拥有完全控制权限，可执行任何操作。
- Users : 普通用户组。成员可以运行应用程序、使用打印机等，但不能修改系统设置或安装软件。
- Guests : 来宾组。权限比 Users 更低，通常用于临时访问。
- Power Users : 已淘汰（保留兼容性）。早期版本中拥有介于 Users 和 Administrators 之间的权限。
- Backup Operators : 备份操作员组。成员可以备份/还原文件，无论其 NTFS 权限如何。
- Remote Desktop Users : 远程桌面用户组。成员可通过远程桌面登录。
- Network Configuration Operators : 网络配置操作员，可修改 TCP/IP 设置。
- Performance Monitor Users : 可访问性能计数器。
- Cryptographic Operators : 可执行加密操作。
- Event Log Readers : 可读取事件日志。
- Hyper-V Administrators : 完全访问 Hyper-V 功能。
- IIS_IUSRS : IIS 匿名用户组，用于 Web 应用程序。

=== 特殊主体（内置安全身份）===
- Everyone : 所有用户，包括匿名、来宾、验证用户。最宽松的权限分配对象（风险高）。
- Authenticated Users : 所有已验证身份的用户（不包括 Guest）。比 Everyone 更安全。
- SYSTEM : 操作系统账户（最高权限）。常被服务使用。
- CREATOR OWNER : 文件/文件夹的创建者。例如将某个文件夹的权限设置为“CREATOR OWNER:完全控制”后，谁创建的文件谁就拥有完全控制权。
- Users : 这里指“经过验证的用户”（类似于 Authenticated Users），但范围更广。在权限列表中手动输入 Users 通常会映射到 BUILTIN\Users。
- INTERACTIVE : 本地登录的用户。
- NETWORK : 通过网络访问的用户。
- SERVICE : 作为服务登录的账户。
- LOCAL SERVICE : 本地服务账户（较低权限）。
- NETWORK SERVICE : 网络服务账户（中等权限）。
- TrustedInstaller (NT SERVICE\TrustedInstaller) : 系统核心文件与注册表的"守护者"，权限高于 SYSTEM，普通权限无法修改由其"拥有"的系统关键文件。[reference:7][1]{.cite .cite-1}

=== 使用建议 ===
- 日常操作推荐使用 **Users** 组或自定义用户。
- 给文件夹授权时，避免直接使用 **Everyone**，优先使用 **Authenticated Users**。
- **Administrators** 和 **SYSTEM** 应仅在必要时授予。
- 手动输入时可使用格式：`用户名`、`组名` 或 `DOMAIN\用户名`、`BUILTIN\组名`。

更多特殊主体可参考 Microsoft 文档。
)
    MsgBox, 0, 用户/组类型介绍, %UserintroText%
return

BrowseFile:
    FileSelectFile, selectedPath, 3, , 选择文件或文件夹
    if (selectedPath != "")
        GuiControl, , TargetPath, %selectedPath%
return

BrowseFolder:
    FileSelectFolder, selectedFolder, *%A_WorkingDir%, 3, 选择文件夹
    if (selectedFolder != "")
        GuiControl, , TargetPath, %selectedFolder%
return

SetNtfs:
    GuiControlGet, TargetPath
    GuiControlGet, UserName
    GuiControlGet, PermType
    GuiControlGet, PermMask
    GuiControlGet, CustomMask

    ; 检查是否选择了分隔线
    if (InStr(UserName, "---") > 0) {
        DebugOut("错误：请选择一个有效的用户或组，不能选择分隔线。")
        GuiControl, , StatusText, 状态：所选条目无效
        return
    }
    if (TargetPath = "" or UserName = "") {
        DebugOut("错误：路径或用户名不能为空！")
        GuiControl, , StatusText, 状态：输入有误，请检查
        return
    }
    if not FileExist(TargetPath) {
        DebugOut("错误：路径不存在 - " TargetPath)
        GuiControl, , StatusText, 状态：路径不存在
        return
    }

    ; 确定权限掩码
    mask := ""
    if (PermMask = "F (完全控制)")
        mask := "F"
    else if (PermMask = "M (修改)")
        mask := "M"
    else if (PermMask = "RX (读取和执行)")
        mask := "RX"
    else if (PermMask = "R (只读)")
        mask := "R"
    else if (PermMask = "W (写入)")
        mask := "W"
    else {
        if (CustomMask = "") {
            DebugOut("错误：自定义权限掩码为空，请填写掩码表达式")
            GuiControl, , StatusText, 状态：自定义掩码不能为空
            return
        }
        mask := CustomMask
    }

    cmdSwitch := (PermType = "允许") ? "/grant" : "/deny"
    icaclsArg := cmdSwitch . " """ . UserName . """:(" . mask . ")"
    command := "icacls """ . TargetPath . """ " . icaclsArg

    DebugOut("执行命令：" . command)
    GuiControl, , StatusText, 状态：正在修改 NTFS 权限，请稍候...

    ; 尝试执行 icacls（不自动提权）
    RunWait, %ComSpec% /c %command%, , Hide

    if (ErrorLevel = 0) {
        DebugOut("成功：NTFS 权限已修改 (" . PermType . " " . mask . ")")
        GuiControl, , StatusText, 状态：NTFS 权限修改成功
    } else {
        DebugOut("失败：NTFS 权限修改未成功 (ErrorLevel = " . ErrorLevel . ")")
        GuiControl, , StatusText, 状态：NTFS 权限修改失败，可能是权限不足"
        ; 询问用户是否以管理员身份重试
        MsgBox, 4, 权限不足, 修改 NTFS 权限失败，通常需要管理员权限。`n`n是否以管理员身份重新运行本工具？`n（注意：工具将重启，当前未保存的设置会丢失。）
        IfMsgBox Yes
        {
            Run *RunAs "%A_ScriptFullPath%"
            ExitApp
        }
    }
return

SetFileAttr:
    GuiControlGet, TargetPath
    if (TargetPath = "") {
 DebugOut("错误：目标路径为空，无法修改属性")
        GuiControl, , StatusText, 状态：请填写目标路径
        return
    }
    if not FileExist(TargetPath) {
 DebugOut("错误：路径不存在 - " TargetPath)
        GuiControl, , StatusText, 状态：路径不存在
        return
    }
    GuiControlGet, AttrReadOnly
    GuiControlGet, AttrHidden
    GuiControlGet, AttrSystem
    GuiControlGet, AttrArchive
    GuiControlGet, AttrRemove
    GuiControlGet, RecurseSubfolders
    attribFlags := ""
    if (AttrReadOnly)
        attribFlags .= (AttrRemove ? "-R" : "+R")
    if (AttrHidden)
        attribFlags .= (AttrRemove ? "-H" : "+H")
    if (AttrSystem)
        attribFlags .= (AttrRemove ? "-S" : "+S")
    if (AttrArchive)
        attribFlags .= (AttrRemove ? "-A" : "+A")
    if (attribFlags = "") {
  DebugOut("错误：未勾选任何文件属性，无法修改")
        GuiControl, , StatusText, 状态：请至少勾选一个属性选项
        return
    }
DebugOut("正在修改属性：为 " . TargetPath . " 设置 " . attribFlags)
    GuiControl, , StatusText, 状态：正在修改文件属性...
    RecurseFlag := RecurseSubfolders ? 1 : 0
    FileSetAttrib, %attribFlags%, %TargetPath%, , %RecurseFlag%
    if (ErrorLevel = 0) {
  DebugOut("成功：文件属性已修改 (" . attribFlags . ")")
        GuiControl, , StatusText, 状态：文件属性修改成功"
    } else {
 DebugOut("失败：文件属性修改失败 (ErrorLevel = " . ErrorLevel . ")")
        GuiControl, , StatusText, 状态：文件属性修改失败，可能是权限不足"
        MsgBox, 48, 权限不足, 修改文件属性失败，原因可能是当前用户对目标路径没有足够的 NTFS 权限。`n`n请先使用本工具的「修改 NTFS 权限」为当前用户授予至少「修改(M)」或更高权限，然后再试。`n`n是否需要立即打开帮助？, 2
        IfMsgBox, OK
            MsgBox, 64, 授予权限帮助, 请选择要修改权限的「用户/组」，然后选择「允许」和「M（修改）」权限，再点击「修改 NTFS 权限」。
    }
return

RemoveUser:
    ; 获取当前界面选择的目标路径和用户/组
    GuiControlGet, TargetPath
    GuiControlGet, UserName

    ; 验证输入
    if (TargetPath = "") {
        MsgBox, 48, 错误, 请先填写目标路径。
        return
    }
    if (UserName = "") {
        MsgBox, 48, 错误, 请选择或输入要删除的用户/组。
        return
    }
    if (InStr(UserName, "---") > 0) {
        MsgBox, 48, 错误, 不能删除分隔线，请选择具体的用户或组。
        return
    }
    if not FileExist(TargetPath) {
        MsgBox, 48, 错误, 目标路径不存在：%TargetPath%
        return
    }

    ; 第一次确认
    MsgBox, 4, 确认删除, 确定要从“%TargetPath%”的安全权限列表中删除用户/组“%UserName%”吗？`n`n此操作不可撤销，删除后该用户/组将不再拥有此路径的任何访问权限（除非继承父目录权限）。
    IfMsgBox No
        return

    ; 第二次确认（更强烈警告）
    MsgBox, 4, 最终确认, 再次确认：你要删除用户/组“%UserName%”对“%TargetPath%”的所有权限条目吗？`n`n此操作将移除该用户/组在此路径上的所有明确授权（允许和拒绝）。
    IfMsgBox No
        return

    ; 构造 icacls /remove 命令
    command := "icacls """ . TargetPath . """ /remove """ . UserName . """"
    DebugOut("执行删除命令：" . command)
    GuiControl, , StatusText, 状态：正在删除用户/组的权限，请稍候...

    ; 执行命令
    RunWait, %ComSpec% /c %command%, , Hide

    if (ErrorLevel = 0) {
        DebugOut("成功：已从 " . TargetPath . " 的权限列表中删除 " . UserName)
        GuiControl, , StatusText, 状态：删除成功
        MsgBox, 64, 成功, 用户/组“%UserName%”已从目标路径的权限列表中删除。
    } else {
        DebugOut("失败：删除操作未成功 (ErrorLevel=" . ErrorLevel . ")")
        GuiControl, , StatusText, 状态：删除失败，请检查权限或用户是否存在"
        MsgBox, 48, 失败, 删除操作失败。`n可能原因：`n- 当前用户没有修改该路径 ACL 的权限`n- 该用户/组在此路径上没有明确的权限条目`n- 该权限条目是从父目录继承的（需要禁用继承后才能删除）`n`n建议以管理员身份运行并重试。
    }
return

; ------------------------------- 拖拽文件到目标路径 -------------------------------
GuiDropFiles:
    ; 获取拖拽的文件列表（换行分隔）
    files := A_GuiEvent
    ; 取第一个文件/文件夹
    firstItem := ""
    Loop, Parse, files, `n
    {
        firstItem := A_LoopField
        break
    }
    if (firstItem = "")
        return

    ; 检查拖拽的目标控件名称
    targetCtrl := A_GuiControl
    if (targetCtrl = "TargetPath") {
        GuiControl, , TargetPath, %firstItem%
        DebugOut("拖拽路径: " firstItem)
    } else {
        ; 可选：拖拽到其他区域时忽略或提示
        ; DebugOut("拖拽已忽略，请拖拽到「目标路径」编辑框")
    }
return

ClearLog:
    GuiControl, , LogBox
return

GuiClose:
    ExitApp
return

GuiSize:
return
