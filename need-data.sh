#!/bin/sh

TITLE="Quake III Arena"
TEXT="`cat "$1"`"

# This is basically the code/sys/sys_unix.c implementation of Sys_Dialog,
# redone in shell.

try_zenity () {
  if command -v zenity >/dev/null; then
    zenity --error --text="$TEXT" --title="$TITLE"
    return 0
  else
    return 1
  fi
}

try_kdialog () {
  if command -v kdialog >/dev/null; then
    kdialog --error --text="$TEXT" --title="$TITLE"
    return 0
  else
    return 1
  fi
}

try_xmessage () {
  if command -v xmessage >/dev/null; then
    xmessage -center -buttons OK "$TEXT"
    return 0
  else
    return 1
  fi
}

case $(echo "$DESKTOP_SESSION" | tr A-Z a-z) in
  (kde)
    pref=try_kdialog
    ;;
  (gnome)
    pref=try_zenity
    ;;
  (*)
    pref=false
    ;;
esac

$pref || try_zenity || try_kdialog || try_xmessage

printf "%s\n" "$TEXT"
exit 72         # EX_OSFILE
