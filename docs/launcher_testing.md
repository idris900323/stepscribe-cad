# Testing the desktop launcher (for the user)

The automated tests cover the files the launcher writes, the single-instance check, Quit, the idle
exit and the console-close handler. They cannot double-click an icon or watch Task Manager, so
**you** need to run this once on Windows (and once on macOS or Linux if you use them). It takes
about ten minutes.

## 1. Create the icon

```text
python -m stepscribe shortcut
```

It prints the paths it created. On Windows you should see `stepscribe.lnk` on the Desktop (with the
blue icon) and `%LOCALAPPDATA%\stepscribe\stepscribe.bat`.

## 2. Open it

1. Double-click the icon. A console window titled "stepscribe" opens, then your browser shows the page.
2. Double-click the icon again. The same page opens; no second console window stays open.
3. Drop a small STEP file (for example `robot_steps/SO-ARM100/STS3215_03a.step`) on the page and
   wait for the results. Answer one question in "Ask me questions".

## 3. Close it: three ways (do each one in turn, starting the icon again each time)

- **Quit:** press "Quit stepscribe" in the page header and confirm. The page says it has stopped,
  the console window closes.
- **Forget the tab:** close the browser tab and wait. After 10 minutes without a page (use
  `python -m stepscribe ui --idle-exit-min 1` to test faster) the console window closes by itself.
  While an analysis is running it must stay open.
- **Close the window:** click the X of the console window while an analysis is running.

## 4. Look for leftovers

After each way of closing:

- Windows: open Task Manager, Details tab, sort by name. There must be **no** `python.exe` left
  that was started by the icon. Also check that `%TEMP%\stepscribe_ui_*` folders from this run are gone.
- macOS / Linux: run `ps aux | grep stepscribe`. Nothing should be listed.
- Start the icon once more: it must start normally (no "already running" message).

## 5. Uninstall test

```text
python -m stepscribe shortcut --remove
```

The desktop icon and the `.bat` are gone. Create them again, then uninstall stepscribe
(`python -m pip uninstall stepscribe-cad`) and double-click the icon: the window must say that
stepscribe is no longer installed, show the reinstall command and wait for a key press.

If anything differs from the above, please open an issue with what you saw (your Windows version, how
you closed the page, and what Task Manager showed).
