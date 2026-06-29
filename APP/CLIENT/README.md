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
