# Sigil bash bindings. Core behavior lives in the `sigil` executable.
#
# Bash cannot use zsh's `print -z` to inject text into the prompt buffer.
# Instead, selected proposals are displayed as a visual block in the next
# prompt (via PS1). The user can then:
#
#   ↑ up-arrow    recall from history (history -s)
#   Ctrl-X C      insert into buffer for review/edit (use)
#   Ctrl-X D      discard and start fresh
#
# The Ctrl-X , widget remains as a direct dispatch shortcut for users who
# prefer it.

if [[ -n "${SIGIL_BIN:-}" ]]; then
  __sigil_bin="$SIGIL_BIN"
elif command -v sigil >/dev/null 2>&1; then
  __sigil_bin="sigil"
else
  __sigil_bin="sigil"
fi

__sigil_muted=$'\e[38;2;110;106;134m'
__sigil_reset=$'\e[0m'
__sigil_last_failed_history=""

if [[ -z "${SIGIL_SESSION_ID:-}" ]]; then
  if command -v uuidgen >/dev/null 2>&1; then
    export SIGIL_SESSION_ID="$(uuidgen)"
  else
    __sigil_tty="${TTY:-tty}"
    export SIGIL_SESSION_ID="${__sigil_tty##*/}-$$"
  fi
fi

# Pending proposal state. When a command is selected via fzf, it is stored
# here and displayed in the next prompt instead of being printed to stdout.
__sigil_pending_command=""
__sigil_pending_prefix=""
__sigil_pending_show=0

# Preserve the original PS1 so we can restore it after pending display.
__sigil_saved_ps1=""

__sigil_history_insert() {
  [[ $- == *i* ]] || return 0
  [[ -n "${1:-}" ]] || return 0
  builtin history -s "$1" 2>/dev/null || true
}

__sigil_stdin_is_pipe() {
  [[ -p /dev/stdin ]]
}

# ── Pending proposal: show, accept, discard ──────────────────────────────

__sigil_show_pending() {
  local cmd="$1"
  local prefix="${2:-}"
  __sigil_pending_command="$cmd"
  __sigil_pending_prefix="$prefix"
  __sigil_pending_show=1
  __sigil_history_insert "$cmd"
}

__sigil_discard_pending() {
  __sigil_pending_command=""
  __sigil_pending_prefix=""
  __sigil_pending_show=0
  if [[ -n "$__sigil_saved_ps1" ]]; then
    PS1="$__sigil_saved_ps1"
    __sigil_saved_ps1=""
  fi
}

