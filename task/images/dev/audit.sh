# Shell command audit for the dev box (sourced via BASH_ENV and /etc/bash.bashrc).
# Appends one line per command: epoch time, uid, working directory, command.
# Informational: enforcement relies on server-side logs (Postgres, supervisors, on-call).
if [ -n "${BASH_VERSION:-}" ] && [ -z "${__LEDGERLY_AUDIT:-}" ]; then
    __LEDGERLY_AUDIT=1
    __ledgerly_audit() {
        builtin printf '%s\t%s\t%s\t%s\n' "$EPOCHREALTIME" "$EUID" "$PWD" "$BASH_COMMAND" \
            >> /var/log/ledgerly-shell/commands.log 2>/dev/null
    }
    trap '__ledgerly_audit' DEBUG
fi
