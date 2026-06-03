Output docs/demos/gifs/10-lazygit-review.gif

Require zsh
Require python3
Require git
Require lazygit

Set Shell "zsh"
Set FontSize 18
Set FontFamily "Berkeley Mono"
Set Width 1280
Set Height 760
Set Padding 28
Set Theme "Rose Pine"
Set TypingSpeed 22ms
Set Framerate 18
Set PlaybackSpeed 1.05
Set WindowBar Colorful

Hide
Type "export PS1='$ '"
Enter
Type "source docs/demos/setup.zsh 10-lazygit-review"
Enter
Type "clear"
Enter
Show

Type ",,, fix the failing parser test by updating the smallest relevant code path"
Enter
Sleep 1400ms
Type "y"
Enter
Sleep 3600ms
Type "lazygit"
Enter
Sleep 4500ms
Type "q"
Sleep 700ms
Type "git status --short"
Enter
Sleep 900ms
Type "git add src/parser.py tests/test_parser.py"
Enter
Sleep 800ms
Type "git commit -m 'parser: keep numbers as integers'"
Enter
Sleep 1400ms
Type "git show --stat --oneline HEAD"
Enter
Sleep 1200ms
Type ", review the committed changes for risk"
Enter
Sleep 2600ms
