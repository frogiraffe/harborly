Output docs/harborly-demo.gif

Set FontSize 18
Set Width 1200
Set Height 700
Set Padding 20
Set Theme "Catppuccin Mocha"
Set Framerate 20
Set PlaybackSpeed 1.5
Set Shell "bash"

Hide
Type "cd /tmp && clear"
Enter
Sleep 200ms
Show

Type "harborly search Mersin --country TR"
Sleep 300ms
Enter
Sleep 1s

Type "harborly near 36.8 34.6 --limit 3"
Sleep 300ms
Enter
Sleep 800ms

Type "harborly route TRMER GRPIR"
Sleep 300ms
Enter
Sleep 1s

Type "harborly route TRMER GRPIR --html-map /tmp/route.html"
Sleep 300ms
Enter
Sleep 1s

Type "harborly tui"
Sleep 300ms
Enter
Sleep 1s

Type "Mersin"
Sleep 400ms
Enter
Sleep 1.5s

Escape
Sleep 400ms

Type "+"
Sleep 500ms
Type "+"
Sleep 500ms
Type "-"
Sleep 500ms
Type "-"
Sleep 500ms
Type "-"
Sleep 500ms

Ctrl+C
Sleep 300ms
