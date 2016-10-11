#!/bin/sh

set -e

icon=
dotdir=
text_file=
title=

run () {
  mkdir -p -m700 "${dotdir}"
  touch "${dotdir}/confirmed-binary-only"
  exec "$@"
  exit 70   # EX_SOFTWARE
}

try_zenity () {
  if ! command -v zenity >/dev/null; then
    return 1
  fi

  e=0
  zenity --text-info --filename="$text_file" --title="$title" \
    --checkbox="I'll be careful" --ok-label="Run" \
    --window-icon="${icon}" \
    --width=500 --height=400 || e=$?
  case "$e" in
    (0)
      run "$@"
      ;;
    (*)
      exit 77   # EX_NOPERM
      ;;
  esac
}

try_kdialog () {
  if ! command -v kdialog >/dev/null; then
    return 1
  fi

  e=0
  kdialog --title "$TITLE" --warningcontinuecancel "$(cat "$text_file")" || \
    e=$?
  case "$e" in
    (0)
      run "$@"
      ;;
    (*)
      exit 77   # EX_NOPERM
      ;;
  esac
}

try_xmessage () {
  if ! command -v xmessage >/dev/null; then
    return 1
  fi

  e=0
  xmessage -buttons Run:100,Cancel:101 -nearmouse -file "$text_file" || e=$?
  case "$e" in
    (100)
      run "$@"
      ;;
    (*)
      exit 77   # EX_NOPERM
      ;;
  esac
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    (--dotdir)
      dotdir="$2"
      shift 2
      ;;

    (--icon)
      icon="$2"
      shift 2
      ;;

    (--title)
      title="$2"
      shift 2
      ;;

    (--text-file)
      text_file="$2"
      shift 2
      ;;

    (--)
      shift
      ;;

    (*)
      break
      ;;
  esac
done

if [ -z "$icon" ] || [ -z "$dotdir" ] || [ -z "$text_file" ] || \
    [ -z "$title" ]; then
  echo "$0: usage error: missing parameter" >&2
  exit 2
fi

if [ -e "${dotdir}/confirmed-binary-only" ]; then
  run "$@"
fi

case $(echo "$DESKTOP_SESSION" | tr A-Z a-z) in
  (kde)
    pref=try_kdialog
    ;;
  (gnome)
    pref=try_zenity
    ;;
  # easter egg for testing
  (1990slinuxuser)
    pref=try_xmessage
    ;;
  (*)
    pref=false
    ;;
esac

$pref "$@" || try_zenity "$@" || try_kdialog "$@" || try_xmessage "$@"

exit 72   # EX_OSFILE

# vim:set et sts=2 sw=2:
