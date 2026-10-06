# Run the jobs each week

The jobs build the week that starts on the next Monday. Run them on Sunday
morning. Run `hcb whiteboard` first, then `hcb menu`.

Each run makes 1 model call through the `claude` program. The program must be
signed in as the user that runs the job. Run `claude` once by hand as that user
to sign in.

## Linux or a Raspberry Pi (cron)

Open the crontab with `crontab -e` and add 2 lines. Change the paths to your
checkout:

```
0 6 * * 0  cd /home/me/household-coordination-board && .venv/bin/hcb whiteboard >> state/hcb.log 2>&1
15 6 * * 0 cd /home/me/household-coordination-board && .venv/bin/hcb menu >> state/hcb.log 2>&1
```

cron uses the timezone of the system. Check it with `timedatectl`.

## macOS (launchd)

Save this as `~/Library/LaunchAgents/com.example.hcb.plist`. Change the paths,
then run `launchctl load ~/Library/LaunchAgents/com.example.hcb.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.hcb</string>
  <key>WorkingDirectory</key><string>/Users/me/household-coordination-board</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string><string>-c</string>
    <string>.venv/bin/hcb whiteboard; .venv/bin/hcb menu</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>0</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/Users/me/household-coordination-board/state/hcb.log</string>
  <key>StandardErrorPath</key><string>/Users/me/household-coordination-board/state/hcb.log</string>
</dict>
</plist>
```

## Windows (Task Scheduler)

Run this in PowerShell. Change the path to your checkout:

```powershell
$dir = "C:\Users\me\household-coordination-board"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $dir `
  -Argument "-NoProfile -Command `".venv\Scripts\hcb whiteboard; .venv\Scripts\hcb menu`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 6am
Register-ScheduledTask -TaskName "Household board" -Action $action -Trigger $trigger
```

The computer must be on at that time. Select "Run task as soon as possible
after a scheduled start is missed" in the task settings to catch up.

## Rebuild the current week

When a calendar changes during the week, rebuild the week that is on the
board now:

```
hcb whiteboard --this-week
```
