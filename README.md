# 北大选课助手 · PKU Course Helper

**中文** | [English](README.en.md)

用于北京大学补退选的 Windows 选课辅助工具。北京大学选课脚本/抢课脚本/选课助手、运行监控与账号设置，支持主修、选修、辅修、班号 `00`、优先级、课程互斥、延迟选课和日志查看。

![界面预览（模拟数据）](docs/images/workspace.png)

## 如何使用

可以下载程序包直接运行，也可以克隆仓库运行源码并自行修改。

### 方式一：从 Release 下载程序包

运行环境：**Windows 10/11 x64**

1. 打开 [Release / v1.0.1](https://github.com/Echo-Nie/PKU-Course-Helper/releases/tag/v1.0.1)，下载 `PKUCourseHelper-windows-x64-portable.zip`。
2. 将 ZIP **完整解压**到可写文件夹，阅读包内的 `使用说明.md`。
3. 双击解压目录中的 `PKUCourseHelper.exe`，按页面顶部的指引配置并开始使用。请保留 `_internal` 等同目录文件，不要只复制 EXE。

### 方式二：克隆仓库，运行源码或 DIY

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

### 启动后的配置

1. 填写统一认证学号和密码，添加课程，核对全名、开课单位、班号和页码。
2. **主修／选修**共用主修入口，**辅修**使用辅修入口；页码从 `1` 开始，班号 `00` 与 `0` 等价，班号不是完整课程编号。
3. 按需调整同一入口、同一页内的优先级，设置互斥组或延迟阈值。保存后点击“开始运行”。
4. 查看状态下方的具体原因及日志。运行中保存修改后，可确认重启并应用；退出程序会停止任务。

建议保留默认 `6 秒`查询间隔与 `0.2` 随机偏移，保持电脑唤醒、网络畅通。

## 账号与本地数据说明

- **本地保存，无开发者云端存储：** 学号、课程配置及运行日志保存在你电脑的软件目录 `data/` 中，不会由本项目自动上传给开发者或同步到开发者的云端服务。
- **密码仅用于本次会话：** 当前桌面版不保存密码到配置文件，退出后需重新输入。学号与课程配置是本地文件，请勿公开分享 `data/`、导出的配置或含个人信息的日志截图。
- **必要的学校通信：** 登录时，程序会通过 HTTPS 将学号和密码发送给学校统一认证系统（`iaaa.pku.edu.cn`），并与学校选课系统通信以查询、选课。“本地保存”不代表离线运行或无需向学校提交登录信息。

迁移配置时，先退出新旧程序，再将旧 `data/` 复制到新程序目录。

## 常见问题

- 账号／密码错误：核对统一认证信息；学校未区分错误字段时，会显示“账号或密码错误”。
- 找不到课程：检查对应入口、页码、全名、开课单位、班号及补退选计划。
- 辅修入口不可用：确认学校页面是否提供该入口；普通选修应选择“选修”。

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

感谢前辈们以及所有贡献者的积累与分享。

## 使用声明

本项目仅用于技术学习与交流，严禁在公共平台、公开群聊等公共场合扩散、宣传或推广。请遵守学校相关规定，勿干扰系统运行，勿公开账号、配置或日志；选课结果以学校系统为准。

以上为交流与使用约定，代码授权以 [LICENSE](LICENSE) 为准。
