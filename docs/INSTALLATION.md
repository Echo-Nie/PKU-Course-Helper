# 安装版（历史维护用途）

当前正式交付物是免安装 ZIP，本安装版不参与自动 Release。此文件仅供维护
`packaging/build_installer.ps1` 时使用。

安装版面向当前 Windows 用户，默认安装到：

```text
%LOCALAPPDATA%\Programs\PKUCourseHelper
```

它只创建开始菜单快捷方式和标准卸载入口，不添加服务、计划任务、开机启动项或系统
PATH，也不安装共享 Python、Node.js 或 WebView2。

卸载前应先停止任务并退出程序，然后通过 Windows“设置 → 应用 → 已安装的应用”卸载，
或运行安装目录中的 `unins000.exe`。确认卸载会删除安装目录中的程序、课程配置、密码
数据、日志和缓存；需要保留的内容应先导出到安装目录之外。

构建安装器需要 Windows x64、Inno Setup 6.7.3 和经过来源及 SHA-256 校验的私有
WebView2 CAB：

```powershell
./packaging/build_installer.ps1 `
  -WebView2RuntimeCab C:\build-inputs\runtime.cab `
  -RuntimeSha256 <可信校验值> `
  -InnoCompiler 'C:\build-tools\Inno Setup 6\ISCC.exe'
```

安装器候选必须完成真实安装、启动、停止、卸载和残留检查后才能交付。主程序和安装器
目前没有商业代码签名，Windows 可能提示未知发布者。
