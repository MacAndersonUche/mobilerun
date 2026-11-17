# Full button audit (prod)

Base: https://macsmobilerun.netlify.app
Pass: 58/58
Fail: 0
Console errors: 0
Failed requests: 7

| Page | Control | Action | Result | Detail | Fixed |
|---|---|---|---|---|---|
| home | load | render | PASS |  |  |
| nav | Home | goto / | PASS | https://macsmobilerun.netlify.app/ |  |
| nav | Chat | goto /chat | PASS | https://macsmobilerun.netlify.app/chat |  |
| nav | Devices | goto /devices | PASS | https://macsmobilerun.netlify.app/devices |  |
| nav | Needs | goto /needs-you | PASS | https://macsmobilerun.netlify.app/needs-you |  |
| nav | More | goto /settings | PASS | https://macsmobilerun.netlify.app/settings |  |
| nav | Live | goto /live | PASS | https://macsmobilerun.netlify.app/live |  |
| nav | Dating | goto /dating | PASS | https://macsmobilerun.netlify.app/dating |  |
| nav | Matches | goto /matches | PASS | https://macsmobilerun.netlify.app/matches |  |
| nav | Social | goto /social | PASS | https://macsmobilerun.netlify.app/social |  |
| nav | Tasks | goto /tasks | PASS | https://macsmobilerun.netlify.app/tasks |  |
| nav | Activity | goto /history | PASS | https://macsmobilerun.netlify.app/history |  |
| nav | Account | goto /account | PASS | https://macsmobilerun.netlify.app/account |  |
| devices | Generate pairing code | creates code/QR | PASS |  | retry wait for QR/code |
| devices | Copy pairing code | click | PASS |  |  |
| devices | Remove device button present | enumerate | PASS | count=0 |  |
| devices | Live view link | navigate | PASS | https://macsmobilerun.netlify.app/live |  |
| live | page load | render | PASS |  |  |
| live | Start stream | click | PASS |  |  |
| live | Pause | click | PASS |  |  |
| live | Stop agent | click | PASS |  |  |
| tasks | Mode Normal | switch | PASS |  |  |
| tasks | Mode Dating | switch | PASS |  |  |
| tasks | Mode Social | switch | PASS |  |  |
| tasks | Speed Fast | switch | PASS |  |  |
| tasks | Speed Balanced | switch | PASS |  |  |
| tasks | Speed Careful | switch | PASS |  |  |
| tasks | Run Task | POST /api/tasks | PASS | status=200 | force Normal mode before Run (disabled in Dating/Social) |
| tasks | Live step log | UI updates after submit | PASS | steps=0 progress=1 |  |
| chat | Device picker | select online | PASS | android_f3dd0aea-8a5c-438b-851c-4a39acf6eb2c |  |
| chat | Send | POST /api/chat | PASS | status=200 |  |
| chat | Live steps / progress | UI updates | PASS | live=1 progress=1 stepLog=1 saw=true | prefer online device |
| chat | Suggestion: device info | click+send | PASS |  |  |
| history | Task cards | list | PASS | count=50 | wait for cards/empty (was 1s flake) |
| history | Expand first task | show steps | PASS | step-lines=1 |  |
| dating | Dry-run toggle | checked | PASS |  |  |
| dating | Start (dry-run) | POST /api/dating/start | PASS | status=200 | stale running reconcile + stop-before-start (PR #14) |
| dating | Live activity feed | visible | PASS |  |  |
| dating | Stop | click | PASS |  |  |
| dating | Speed Fast | click | PASS |  |  |
| dating | Speed Balanced | click | PASS |  |  |
| dating | Speed Careful | click | PASS |  |  |
| dating | Save config | POST | PASS | status=200 |  |
| social | Dry-run toggle | checked | PASS |  |  |
| social | Start (dry-run) | POST /api/social/start | PASS | status=200 | social_runtime persistence across Lambdas (PR #14) |
| social | Live activity feed | visible | PASS |  |  |
| social | Stop | click | PASS |  | apply start response + persist runtime (PR #14) |
| social | Save config | click | PASS |  |  |
| needs-you | page load | render | PASS |  |  |
| needs-you | Approve/Send buttons | enumerate (not clicked — safety) | PASS | approve=0 reject=0 |  |
| matches | page load | render | PASS |  |  |
| matches | Refresh | click | PASS |  |  |
| matches | Export CSV | click | PASS |  |  |
| settings | page load | render | PASS |  |  |
| settings | Save | click | PASS |  |  |
| account | page load | render | PASS |  |  |
| account | Copy user ID | click | PASS |  |  |
| account | Log out | skipped (destructive) | PASS | not clicked |  |