__sigil_use_pending() {
  if [[ $__sigil_pending_show -eq 1 && -n "$__sigil_pending_command" ]]; then
    READLINE_LINE="$__sigil_pending_command"
    READLINE_POINT=${#READLINE_LINE}
    __sigil_discard_pending
  fi
}

__sigil_prompt_setup() {
  if [[ $__sigil_pending_show -eq 1 && -n "$__sigil_pending_command" ]]; then
    local cmd="$__sigil_pending_command"
    local prefix="$__sigil_pending_prefix"
    local bar
    bar=$(printf '─%.0s' $(seq 1 $(( ${#cmd} + 4 ))))

    # Save original PS1 only once.
    if [[ -z "$__sigil_saved_ps1" ]]; then
      __sigil_saved_ps1="$PS1"
    fi

    # Escape any existing PS1 escape sequences so they survive in the
    # expanded string, then wrap with the pending block.
    local label=" "
    [[ -n "$prefix" ]] && label="$prefix"
    PS1="${__sigil_muted}${bar}\n${label} ${cmd}\n${bar}${__sigil_reset}\n"
  fi
}

# Readline callbacks for Ctrl-X C (use) and Ctrl-X D (discard).
__sigil_readline_use() {
  __sigil_use_pending
}

__sigil_readline_discard() {
  __sigil_discard_pending
}

# ── Command wrappers ─────────────────────────────────────────────────────

sigil_command() {
  if __sigil_stdin_is_pipe; then
    "$__sigil_bin" op "," "$@"
    return $?
  fi
  local selected
  selected="$("$__sigil_bin" command --select "$*")" || return $?
  if [[ -n "$selected" ]]; then
    __sigil_show_pending "$selected" "[model/propose]"
  fi
}

sigil_previous_command() {
  if __sigil_stdin_is_pipe; then
    "$__sigil_bin" op ",," "$@"
    return $?
  fi
  local selected
  selected="$("$__sigil_bin" command --previous --select)" || return $?
  if [[ -n "$selected" ]]; then
    __sigil_show_pending "$selected" "[model/propose]"
  fi
}

sigil_question() {
  if __sigil_stdin_is_pipe; then
    "$__sigil_bin" op "?" "$@"
    return $?
  fi
  "$__sigil_bin" question "$*"
}

sigil_follow_up() {
  if __sigil_stdin_is_pipe; then
    "$__sigil_bin" op "??" "$@"
    return $?
  fi
  "$__sigil_bin" question --follow-up "$*"
}

sigil_fix() {
  if __sigil_stdin_is_pipe; then
    "$__sigil_bin" op "^" "$@"
    return $?
  fi
  local selected
  selected="$("$__sigil_bin" fix)" || return $?
  if [[ -n "$selected" ]]; then
    __sigil_show_pending "$selected" "[model/propose]"
  fi
}

sigil_previous_fix() {
  if __sigil_stdin_is_pipe; then
    "$__sigil_bin" op "^^" "$@"
    return $?
  fi
  local selected
  selected="$("$__sigil_bin" fix --previous)" || return $?
  if [[ -n "$selected" ]]; then
    __sigil_show_pending "$selected" "[model/propose]"
  fi
}

sigil_summary() {
  "$__sigil_bin" summary "$*"
}

# ── Glyph functions ──────────────────────────────────────────────────────

function , { sigil_command "$*"; }
function ,, { sigil_previous_command "$*"; }
function ? { sigil_question "$*"; }
function ?? { sigil_follow_up "$*"; }
function ^ { sigil_fix "$*"; }
function ^^ { sigil_previous_fix "$*"; }
function @. { sigil_summary "$*"; }

if [[ $- == *i* ]]; then
  alias ,='sigil_command'
  alias ,,='sigil_previous_command'
  alias '?'='sigil_question'
  alias '??'='sigil_follow_up'
  alias '^'='sigil_fix'
  alias '^^'='sigil_previous_fix'
  alias '@.'='sigil_summary'
fi

# ── Readline glyph dispatch (Ctrl-X ,) ───────────────────────────────────

__sigil_trim_leading_spaces() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  printf '%s' "$value"
}

__sigil_block_readline() {
  printf '\n%s%s%s\n' "$__sigil_muted" "$1" "$__sigil_reset" >&2
  READLINE_LINE=""
  READLINE_POINT=0
}

__sigil_set_readline_buffer() {
  READLINE_LINE="${1:-}"
  READLINE_POINT=${#READLINE_LINE}
}

__sigil_readline_dispatch() {
  local b="${READLINE_LINE:-}"
  local rest selected

  if [[ "$b" == ,!* ]]; then
    __sigil_block_readline "> sigil ,! - blocked - bang requires sandbox"
    return 0
  elif [[ "$b" == ,,* ]]; then
    printf '\n' >&2
    selected="$("$__sigil_bin" command --previous --select)" || return $?
    __sigil_set_readline_buffer "$selected"
    return 0
  elif [[ "$b" == ,* ]]; then
    rest="${b#,}"
    rest="$(__sigil_trim_leading_spaces "$rest")"
    [[ -n "$rest" ]] || return 0
    printf '\n' >&2
    selected="$("$__sigil_bin" command --select "$rest")" || return $?
    __sigil_set_readline_buffer "$selected"
    return 0
  elif [[ "$b" == @.* ]]; then
    rest="${b#@.}"
    rest="$(__sigil_trim_leading_spaces "$rest")"
    printf '\n' >&2
    READLINE_LINE=""
    READLINE_POINT=0
    "$__sigil_bin" summary "$rest"
    return $?
  elif [[ "$b" == @!* || "$b" == @* ]]; then
    __sigil_block_readline "> sigil @ - blocked - no promotion mutation"
    return 0
  elif [[ "$b" == ^^* ]]; then
    printf '\n' >&2
    selected="$("$__sigil_bin" fix --previous)" || return $?
    __sigil_set_readline_buffer "$selected"
    return 0
  elif [[ "$b" == ^* ]]; then
    printf '\n' >&2
    selected="$("$__sigil_bin" fix)" || return $?
    __sigil_set_readline_buffer "$selected"
    return 0
  elif [[ "$b" == \?!* ]]; then
    __sigil_block_readline "> sigil ?! - blocked - no execute path"
    return 0
  elif [[ "$b" == \?\?* ]]; then
    rest="${b#??}"
    rest="$(__sigil_trim_leading_spaces "$rest")"
    [[ -n "$rest" ]] || return 0
    printf '\n' >&2
    READLINE_LINE=""
    READLINE_POINT=0
    "$__sigil_bin" question --follow-up "$rest"
    return $?
  elif [[ "$b" == \?* ]]; then
    rest="${b#?}"
    rest="$(__sigil_trim_leading_spaces "$rest")"
    [[ -n "$rest" ]] || return 0
    printf '\n' >&2
    READLINE_LINE=""
    READLINE_POINT=0
    "$__sigil_bin" question "$rest"
    return $?
  fi

  printf '\n%s%s%s\n' \
    "$__sigil_muted" \
    "> sigil readline - current buffer is not a Sigil glyph" \
    "$__sigil_reset" >&2
  return 0
}

# ── Failure recording ────────────────────────────────────────────────────

__sigil_history_line() {
  local line
  line="$(HISTTIMEFORMAT= builtin history 1 2>/dev/null)" || return 1
  if [[ "$line" =~ ^[[:space:]]*[0-9]+[[:space:]]+(.*)$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

__sigil_precmd() {
  local exit_status=$?
  local command
  local record_args

  command="$(__sigil_history_line)" || return "$exit_status"
  if [[ $exit_status -ne 0 && -n "$command" && "$command" != "$__sigil_last_failed_history" ]]; then
    case "$command" in
      ,*|\?*|\^*|@*|sigil\ *|__sigil_*) ;;
      *)
        record_args=(record-failure --status "$exit_status" --cwd "$PWD")
        [[ -n "${SIGIL_FAILURE_STDOUT:-}" ]] && record_args+=(--stdout-snippet "$SIGIL_FAILURE_STDOUT")
        [[ -n "${SIGIL_FAILURE_STDERR:-}" ]] && record_args+=(--stderr-snippet "$SIGIL_FAILURE_STDERR")
        "$__sigil_bin" "${record_args[@]}" "$command" >/dev/null 2>&1 || true
        __sigil_last_failed_history="$command"
        unset SIGIL_FAILURE_STDOUT SIGIL_FAILURE_STDERR
        ;;
    esac
  fi
  return "$exit_status"
}

# ── Installation ─────────────────────────────────────────────────────────

__sigil_install_prompt_command() {
  [[ $- == *i* ]] || return 0

  local prompt_decl
  prompt_decl="$(declare -p PROMPT_COMMAND 2>/dev/null || true)"
  case "$prompt_decl" in
    declare\ -a*|declare\ -ax*)
      local item
      for item in "${PROMPT_COMMAND[@]}"; do
        [[ "$item" == "__sigil_precmd" ]] && return 0
        [[ "$item" == "__sigil_prompt_setup" ]] && return 0
      done
      PROMPT_COMMAND=(__sigil_precmd __sigil_prompt_setup "${PROMPT_COMMAND[@]}")
      return 0
      ;;
  esac

  case ";${PROMPT_COMMAND:-};" in
    *";__sigil_precmd;"*) return 0 ;;
  esac
  if [[ -n "${PROMPT_COMMAND:-}" ]]; then
    PROMPT_COMMAND="__sigil_precmd; __sigil_prompt_setup; ${PROMPT_COMMAND}"
  else
    PROMPT_COMMAND="__sigil_precmd; __sigil_prompt_setup"
  fi
}

__sigil_install_readline_bindings() {
  [[ $- == *i* ]] || return 0
  bind -x '"\C-x,": __sigil_readline_dispatch' 2>/dev/null || true
  bind -x '"\C-x\C-c": __sigil_readline_use' 2>/dev/null || true
  bind -x '"\C-x\C-d": __sigil_readline_discard' 2>/dev/null || true
}

__sigil_install_prompt_command
__sigil_install_readline_bindings
