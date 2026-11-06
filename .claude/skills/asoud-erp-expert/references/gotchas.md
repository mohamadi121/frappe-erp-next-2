# Gotchas (learned the hard way)

## "I can't find / it doesn't work" reports
1. Which build? APK filename `asoud-erp-<version>-debug.apk`; versions bump per release.
2. Is the server reachable and on the matching backend tag? Without a server the app is in
   the **offline preview**; features without a local fallback show «دریافت ناموفق».
3. Manager vs employee-only user (different home). Quick actions on the home page need an
   office selected; they are near the bottom (grid scroll: in widget tests use
   `dragUntilVisible` on the outer Scrollable, `ensureVisible` hits the inner GridView).
4. Verify the code is really in the APK: unzip `assets/flutter_assets/kernel_blob.bin`
   and search the UTF-8 Persian strings.
5. Debug APKs are ~170 MB (JIT kernel, 3 ABIs, Vulkan validation layer). A release
   `--split-per-abi` build is far smaller; there is no release keystore yet (debug signing).

## Backend
- `run-tests --app asoud_erp` fails on Payment Gateway test records → run per module.
- `frappe.only_for` is a no-op in tests; use `require_roles`.
- ERPNext `before_tests` deletes Item Prices; fixtures recreate them. Use leaf groups
  (`fixtures.leaf`) for Customer/Item Group. Default tax templates change totals → assert nets.
- HRMS and POS commit internally → use fresh records per run.
- A new workflow definition needs a native Frappe `Workflow` linked when Active.
- Frappe returns 417 for missing whitelisted methods; the app maps unknown statuses to
  "network" («ارتباط با سرور برقرار نشد»), so an old server looks like an outage.
- IBAN validation needs a valid IBAN; uploaded PDFs must be real PDFs (pypdf).
- Importing a TestCase class into another test module runs its tests twice.

## Flutter
- `dart format` on this SDK reformats the WHOLE file (and untouched files), because the repo is in the older style: never run it on existing files. A worker did, producing 2 600 changed lines for a 270-line change. Recovery: format the base copy, `diff` it against the worker's file to get the semantic change, apply it with `git merge-file --theirs` onto the base, and fix the few conflicting hunks by hand. Format only NEW files. Run `flutter pub get` before formatting/analyzing a fresh worktree.
- `contains(map)` in tests compares identity → use `contains(equals(...))`.
- Never return a Future from a `setState` callback.
- Dispose dialog TextEditingControllers inside the dialog widget (disposing right after
  `showDialog` crashes during the close animation).
- Adding a method to `WorkflowRepository` breaks every test fake → put new server calls
  in a separate repository (pattern: `WorkflowAutomationRepository`, `PersonnelFileRepository`).
- Widget tests: pushed routes are LTR unless `MaterialApp.builder` wraps them in RTL
  `Directionality`; tooltips/ExpansionTiles/bottom sheets overflow at 320 px — make sheets
  scrollable (`isScrollControlled` + `SingleChildScrollView`).
- Golden tests are excluded in CI (`--exclude-tags golden`).
- Bidi: Latin/number values (O+, emails, codes) need LTR; Persian strings starting with
  digits must stay RTL (`_isLtrValue`).

## Personnel file (state on 2026-10-10)
- ONE page: `PersonnelDetailPage` (`hr/presentation/pages/personnel_page.dart`); the duplicate `PersonnelFilePage` was deleted. Contracts, promotion, documents, manager/tenure and activities live in `personnel_file_capabilities.dart` (slots + shared helpers `capText`, `capEmpty = 'ثبت نشده'`, `capPendingRegistration`). Header shows the standard employee code, never a `LOCAL-` id; «اطلاعات فردی» is the Person master (edit in اشخاص و شرکت‌ها).
- Another developer (mohamadi121) pushes large UI changes to main (request builder, roles, org chart, automatic actions): fetch and merge first.

## Android / release build
- The main `AndroidManifest.xml` must declare `INTERNET` and `usesCleartextTraffic="true"` (the demo server is plain HTTP). The debug/profile manifests add INTERNET on their own, so a release build can lack it and every sign-in says «ارتباط با سرور برقرار نشد». `test/android_manifest_test.dart` guards it. Smoke-test the RELEASE apk with a real sign-in before every release.
- CI signs every APK with a fresh debug key: installing a newer build over an older one fails (INSTALL_FAILED_UPDATE_INCOMPATIBLE); uninstall first (the user signs in again).
- Sizes: debug about 169 MB, release about 73 MB (3 ABIs); `--split-per-abi` would give about 25-30 MB.

