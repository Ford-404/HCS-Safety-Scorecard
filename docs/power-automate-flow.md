# Power Automate flow: send the weekly email

The weekly script can't send through the new Outlook, so it hands the email to Power Automate
(`email.method: onedrive` in config.yaml):

```
PC: run_weekly.py ──► OneDrive - Hillwood\HCS Safety Report\Attachments\Safety Health Report ….xlsx
                  └─► OneDrive - Hillwood\HCS Safety Report\Outbox\message ….json   (to, cc, subject, html, attachment)
                                   │ OneDrive syncs
Cloud: flow "HCS Safety Report email" ── new file in /HCS Safety Report/Outbox ──► waits 2 min ──►
       reads the message ──► gets the workbook ──► Send an email (V2) from your mailbox
```

The recipients still come from `email.to` / `email.cc` in config.yaml. You don't edit the flow to change them.

## One-time setup (about 15 minutes)

**0. Create the folders.** Run the test once on the PC:
`.\.venv\Scripts\python.exe send_test_email.py`. It creates `HCS Safety Report\Outbox` and `\Attachments` in
your work OneDrive. That first message won't be sent, because the flow doesn't exist yet. Wait a minute for OneDrive to sync.

**1. Create the flow.** Go to <https://make.powerautomate.com> (sign in with your Hillwood account), then
**+ Create → Automated cloud flow**.
- Flow name: `HCS Safety Report email`
- Trigger: search **"When a file is created (properties only)"** and pick the **OneDrive for Business** one → **Create**.

**2. Trigger settings.** Click the trigger:
- **Folder:** click the folder icon → `HCS Safety Report` → `Outbox`. It should show `/HCS Safety Report/Outbox`.
- Include subfolders: **No**.

**3. Add a wait** so the workbook finishes syncing: **+** → search **Delay** (Schedule) → Count `2`, Unit `Minute`.

**4. Read the message file:** **+** → search **"Get file content"** → pick **OneDrive for Business – Get file content**.
- **File:** click in the box → the ⚡ dynamic content icon → **File identifier** (from the trigger).
- **Advanced parameters → Infer Content Type: No**. This is important: the next step expects raw file content.
- Keep the step's name **Get file content**.

**5. Turn it into fields:** **+** → search **Compose** (Data Operation).
- Rename the step (… menu → Rename) to exactly **Message**.
- **Inputs:** click in the box → the *fx* (expression) icon → paste this, then press Add/OK:
  ```
  json(base64ToString(body('Get_file_content')?['$content']))
  ```

**6. Get the workbook:** **+** → search **"Get file content using path"** → **OneDrive for Business**.
- **File Path:** *fx* → paste:
  ```
  concat('/HCS Safety Report/Attachments/', outputs('Message')?['attachment'])
  ```
- Keep the step's name **Get file content using path**.

**7. Send it:** **+** → search **"Send an email (V2)"** → **Office 365 Outlook**.
- **To:** *fx* → `outputs('Message')?['to']`
- **Subject:** *fx* → `outputs('Message')?['subject']`
- **Body:** switch the body editor to code view (the `</>` button), then *fx* → `outputs('Message')?['html']`
- **Advanced parameters → Attachments** → **Add new item**:
  - **Attachments Name – 1:** *fx* → `outputs('Message')?['attachment']`
  - **Attachments Content – 1:** ⚡ dynamic content → **File content** (from *Get file content using path*)
- Optional, only if you use `email.cc`: **CC:** *fx* → `outputs('Message')?['cc']`

**8. Save** (top right). Power Automate may ask you to sign in to the OneDrive for Business and Office 365 Outlook
connections. Use your Hillwood account.

## Test it

On the PC: `.\.venv\Scripts\python.exe send_test_email.py`. In about 3–5 minutes (OneDrive sync, then the
2-minute wait), the "[TEST] HCS Safety Health Report" email should arrive with the workbook attached.
To watch it: make.powerautomate.com → **My flows** → *HCS Safety Report email* → **Run history**.

## If a run fails

Open the run in Run history; the failed step is red.

| Failed step | Usually means | Fix |
|---|---|---|
| Message (Compose): "base64ToString… null" | Infer Content Type wasn't set to **No** in step 4 | Set it to No, save, run the test again |
| Message: "template language expression… Get_file_content" | The step in 4 was renamed | Rename it back to *Get file content* (or use the new name with spaces → underscores) |
| Get file content using path: 404 / not found | The workbook hadn't synced yet | Raise the Delay to 5 minutes. Check that OneDrive is running on the PC |
| Send an email (V2): body shows HTML code as text | Body wasn't in code view | Redo step 7's Body in code view |

The flow only reads those two folders and sends one email per message file. To stop emails, turn the
flow **Off** (My flows → … → Turn off) or set `email.enabled: false` in config.yaml.
Old files in `Outbox` and `Attachments` can be deleted at any time.
