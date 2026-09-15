# PKU Course Helper · 北大选课助手

[中文](README.md) | **English**

A Windows desktop helper for Peking University's course add/drop period. A single-page workspace brings together a short guide, live results, target courses, and account settings in a deep red and warm white interface.

> This is a derivative of [Aerisun/PKUAutoElective2026](https://github.com/Aerisun/PKUAutoElective2026), built on earlier generations of open-source work. **It is not an original implementation from scratch or an official Peking University application.** We thank the senior students and contributors who made it possible.

## Changes in this fork

![Single-page workspace with offline sample data](docs/images/workspace.png)

- One page in this order: quick guide → runtime status → target courses → account and settings; no sidebar.
- Major, elective, and minor UI categories. Major and elective both use the existing major (`bzx`) route; scheduling semantics are unchanged.
- Class number `00` is accepted, stored as numeric `0`, and matched equivalently.
- Visible failure reasons and next steps, separating authentication errors, unavailable identity entries, missing courses on a particular page, and school restrictions.
- Existing start/stop, confirmed restart after saving, fair scheduling, within-group ordering, drag sorting, mutual exclusion, delayed enrollment, logs, INI import/export, and sleep protection remain available.
- Obsolete Docker files, training code, screenshots, and old UI scripts are removed. The ONNX model, provenance, licenses, and offline fixtures are retained.

## Run a packaged build

The basic portable build requires **Windows 10/11 x64**, an existing **Microsoft Edge WebView2 Runtime**, and **.NET Framework 4.6.2+**. Python and Node.js are not required on the destination computer. Build locally as described below, download an Actions build artifact, or use a complete ZIP if one is available in Releases.

1. Extract the **entire ZIP** into a writable folder, such as `D:\PKUCourseHelper`.
2. Close the old application and double-click `PKUCourseHelper.exe`. Keep `_internal` and all adjacent files; do not copy just the EXE.
3. Enter your university authentication account and password. The desktop UI keeps the password only for the current session.
4. Add courses with the exact name, offering school, class number, and page number from the corresponding add/drop plan. Page numbers start at 1. `00` refers to the **class number**, not the full course identifier.
5. Choose **主修 (major)** or **选修 (elective)** for the major entry, and **辅修 (minor)** for the minor entry. Set priorities within the same entry/page. Optionally configure mutual exclusion or a remaining-seat threshold for delayed enrollment.
6. Save and start. Inspect the explanation below each status; expand the log for detail. Saving during a run offers an explicit restart or defers changes to the next run.
7. Keep the computer awake and connected. Closing the application stops the task. Confirm the final outcome in the university's enrolled-course list.

Configuration and logs live in `data/` beside the EXE. To migrate settings, close both programs and copy the old `data/` folder beside the new EXE. Never commit personal configuration, passwords, or logs, or include them in a shared ZIP.

### Interpreting errors

| Message | Meaning / next step |
| --- | --- |
| Account error / password error | Shown separately only when the school explicitly identifies the failing field. |
| Account or password error | The school did not distinguish the field. Verify both in the official website; the app does not guess. |
| Minor entry unavailable | The minor entry was not recognized. Use elective for ordinary electives. If the website exposes the minor entry, report a compatibility issue. |
| Major / elective / minor course not found | No match on the configured entry and page. Check the exact name, class, school, page, and add/drop plan. |
| Schedule / exam conflict, credit limit, etc. | Follow the school's feedback. The app never automatically drops an existing course. |
| Access restricted / selection agreement required | Resolve the issue as instructed and restart manually. |

Keep the default 6-second interval and 0.2 jitter unless you understand the consequences. No interval guarantees freedom from school limits, and successful enrollment is not guaranteed.

## Run from source

Install **Python 3.11 x64**, **Node.js 22**, and WebView2. In **Git Bash**:

```bash
git clone https://github.com/Echo-Nie/PKU-Course-Helper.git
cd PKU-Course-Helper
python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
python desktop.py
```

These commands install dependencies into your current Python. You may use a virtual environment, but it is not mandatory. The full desktop entry point is **`desktop.py`**. Rebuild the frontend and restart after UI edits; restart after Python edits. Existing EXEs are not updated by source edits.

### UI-only preview

After building the frontend, run `python desktop.py --preview` from the project root for an offline native preview, or `./PKUCourseHelper.exe --preview` after packaging. It uses an isolated temporary profile, never logs in or enrolls, and does not read your normal configuration.

For frontend development, use a browser preview:

```bash
cd frontend
npm ci
npm run dev
```

Open the printed local URL with `/?preview=1`, normally `http://127.0.0.1:5173/?preview=1`. It uses disposable mock data and never logs in or enrolls. Refreshing resets preview data. Add `&scenario=errors` for example failure states. Press `Ctrl+C` to stop the preview server.

## Build an EXE

From the project root in **Git Bash**:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/build_local.ps1
```

Or in **PowerShell**:

```powershell
.\tools\build_local.ps1
```

The script verifies Python 3.11 x64, creates project-local `.venv-build-tools` and `.venv-desktop` environments, installs locked dependencies, builds the UI, runs tests, packages the executable, and performs offline self-tests and archive checks. These are build environments, not requirements for end users.

The successful output includes:

```text
dist/portable/<build-id>/PKUCourseHelper-windows-x64-portable.zip
build/portable-<build-id>/dist/PKUCourseHelper/PKUCourseHelper.exe
```

Extract the ZIP completely before running. The basic package uses the system WebView2 runtime. See [release notes](docs/RELEASING.md) for packaging with a private WebView2 runtime. Offline tests do not contact the university or certify real enrollment.

## Structure

`desktop.py` is the entry point; `frontend/` holds the React UI; `autoelective/desktop/` implements configuration, scheduling, status, and Windows adapters; `autoelective/` retains protocol and compatibility code; `resources/model/` holds the ONNX model and provenance; `tests/` holds offline tests and fixtures; `packaging/` contains release tooling.

Personal `data/`, caches, virtual environments, and build artifacts are ignored by Git. Compatibility code still used by the runtime or regression suite is retained.

## References and acknowledgments

This repository starts with the current modified version, retaining the upstream MIT license and attribution. It is based on:

1. [Aerisun/PKUAutoElective2026](https://github.com/Aerisun/PKUAutoElective2026): the **direct upstream**, providing the Windows desktop, ONNX inference, and multi-identity/page scheduler.
2. [Hovennnnn/PKUAutoElective2023](https://github.com/Hovennnnn/PKUAutoElective2023): earlier adaptations and the CNN + GRU + CTC captcha model.
3. [zhongxinghong/PKUAutoElective](https://github.com/zhongxinghong/PKUAutoElective): the original enrollment workflow, school interfaces, mutual exclusion, and delayed enrollment rules.

Thank you to the senior students and all contributors. This fork focuses on the single-page UI, category presentation, feedback, and documentation; it does not claim the upstream work as original. See [model provenance](resources/model/README.md) and [LICENSE](LICENSE).
