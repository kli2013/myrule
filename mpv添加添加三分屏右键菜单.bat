@Echo Off
Title Reg Converter v1.2 & Color 1A
cd %systemroot%\system32
call :IsAdmin

rem 放到mpv.exe同目录运行

Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.3gp2\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.3gp2\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.3gpp\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.3gpp\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.3iv\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.3iv\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.avi\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.avi\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.divx\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.divx\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.dv\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.dv\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.f4v\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.f4v\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.flv\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.flv\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.h264\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.h264\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.hdmov\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.hdmov\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.hevc\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.hevc\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.mkv\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.mkv\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.mpeg\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.mpeg\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.mpeg4\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.mpeg4\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.rm\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.rm\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.rmvb\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.rmvb\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.webm\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.webm\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.wmv\shell\open1" /ve /t REG_SZ /d "使用 MPV 水平分三屏 播放" /f
Reg.exe add "HKLM\SOFTWARE\Classes\io.mpv.wmv\shell\open1\command" /ve /t REG_SZ /d "\"%CD%\mpv.exe\" \"%%L\" --external-file=\"%%L\" --external-file=\"%%L\" --lavfi-complex=\"[vid1] [vid2] hstack [t1] ; [t1] [vid3] hstack [vo]\"" /f
Exit

:IsAdmin
Reg.exe query "HKU\S-1-5-19\Environment"
If Not %ERRORLEVEL% EQU 0 (
 Cls & Echo You must have administrator rights to continue ... 
 Pause & Exit
)
Cls
goto:eof
