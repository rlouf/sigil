Output docs/demos/gifs/02-git-diff-review.gif

Require zsh
Require python3
Require git

Set Shell "zsh"
Set FontSize 18
Set FontFamily "Berkeley Mono"
Set Width 1280
Set Height 720
Set Padding 28
Set Theme "Rose Pine"
Set TypingSpeed 22ms
Set Framerate 18
Set PlaybackSpeed 1.05
Set WindowBar Colorful

Hide
Type "export PS1='$ '"
Enter
Type "source docs/demos/setup.zsh 02-git-diff-review"
Enter
Type "sigil_demo_make_parser_change"
Enter
Type "clear"
Enter
Show

Type "git diff"
Enter
Sleep 1200ms
Type ", review the risky parser change"
Enter
Sleep 2600ms
Type ", what should I test first?"
Enter
Sleep 3200ms
