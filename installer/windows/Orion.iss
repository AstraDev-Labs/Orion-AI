; Orion installer (Inno Setup 6/7).
;
; Build with installer\build-windows.ps1, which compiles the app, stages the
; backend and then runs:
;   ISCC.exe /DAppVersion=<x.y.z> /DAppExe=<path to orion-desktop.exe> Orion.iss
;
; The installer copies the app and Orion's backend, then runs
; orion-setup.ps1 to install the AI engine, the AI model sized for the PC, voice,
; and whichever additional features were ticked. Core features and AI models
; are a fixed component and cannot be unticked. No administrator rights needed.

#ifndef AppVersion
  #define AppVersion "1.0.3"
#endif
#ifndef AppExe
  #define AppExe "..\..\frontend\src-tauri\target\release\orion-desktop.exe"
#endif

[Setup]
AppId={{6B1C2E4F-3A7D-4C1B-9E2F-0A5D8C7B4E31}
AppName=Orion
AppVersion={#AppVersion}
AppVerName=Orion {#AppVersion}
AppPublisher=Orion AI
AppPublisherURL=https://github.com/AstraDev-Labs/Orion-AI
AppSupportURL=https://github.com/AstraDev-Labs/Orion-AI/issues
DefaultDirName={localappdata}\Programs\Orion
DisableProgramGroupPage=yes
; The chosen folder also holds the downloaded runtime, tools and models (several
; GB), so users short on C: can pick another drive. Always shown on a first
; install; an update keeps the existing folder.
DisableDirPage=auto
UsePreviousAppDir=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist
OutputBaseFilename=OrionSetup-{#AppVersion}
SetupIconFile=orion.ico
; Terms of Use and Privacy Policy: must be accepted before anything installs.
LicenseFile=terms-and-privacy.txt
UninstallDisplayIcon={app}\Orion.exe
UninstallDisplayName=Orion
WizardStyle=modern
WizardImageFile=wizard-large.bmp
WizardSmallImageFile=wizard-small.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
; Not Restart Manager's relaunch: it reopened Orion as soon as the files were
; copied, while setup was still rebuilding the Python environment. An in-app
; update reopens Orion from [Run] once setup has finished.
RestartApplications=no
; Setup's RedirectionGuard blocked uv inside orion-setup.ps1 from following the
; folder links it keeps its Python in ("untrusted mount point", error 448).
; The mitigation protects elevated installs from path redirection; this one
; always runs with the user's own rights, so there is nothing to escalate.
RedirectionGuard=no

[Messages]
WelcomeLabel2=This will install Orion, your on-device AI assistant.%n%nSetup downloads the local AI engine and an AI model sized for this PC, so the first install needs an internet connection and about 12 GB of free space on the drive you install to. Everything runs on this computer afterwards.
WizardLicense=Terms of Use and Privacy Policy
LicenseLabel=Please read how Orion works and what it does with your data before continuing.
LicenseLabel3=Orion runs on this computer and sends no analytics. Please read these terms and the privacy policy. You must accept them to install Orion.
LicenseAccepted=I &accept the Terms of Use and Privacy Policy
LicenseNotAccepted=I &do not accept
SelectDirLabel3=Orion, and everything setup downloads for it (Python environment, AI engine and models), will be installed in this folder. Choose another drive if C: is short on space.

[Types]
Name: "recommended"; Description: "Recommended"
Name: "full"; Description: "Everything"
Name: "minimal"; Description: "Core only"
Name: "custom"; Description: "Choose features"; Flags: iscustom

[Components]
Name: "core"; Description: "Orion (required): assistant, local AI engine, AI model, voice and memory"; Types: recommended full minimal custom; Flags: fixed
Name: "whatsapp"; Description: "WhatsApp messaging and auto-reply (installs Node.js, about 80 MB)"; Types: recommended full
Name: "browser"; Description: "Web browser automation (uses Edge or Chrome)"; Types: recommended full
Name: "documents"; Description: "Read PDF documents"; Types: recommended full
Name: "telegram"; Description: "Telegram bot"; Types: full
Name: "gpu"; Description: "GPU power and energy monitoring (NVIDIA only)"; Types: full
Name: "vision"; Description: "Screen and camera understanding (vision model, about 1.7 GB)"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#AppExe}"; DestDir: "{app}"; DestName: "Orion.exe"; Flags: ignoreversion; Components: core
Source: "..\stage\backend\*"; DestDir: "{app}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: core
Source: "orion-setup.ps1"; DestDir: "{app}\setup"; Flags: ignoreversion; Components: core
Source: "orion-uninstall.ps1"; DestDir: "{app}\setup"; Flags: ignoreversion; Components: core
Source: "terms-and-privacy.txt"; DestDir: "{app}"; DestName: "Terms and Privacy.txt"; Flags: ignoreversion; Components: core

[Icons]
Name: "{autoprograms}\Orion"; Filename: "{app}\Orion.exe"
Name: "{autoprograms}\Orion Terms and Privacy"; Filename: "{app}\Terms and Privacy.txt"
Name: "{autodesktop}\Orion"; Filename: "{app}\Orion.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Orion.exe"; Description: "Open Orion"; Flags: postinstall nowait skipifsilent unchecked
; An update started from inside Orion (/UPDATE=1) runs silently; reopen Orion when it is done.
; postinstall matters: plain [Run] entries run before ssPostInstall, which
; reopened Orion while setup was still rebuilding its Python environment.
; Silent installs run postinstall entries automatically.
Filename: "{app}\Orion.exe"; Description: "Open Orion"; Flags: nowait postinstall; Check: IsAppUpdate

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Get-Process | Where-Object {{ $_.Path -like '{app}\*' } | Stop-Process -Force -ErrorAction SilentlyContinue"""; Flags: runhidden; RunOnceId: "StopOrion"

[Code]
const
  MinFreeGB = 12;

var
  SetupSucceeded: Boolean;

{ A completed Orion install has both its durable setup record and its working
  Python runtime. Updates preserve its AI engine, downloaded models, voice,
  settings and feature choices; incomplete installs still use full setup. }
function IsExistingOrionInstallAt(const Dir: String): Boolean;
begin
  Result := FileExists(AddBackslash(Dir) + 'install.json') and
    FileExists(AddBackslash(Dir) + 'runtime\.venv\Scripts\python.exe');
end;

function IsExistingOrionInstall(): Boolean;
begin
  Result := IsExistingOrionInstallAt(RemoveBackslashUnlessRoot(ExpandConstant('{app}')));
end;

{ The actual update decision is repeated after files are copied, but show it
  before the user clicks Install. This makes a completed installation visibly
  different from a first-time setup and explains what will be preserved. }
procedure ConfigureReadyPage;
var
  Updating: Boolean;
begin
  Updating := IsExistingOrionInstallAt(RemoveBackslashUnlessRoot(WizardDirValue()));
  if Updating then
  begin
    WizardForm.PageNameLabel.Caption := 'Ready to Update';
    WizardForm.PageDescriptionLabel.Caption := 'Setup is ready to update Orion on your computer.';
    WizardForm.ReadyLabel.Caption := 'Click Update to refresh Orion. Your AI engine, models, voice, settings and selected features will stay in place.';
    WizardForm.ReadyMemo.Lines.Text := 'Update details:' + #13#10
      + '  • Orion application and backend will be refreshed' + #13#10
      + '  • Local AI engine, downloaded models and voice files will be kept' + #13#10
      + '  • Settings, memories and selected features will be kept';
    WizardForm.NextButton.Caption := '&Update';
  end
  else
  begin
    WizardForm.PageNameLabel.Caption := 'Ready to Install';
    WizardForm.PageDescriptionLabel.Caption := 'Setup is now ready to begin installing Orion on your computer.';
    WizardForm.ReadyLabel.Caption := 'Click Install to continue with the installation, or click Back if you want to review or change any settings.';
    WizardForm.NextButton.Caption := '&Install';
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpReady then ConfigureReadyPage;
end;

{ The install folder must be local and writable by this user: setup keeps
  downloading into it after the wizard, and later updates run without admin
  rights. Warn when the drive is short of space for the downloads. }
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir, Probe, Existing: String;
  Created: Boolean;
  FreeMB, TotalMB: Cardinal;
begin
  Result := True;
  if CurPageID <> wpSelectDir then Exit;
  Dir := RemoveBackslashUnlessRoot(WizardDirValue());

  if Copy(Dir, 1, 2) = '\\' then
  begin
    MsgBox('Please choose a folder on a drive in this computer, not a network location.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  Existing := Dir;
  while (Existing <> '') and not DirExists(Existing) and (ExtractFileDir(Existing) <> Existing) do
    Existing := ExtractFileDir(Existing);
  Created := not DirExists(Dir);
  Probe := AddBackslash(Dir) + 'orion-write-test.tmp';
  if not (ForceDirectories(Dir) and SaveStringToFile(Probe, 'ok', False)) then
  begin
    MsgBox('Orion cannot write to this folder:' + #13#10 + Dir + #13#10#13#10
      + 'Orion installs for your Windows account without administrator rights, so folders such as Program Files are not available. Choose a folder in your user profile or on another drive, for example D:\Orion.', mbError, MB_OK);
    Result := False;
  end;
  DeleteFile(Probe);
  if Created then RemoveDir(Dir);
  if not Result then Exit;

  { A completed update does not download models or voice files, so it does not
    need the first-install free-space requirement. }
  if IsExistingOrionInstallAt(Dir) then Exit;

  if GetSpaceOnDisk(ExtractFileDrive(Dir), True, FreeMB, TotalMB) and (FreeMB < MinFreeGB * 1024) then
    Result := MsgBox(Format('The drive %s has %d GB free. Orion needs about %d GB for the AI engine, model and voice downloads.', [ExtractFileDrive(Dir), FreeMB div 1024, MinFreeGB]) + #13#10#13#10
      + 'Install here anyway?', mbConfirmation, MB_YESNO) = IDYES;
end;

{ Comma-separated additional features for orion-setup.ps1 -Features. }
function SelectedFeatures(): String;
var
  Names: array[0..5] of String;
  I: Integer;
begin
  Names[0] := 'whatsapp';
  Names[1] := 'browser';
  Names[2] := 'documents';
  Names[3] := 'telegram';
  Names[4] := 'gpu';
  Names[5] := 'vision';
  Result := '';
  for I := 0 to 5 do
    if WizardIsComponentSelected(Names[I]) then
    begin
      if Result <> '' then Result := Result + ',';
      Result := Result + Names[I];
    end;
  if Result = '' then Result := 'none';
end;

{ Started by Orion's in-app updater (app_update.rs). }
function IsAppUpdate(): Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;

{ Orion quits itself before an in-app update, but its servers can take a
  moment to exit; files they hold open could not be replaced. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  App: String;
  ResultCode: Integer;
begin
  Result := '';
  App := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
  if DirExists(App) then
    Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -ExecutionPolicy Bypass -Command "$a = ''' + App + '''; Get-Process | Where-Object { $_.Path -and ($_.Path -like ($a + ''\Orion.exe'') -or $_.Path -like ($a + ''\runtime\*'') -or $_.Path -like ($a + ''\tools\python\*'') -or $_.Path -like ($a + ''\tools\node\*'')) } | Stop-Process -Force -ErrorAction SilentlyContinue"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Params: String;
  ResultCode: Integer;
  ShowCmd: Integer;
  Updating: Boolean;
begin
  if CurStep = ssPostInstall then
  begin
    Updating := IsExistingOrionInstall();
    { An in-app update shows Setup's own progress window only. }
    if IsAppUpdate() then
      ShowCmd := SW_HIDE
    else
      ShowCmd := SW_SHOWNORMAL;
    if Updating then
      WizardForm.StatusLabel.Caption := 'Updating Orion. Your AI engine, models, voice, settings and selected features are kept.'
    else
      WizardForm.StatusLabel.Caption := 'Installing the AI engine, AI model, voice and your selected features. A setup window shows the progress; the first install can take a while.';
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup\orion-setup.ps1') + '"'
      + ' -PayloadDir "' + ExpandConstant('{app}\backend') + '"'
      + ' -InstallRoot "' + ExpandConstant('{app}') + '"'
      + ' -Features "' + SelectedFeatures() + '" -NoPause';
    if Updating then Params := Params + ' -Update';
    SetupSucceeded := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '', ShowCmd, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
    if not SetupSucceeded then
      SuppressibleMsgBox('Orion was installed, but setup could not finish downloading everything it needs.' + #13#10#13#10
        + 'Open Orion to try again: it resumes where setup stopped.' + #13#10
        + 'Details: ' + ExpandConstant('{app}\setup.log'), mbError, MB_OK, IDOK);
  end;
end;

{ ---------------------------------------------------------------------------
  Uninstall: the user picks what goes. orion-setup.ps1 records in
  uninstall.ini (install folder) what it installed or downloaded; only those are
  offered, so an Ollama, uv or model that was already on this PC is never
  removed. orion-uninstall.ps1 does the removing.

  Silent uninstall: everything Orion installed is removed, personal data is
  kept. /KEEP=models,engine,... keeps parts; /REMOVEDATA also removes data.
  --------------------------------------------------------------------------- }

const
  PartCount = 7;

var
  UninstallParts: String;

function AppDirNoSlash(): String;
begin
  Result := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
end;

function RecordValue(const Key: String): String;
begin
  Result := GetIniString('Orion', Key, '', AppDirNoSlash() + '\uninstall.ini');
end;

function CommandLineValue(const Name: String): String;
var
  I: Integer;
  Arg: String;
begin
  Result := '';
  for I := 1 to ParamCount do
  begin
    Arg := ParamStr(I);
    if CompareText(Copy(Arg, 1, Length(Name) + 1), Name + '=') = 0 then
      Result := Copy(Arg, Length(Name) + 2, MaxInt)
    else if CompareText(Arg, Name) = 0 then
      Result := '1';
  end;
end;

function ListHas(const List, Item: String): Boolean;
begin
  Result := Pos(',' + Lowercase(Item) + ',', ',' + Lowercase(List) + ',') > 0;
end;

function FeatureSummary(): String;
var
  Raw: AnsiString;
  Chosen: String;
begin
  Result := 'Includes voice and memory';
  if LoadStringFromFile(AppDirNoSlash() + '\features.txt', Raw) then
  begin
    Chosen := Trim(String(Raw));
    if ListHas(Chosen, 'whatsapp') then Result := Result + ', WhatsApp';
    if ListHas(Chosen, 'browser') then Result := Result + ', browser automation';
    if ListHas(Chosen, 'documents') then Result := Result + ', PDF reading';
    if ListHas(Chosen, 'telegram') then Result := Result + ', Telegram';
    if ListHas(Chosen, 'gpu') then Result := Result + ', GPU monitoring';
    if ListHas(Chosen, 'vision') then Result := Result + ', screen understanding';
  end;
end;

function InitializeUninstall(): Boolean;
var
  Keys, Captions, Hints: array of String;
  Shown, Defaults: array of Boolean;
  Boxes: array of TNewCheckBox;
  Form: TSetupForm;
  Title, Intro, HintText: TNewStaticText;
  OkButton, CancelButton: TNewButton;
  I, Y, W: Integer;
  App, Keep, Pulled, ModelsDir, OwnOllama, OwnUv: String;
begin
  Result := True;
  App := AppDirNoSlash();
  Pulled := RecordValue('pulled_models');
  StringChangeEx(Pulled, ',', ', ', True);
  ModelsDir := RecordValue('ollama_models_dir');
  OwnOllama := RecordValue('installed_ollama');
  OwnUv := RecordValue('installed_uv');

  SetArrayLength(Keys, PartCount);
  SetArrayLength(Captions, PartCount);
  SetArrayLength(Hints, PartCount);
  SetArrayLength(Shown, PartCount);
  SetArrayLength(Defaults, PartCount);

  Keys[0] := 'runtime';
  Captions[0] := 'Orion''s Python environment and tools';
  Hints[0] := FeatureSummary();
  Shown[0] := DirExists(App + '\runtime');
  Defaults[0] := True;

  Keys[1] := 'models';
  Captions[1] := 'AI models Orion downloaded';
  if (ModelsDir <> '') and DirExists(ModelsDir) then
    Hints[1] := 'Everything in ' + ModelsDir
  else
    Hints[1] := Pulled;
  Shown[1] := (Pulled <> '') or ((ModelsDir <> '') and DirExists(ModelsDir));
  Defaults[1] := True;

  Keys[2] := 'voice';
  Captions[2] := 'Speech recognition and voice models';
  Hints[2] := 'Whisper and Kokoro, about 500 MB';
  Shown[2] := DirExists(App + '\models\huggingface');
  Defaults[2] := True;

  Keys[3] := 'engine';
  Captions[3] := 'Ollama, the local AI engine';
  Hints[3] := 'Installed with Orion';
  Shown[3] := (OwnOllama <> '') and DirExists(OwnOllama);
  Defaults[3] := True;

  Keys[4] := 'node';
  Captions[4] := 'Node.js';
  Hints[4] := 'Private copy used by WhatsApp';
  Shown[4] := DirExists(App + '\tools\node');
  Defaults[4] := True;

  Keys[5] := 'uv';
  Captions[5] := 'uv, the Python package manager';
  Hints[5] := 'Installed with Orion';
  Shown[5] := (OwnUv <> '') and FileExists(OwnUv);
  Defaults[5] := True;

  Keys[6] := 'data';
  Captions[6] := 'Your settings, memories and conversations';
  Hints[6] := 'Also removes linked accounts (WhatsApp, email) and saved keys. Leave unticked to keep them for a reinstall.';
  Shown[6] := DirExists(ExpandConstant('{%USERPROFILE}') + '\.orion');
  Defaults[6] := False;

  UninstallParts := '';
  if UninstallSilent then
  begin
    Keep := CommandLineValue('/KEEP');
    for I := 0 to PartCount - 1 do
      if Shown[I] then
        if (Keys[I] = 'data') then
        begin
          if CommandLineValue('/REMOVEDATA') = '1' then
            UninstallParts := UninstallParts + Keys[I] + ',';
        end
        else if Defaults[I] and not ListHas(Keep, Keys[I]) then
          UninstallParts := UninstallParts + Keys[I] + ',';
    Exit;
  end;

  SetArrayLength(Boxes, PartCount);
  Form := CreateCustomForm(ScaleX(480), ScaleY(400), False, True);
  try
    Form.Caption := 'Uninstall Orion';

    Title := TNewStaticText.Create(Form);
    Title.Parent := Form;
    Title.Left := ScaleX(18);
    Title.Top := ScaleY(16);
    Title.Font.Style := [fsBold];
    Title.Caption := 'Choose what to remove with Orion';
    Y := Title.Top + Title.Height + ScaleY(8);

    Intro := TNewStaticText.Create(Form);
    Intro.Parent := Form;
    Intro.Left := ScaleX(18);
    Intro.Top := Y;
    Intro.Width := Form.ClientWidth - ScaleX(36);
    Intro.WordWrap := True;
    Intro.Caption := 'Ticked items are deleted. Anything that was on this PC before Orion, such as an Ollama or AI models you already had, is never removed.';
    Y := Y + Intro.Height + ScaleY(14);

    for I := 0 to PartCount - 1 do
      if Shown[I] then
      begin
        Boxes[I] := TNewCheckBox.Create(Form);
        Boxes[I].Parent := Form;
        Boxes[I].Left := ScaleX(18);
        Boxes[I].Top := Y;
        Boxes[I].Width := Form.ClientWidth - ScaleX(36);
        Boxes[I].Height := ScaleY(20);
        Boxes[I].Caption := Captions[I];
        Boxes[I].Checked := Defaults[I];
        Y := Y + ScaleY(20);
        if Hints[I] <> '' then
        begin
          HintText := TNewStaticText.Create(Form);
          HintText.Parent := Form;
          HintText.Left := ScaleX(38);
          HintText.Top := Y;
          HintText.Width := Form.ClientWidth - ScaleX(56);
          HintText.WordWrap := True;
          HintText.Font.Color := $707070;
          HintText.Caption := Hints[I];
          Y := Y + HintText.Height;
        end;
        Y := Y + ScaleY(10);
      end;

    Form.ClientHeight := Y + ScaleY(46);

    OkButton := TNewButton.Create(Form);
    OkButton.Parent := Form;
    OkButton.Caption := 'Uninstall';
    OkButton.ModalResult := mrOk;
    OkButton.Default := True;
    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.Caption := 'Cancel';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;
    W := Form.CalculateButtonWidth([OkButton.Caption, CancelButton.Caption]);
    OkButton.Width := W;
    CancelButton.Width := W;
    OkButton.Height := ScaleY(25);
    CancelButton.Height := ScaleY(25);
    CancelButton.Left := Form.ClientWidth - W - ScaleX(18);
    OkButton.Left := CancelButton.Left - W - ScaleX(8);
    OkButton.Top := Form.ClientHeight - ScaleY(25 + 14);
    CancelButton.Top := OkButton.Top;
    Form.ActiveControl := OkButton;

    if Form.ShowModal() <> mrOk then
    begin
      Result := False;
      Exit;
    end;
    for I := 0 to PartCount - 1 do
      if Shown[I] and Boxes[I].Checked then
        UninstallParts := UninstallParts + Keys[I] + ',';
  finally
    Form.Free();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App, Script: String;
  ResultCode: Integer;
begin
  App := AppDirNoSlash();
  if CurUninstallStep = usUninstall then
  begin
    Script := App + '\setup\orion-uninstall.ps1';
    if FileExists(Script) then
    begin
      UninstallProgressForm.StatusLabel.Caption := 'Removing what you selected...';
      Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
        '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '" -AppDir "' + App + '" -Remove "' + UninstallParts + 'none"',
        '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end
  else if CurUninstallStep = usPostUninstall then
    RemoveDir(App);
end;
