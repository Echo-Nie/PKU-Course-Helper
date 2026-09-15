# 北大选课助手 · PKU Course Helper

**中文** | [English](README.en.md)

用于北京大学补退选的 Windows 选课辅助工具。一个页面完成课程管理、运行监控与账号设置，支持主修、选修、辅修、班号 `00`、优先级、课程互斥、延迟选课和日志查看。

![界面预览（模拟数据）](docs/images/workspace.png)

## 使用方法

运行环境：**Windows 10/11 x64**、**WebView2 Runtime**、**.NET Framework 4.6.2+**。打包版不需要 Python 或 Node.js。

1. 完整解压 ZIP，退出旧版程序，双击 `PKUCourseHelper.exe`；保留 `_internal` 等同目录文件。
2. 填写统一认证学号和密码。密码仅保留在本次会话中。
3. 添加课程，核对课程全名、开课单位、班号和页码：
   - **主修／选修**共用主修入口，**辅修**使用辅修入口。
   - 页码从 `1` 开始；班号 `00` 与 `0` 等价，班号不是完整课程编号。
4. 按需调整同一入口、同一页内的优先级，设置互斥组或延迟阈值。保存后点击“开始运行”。
5. 查看状态下方的具体原因及日志。运行中保存修改后，可确认重启并应用；退出程序会停止任务。

建议保留默认 `6 秒`查询间隔与 `0.2` 随机偏移，保持电脑唤醒、网络畅通。配置和日志位于 `data/`；迁移时先退出新旧程序，再复制该目录。

**常见问题：**

- 点击 EXE 无反应：先确认旧版已退出；必要时在任务管理器检查 `CourseSelectionAssistant.exe` 或 `PKUCourseHelper.exe`。
- 账号／密码错误：核对统一认证信息；学校未区分错误字段时，会显示“账号或密码错误”。
- 找不到课程：检查对应入口、页码、全名、开课单位、班号及补退选计划。
- 辅修入口不可用：确认学校页面是否提供该入口；普通选修应选择“选修”。

## 源码运行

准备 **Python 3.11 x64**、**Node.js 22** 和 WebView2，在 Git Bash 中运行：

```bash
git clone https://github.com/Echo-Nie/PKU-Course-Helper.git
cd PKU-Course-Helper
python -m pip install -r requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
python desktop.py
```

虚拟环境可选。修改前端后重新构建并重启程序，修改 Python 后重启即可；已有 EXE 需要重新打包才会更新。

离线桌面预览：`python desktop.py --preview`。浏览器预览：运行 `npm --prefix frontend run dev`，打开 `http://127.0.0.1:5173/?preview=1`；加上 `&scenario=errors` 查看错误示例。预览使用模拟数据，不会登录或选课。

## 打包 EXE

在项目根目录的 **PowerShell** 中运行：

```powershell
.\tools\build_local.ps1
```

**Git Bash** 使用：

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/build_local.ps1
```

脚本自动准备构建环境、安装锁定依赖、运行测试、打包并进行离线自检。构建前先停止前端开发服务，避免文件被占用。

成品位于 `dist/portable/<构建编号>/PKUCourseHelper-windows-x64-portable.zip`。完整解压后运行 EXE。也可在 GitHub Actions 中手动运行 Windows portable 构建；其他发行方式见 [发布说明](docs/RELEASING.md)。

## 参考项目与致谢

本项目基于以下项目修改，保留来源信息与 MIT 许可证：

- [Aerisun/PKUAutoElective2026](https://github.com/Aerisun/PKUAutoElective2026)：直接基础，提供桌面程序、ONNX 推理与多身份调度。
- [Hovennnnn/PKUAutoElective2023](https://github.com/Hovennnnn/PKUAutoElective2023)：前代适配与验证码识别模型。
- [zhongxinghong/PKUAutoElective](https://github.com/zhongxinghong/PKUAutoElective)：选课流程、学校接口及规则实现。

感谢各位学长学姐和所有贡献者的积累与分享。本项目主要调整界面、交互和反馈；模型来源见 [resources/model](resources/model/README.md)。

## 使用声明

本项目仅用于技术学习与交流，严禁在公共平台、公开群聊等公共场合扩散、宣传或推广。请遵守学校相关规定，勿干扰系统运行，勿公开账号、配置或日志；选课结果以学校系统为准。

以上为交流与使用约定，代码授权以 [LICENSE](LICENSE) 为准。
