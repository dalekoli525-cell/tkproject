# Client

The rewritten desktop client will only manage:

- login
- proxy browser environments
- TikTok accounts
- collection task creation
- task logs and result lookup

ADS, DM outreach, CRM dashboards, and campaign modules are intentionally not
part of the new client baseline.

## Entrypoints

Start the production desktop client with:

```powershell
.\.venv\Scripts\python.exe SCRIPTS\Run_Client.py
```

Run the production-style local validation with:

```powershell
.\.venv\Scripts\python.exe SCRIPTS\Validate_Production.py
```

`SCRIPTS\Run_Test_Window.py` is kept only as a legacy smoke-check wrapper.

## Module Boundaries

- `Client_Window.py`: PyQt window, page rendering, button events, and user feedback.
- `Client_App.py`: production Qt application bootstrap.
- `Ui_Style.py`: client stylesheet only.
- `Client_Domain.py`: pure parsing and normalization helpers with no Qt imports.
- `Client_State_Service.py`: user-scoped local state files for environments, tasks, tags, and proxy nodes.
- `Profile_State_Service.py`: isolated Playwright profile markers, cookie retention, and safe profile backup on account changes.
- `Environment_Process_Manager.py`: process lookup, orphan cleanup, and process tree termination.
- `Environment_Launcher.py`: Playwright Chromium launch request construction and proxy launch checks.
- `Task_Command_Service.py`: command-file protocol used by the local browser worker.
- `Local_Json_Store.py`: safe local JSON/JSONL read and write helpers.

Keep TikTok automation, collector behavior, server APIs, and AI filtering outside
the UI module. UI code should call these services instead of owning their state
protocols directly.