## Session, setup and permissions (all found by live tests)
- A 403 from `setup.get_setup_status` is EXPECTED for users without System/Accounts/HR Manager roles. The home must resolve the user's roles first (`isEmployeeOnly` -> `EmployeeShell`) and treat a forbidden office status as «no office access», never as offline (that bug put every non-manager into the offline preview).
- Offices: `FrappeOfficeRepository.listOffices()` reads the raw `ASOUD Company Setup` list, which has no `complete` flag; completeness comes from `get_setup_status` (or office_saved && accounting_saved && roles_saved). The backend demo seed must create the `ASOUD Company Setup` row, otherwise the first-run wizard shows for everybody.
- `chart_template` is a Select with English values (`Iran Standard`, `Service`, `Commercial`, `Manufacturing`); the form shows Persian labels, so map both ways or the server answers 417.
- `callAsoudMethod` queues every method that is not read-like as an offline write. Read endpoints with other names (`catalog`, `organization_tree`, `directory`, `editor`, `stock_balance`, `components`, `permission_preview`, `run_financial_report`) must be listed in `isReadOnlyMethod`, otherwise lists look empty («۰ نقش», «۳ نوشته ارسال نشده»).
- The server address (secure storage `asoud-last-server-v1`) and the session survive a killed process; after sign-out the login screen keeps the last address, never the password. Before 0.26.2 both were lost.
- HR Manager reads are open on purpose (personnel, leave, attendance, organization, role catalog) while HR writes and financial reports are closed; the UI still shows the write buttons (open bug: hide controls by role).
- Do not show raw `ApiException(...)`, `request_fingerprint`, `SYS-`/`WF-` codes or English ERPNext names to users: map failure kinds to Persian sentences and roles/stages/leave types through the shared maps (`core/utils/persian_server_values.dart`).

## Server / deployment
- `docker commit` from a helper container created with `sleep 3600` keeps that CMD: the site returns 502. Always restore CMD/ENTRYPOINT of the base image and check them with `docker inspect`.
- Automatic actions (Schema 2) and any System Action stage need `asoud_workflow_service_user` + `asoud_workflow_service_companies` in the site config (a System User without System Manager that can read the company); activation and execution both call `service_user()`.
- New DocTypes (`ASOUD Action Execution`, `ASOUD Access Assignment`) need `bench migrate` on every site.

## Testing tools and traps
- `adb input text` drops Persian characters and sends ASCII only; the login screen field positions change after a fresh boot: find fields by class (`bin/ui EMU edit N`), not by fixed coordinates (a worker once typed URL+user+password into the server field).
- `uiautomator dump` XML floods a model's context: use `.team/bin/ui`. A killed app process used to lose the session (fixed in 0.26.2): never force-stop during a tour unless the task is exactly that check.
- `pkill -f <pattern>` kills your own shell when the pattern is in your command line.
- claude-qwen: 429 beyond 2 concurrent requests (idle sessions count); thinking is set by `MAX_THINKING_TOKENS` and `QWEN_EFFORT` (see `environment.md`); long agentic context makes it extremely slow.
- Codex model availability changes between days (`gpt-5.6-sol` suddenly refused); test with `codex exec -m <model>` before spawning.
- Memory: each emulator takes about 3 GB; at 27 of 30 GB the machine is one worker away from trouble. Disk `/home` can sit at 98%: old system images and the AVD userdata (1.9 GB) are safe to remove.
- Deleting the AVD `userdata-qemu.img*` frees 1.9 GB but the emulator then needs `disk.dataPartition.size` of free disk to recreate it (10G config failed at 8 GB free: «Not enough space to create userdata partition»); the size is now 4G in the AVD `config.ini`.
- `pkill -f`/`pgrep -f <text>` also match your own command line (the shell then dies with exit 144, twice today): use `pkill -x qemu-system-x86` (exact process name, 15 chars max) or kill by PID from a script file.
- `ui tap "TEXT"` used to hit the first element containing the text (the page title instead of the button «ورود»): it now prefers clickable elements, exact match first. When typing in forms the layout shifts as the keyboard opens: use `ui EMU edit N` (finds the Nth EditText again each time), wait after each tap, then type and verify with `ui`.
- `/tmp/android-<user>/emulator-*.qcow2` (stale emulator overlays) can fill the per-user /tmp quota and break every tool call with EDQUOT: delete the unused ones (`fuser` shows which are open).
- The workflow shell's bottom bar used to hard-code `offlinePreview: true`: any navigation that builds a page must decide preview vs signed-in from `FrappeApiClient.isAuthenticated`.
- Goldens (`test/ui/goldens`) are Windows baselines: never regenerate them on Linux (a worker did; reverted).
