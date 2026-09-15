; Per-user installer. Payload files are removed using Inno's ownership log.
; Never recursively delete {app}, a profile root, or a shared runtime.
#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef ArtifactDir
  #error ArtifactDir is required
#endif
#define ProductId "6AF68EC2-4877-4A72-B3EB-41776586D9DF"
#ifndef ReleaseVersion
  #define ReleaseVersion "0.1.0"
#endif
#ifndef NumericVersion
  #define NumericVersion "0.1.0"
#endif

[Setup]
AppId={{{#ProductId}}
AppName=PKUCourseHelper
AppVersion={#ReleaseVersion}
VersionInfoVersion={#NumericVersion}
VersionInfoProductVersion={#NumericVersion}
VersionInfoProductTextVersion={#ReleaseVersion}
AppPublisher=PKUAutoElective contributors
DefaultDirName={localappdata}\Programs\PKUCourseHelper
DisableDirPage=yes
UsePreviousAppDir=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#ArtifactDir}
OutputBaseFilename=PKUCourseHelper-windows-x64-setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
AppMutex=Local\PKUAutoElectiveDesktop
SetupMutex=Local\PKUAutoElectiveInstaller
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\PKUCourseHelper.exe
UninstallDisplayName=PKUCourseHelper
UninstallLogMode=append
SetupLogging=no
InfoBeforeFile=installer-info.txt

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\PKUCourseHelper"; Filename: "{app}\PKUCourseHelper.exe"; WorkingDir: "{app}"

[Messages]
ConfirmUninstall=卸载将永久删除PKUCourseHelper及其全部课程配置、加密密码、日志和缓存。手动导出的文件不会删除。是否继续？
UninstalledAll=主程序和应用数据已移除。关闭此窗口后会清理卸载临时副本，失败会另行提示。Windows 自身的运行记录和您另存的文件不属于清理范围。
UninstalledMost=卸载尚未完全完成：部分文件仍被占用或无法删除。请关闭相关窗口后重试，不要将此次结果视为完整清理。

[UninstallDelete]
; Data is removed, with error handling, only after confirmation in [Code].
Type: dirifempty; Name: "{app}"

[Code]
var
  MaintenanceHandle: LongWord;

const
  ReparseAttribute = $400;
  DirectoryAttribute = $10;
  InvalidAttributes = $FFFFFFFF;

function GetFileAttributesW(Name: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function GetModuleFileNameW(Module: Cardinal; FileName: String; Size: Cardinal): Cardinal;
  external 'GetModuleFileNameW@kernel32.dll stdcall';

function GetCurrentProcessId: Cardinal;
  external 'GetCurrentProcessId@kernel32.dll stdcall';

function SetEnvironmentVariableW(Name, Value: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

// The pinned Inno Setup 6.7.3 engine is a 32-bit process (also on x64 Windows).
function CreateMutexW(Security: LongWord; Owner: Boolean; Name: String): LongWord;
  external 'CreateMutexW@kernel32.dll stdcall';

function Win32LastError: Cardinal;
  external 'GetLastError@kernel32.dll stdcall';

function CloseHandle(Handle: LongWord): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function AcquireMaintenance: Boolean;
var Existing: Boolean;
begin
  MaintenanceHandle := CreateMutexW(0, False, 'Local\PKUAutoElectiveMaintenance');
  Existing := Win32LastError = 183;
  Result := (MaintenanceHandle <> 0) and not Existing;
  if not Result then begin
    if MaintenanceHandle <> 0 then CloseHandle(MaintenanceHandle);
    MaintenanceHandle := 0;
    MsgBox('另一个安装或卸载窗口正在运行，或无法取得维护权限。请关闭相关窗口后重试。', mbError, MB_OK);
  end;
  // Successful handles stay alive until this process exits, including dialogs.
end;

function IsReparse(const Name: String): Boolean;
var Attributes: Cardinal;
begin
  Attributes := GetFileAttributesW(Name);
  Result := (Attributes <> InvalidAttributes) and ((Attributes and ReparseAttribute) <> 0);
end;

function ExpectedRoot: String;
begin
  Result := ExpandConstant('{localappdata}\Programs\PKUCourseHelper');
end;

function InitializeSetup: Boolean;
begin
  Result := AcquireMaintenance;
end;

function SafeRoot: Boolean;
var Current, Parent: String;
begin
  Current := RemoveBackslashUnlessRoot(ExpandFileName(ExpandConstant('{app}')));
  Result := CompareText(Current, RemoveBackslashUnlessRoot(ExpandFileName(ExpectedRoot))) = 0;
  if not Result then exit;
  repeat
    if IsReparse(Current) then begin Result := False; exit; end;
    Parent := ExtractFileDir(Current);
    if CompareText(Parent, Current) = 0 then break;
    Current := Parent;
  until Current = '';
end;

function HasEntries(const Path: String): Boolean;
var Entry: TFindRec;
begin
  Result := False;
  if FindFirst(AddBackslash(Path) + '*', Entry) then
  try
    repeat
      if (Entry.Name <> '.') and (Entry.Name <> '..') then begin Result := True; break; end;
    until not FindNext(Entry);
  finally FindClose(Entry); end;
end;

function OwnsInstallation: Boolean;
begin
  Result := GetIniString('Installation', 'ProductId', '',
    ExpandConstant('{app}\install-layout.ini')) = '{#ProductId}';
end;

function PayloadHasLinks(const Path: String): Boolean;
var Entry: TFindRec; Child: String;
begin
  Result := IsReparse(Path);
  if Result then exit;
  if FindFirst(AddBackslash(Path) + '*', Entry) then
  try
    repeat
      if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
        Child := AddBackslash(Path) + Entry.Name;
        if ((Entry.Attributes and ReparseAttribute) <> 0) then Result := True
        else if ((Entry.Attributes and DirectoryAttribute) <> 0) then
          Result := PayloadHasLinks(Child);
        if Result then break;
      end;
    until not FindNext(Entry);
  finally FindClose(Entry); end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Release: Cardinal;
begin
  Result := '';
  if not SafeRoot then
    Result := '安装位置必须是当前用户的专用目录，且不能包含符号链接或目录联接。'
  else if DirExists(ExpectedRoot) and HasEntries(ExpectedRoot) and not OwnsInstallation then
    Result := '目标目录包含不属于本安装程序的文件，已停止安装以免覆盖。'
  else if not RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release) then
    Result := '系统缺少 .NET Framework。安装程序不会安装或修改共享系统组件。'
  else if Release < 394802 then
    Result := '需要系统已有 .NET Framework 4.6.2 或更新版本。';
  if (Result = '') and OwnsInstallation then begin
    if PayloadHasLinks(ExpandConstant('{app}\_internal')) or
       PayloadHasLinks(ExpandConstant('{app}\runtime')) or
       PayloadHasLinks(ExpandConstant('{app}\licenses')) then
      Result := '程序目录包含外部链接，已停止覆盖安装。';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var ExitCode: Integer; Version: TWindowsVersion;
begin
  if CurStep = ssPostInstall then begin
    // Windows 10 Fixed Version WebView2 requires read/execute for AppContainer.
    // Restrict ACL changes to this installation's private browser, not parent directories.
    GetWindowsVersionEx(Version);
    if Version.Build < 22000 then begin
      if not Exec(ExpandConstant('{sys}\icacls.exe'), '"' + ExpandConstant('{app}\runtime\webview2') +
        '" /grant *S-1-15-2-2:(OI)(CI)(RX) *S-1-15-2-1:(OI)(CI)(RX)',
        '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
        RaiseException('私有运行时的目录权限设置失败，请重新安装修复。');
    end;
  end;
end;

function StartTemporaryCopyCleanup: Boolean;
var ImageName, ReadyName, Parameters, OldCache: String; Length, Attempt: Cardinal; ExitCode: Integer;
begin
  Result := False;
  SetLength(ImageName, 32768);
  Length := GetModuleFileNameW(0, ImageName, 32768);
  if (Length = 0) or (Length >= 32768) then exit;
  SetLength(ImageName, Length);
  ReadyName := ExpandConstant('{tmp}\pku-cleanup-ready.txt');
  Parameters := '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{app}\_internal\maintenance\uninstall_cleanup.ps1') +
    '" -UninstallerPid ' + IntToStr(GetCurrentProcessId) + ' -ImagePath "' + ImageName +
    '" -ReadyPath "' + ReadyName + '"';
  // Disable the helper's module cache before PowerShell starts. This changes
  // only this process and its child, never the user/machine environment.
  OldCache := GetEnv('PSModuleAnalysisCachePath');
  if not SetEnvironmentVariableW('PSModuleAnalysisCachePath', 'NUL') then exit;
  try
    Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Parameters,
      ExpandConstant('{sys}'), SW_HIDE, ewNoWait, ExitCode);
  finally
    SetEnvironmentVariableW('PSModuleAnalysisCachePath', OldCache);
  end;
  if not Result then exit;
  Result := False;
  // Wait for a pinned process handle and validated exact temporary path.
  for Attempt := 1 to 600 do begin
    if FileExists(ReadyName) then begin Result := True; exit; end;
    Sleep(50);
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := AcquireMaintenance;
  if not Result then exit;
  Result := SafeRoot and OwnsInstallation;
  if Result then
    Result := not PayloadHasLinks(ExpandConstant('{app}\_internal')) and
              not PayloadHasLinks(ExpandConstant('{app}\runtime')) and
              not PayloadHasLinks(ExpandConstant('{app}\licenses'));
  if not Result then
    MsgBox('安装位置或所有权信息异常，已停止卸载，不会删除外部文件。请先修复安装。', mbError, MB_OK)
  else begin
    Result := StartTemporaryCopyCleanup;
    if not Result then
      MsgBox('无法启动卸载临时文件清理，已停止卸载。请检查 PowerShell 是否可用后重试。', mbError, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then begin
    // This event is after user confirmation and the native AppMutex check.
    // Inno treats exceptions here as fatal, before deleting installed files.
    if not SafeRoot or not OwnsInstallation then
      RaiseException('卸载目录校验失败，已停止。');
    if DirExists(ExpandConstant('{app}\data')) or IsReparse(ExpandConstant('{app}\data')) then
      if not DelTree(ExpandConstant('{app}\data'), True, True, True) then
        RaiseException('数据仍被占用或无法删除，卸载未完成。请关闭相关窗口后重试。');
  end;
end;
