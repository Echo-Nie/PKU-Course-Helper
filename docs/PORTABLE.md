# 北大选课助手 · 基础便携包

此文档对应 `tools/build_local.ps1` 生成的基础便携包。它依赖系统已有的
Microsoft Edge WebView2；如需内置运行环境，可使用单独的私有运行环境打包流程。

完整中英文教程见 [项目主页](https://github.com/Echo-Nie/PKU-Course-Helper)，发布流程见
[RELEASING.md](https://github.com/Echo-Nie/PKU-Course-Helper/blob/main/docs/RELEASING.md)。

## 使用与移除

完整解压后双击 `PKUCourseHelper.exe`，不要只复制 EXE。应用数据保存在同目录
的 `data` 文件夹；退出后删除整个解压目录即可移除软件自有内容。

1. 退出旧版程序，在页面下方输入统一认证学号和密码。
2. 添加课程，核对课程全名、开课单位、班号和所在页码。班号 `00` 与 `0` 等价。
3. 主修和选修共用学校主修入口，辅修使用辅修入口。
4. 按需调整同组优先级、互斥规则和延迟阈值，保存后点击“开始运行”。
5. 在页面上方查看运行情况和每门课的具体提示，最终结果以学校已选列表为准。

密码仅保存在本次会话。不要公开分享包含个人配置和日志的 `data` 目录。
保留默认 6 秒查询间隔与 0.2 随机偏移，保持网络畅通与电脑唤醒。

目标平台为 Windows 10/11 x64，需要系统已有 WebView2 Runtime 和 .NET Framework
4.6.2 或更高版本。此包不会安装或更新系统组件。

## 构建

在 Windows x64、Python 3.11 x64 和 Node.js 22 环境中运行；脚本会自动准备 `uv`：

```powershell
./tools/build_local.ps1
```

脚本会执行测试、冻结程序、收集许可证、运行离线自检并审计 ZIP 内容。构建成功不等于
已经完成所有真实 Windows 界面和网络场景验收。

## 来源

基于 [Aerisun/PKUAutoElective2026](https://github.com/Aerisun/PKUAutoElective2026) 修改，
继承 Hovennnnn/PKUAutoElective2023 与 zhongxinghong/PKUAutoElective 的工作。
感谢学长学姐和所有贡献者。
