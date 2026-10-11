#!/bin/bash
# Reports Debian services, sessions, and kernels that require attention.
# Install directory: /usr/local/sbin/

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

RECIPIENT="${RECIPIENT:-}"
MAX_FAILURE_EMAIL_CHARS=12000
SCAN_TIMEOUT_SECONDS=300
TEST_NOTIFICATION=false

usage() {
    cat <<'EOF'
Usage: needrestart.sh [OPTION]

Options:
  -t, --test-notification  Send a synthetic notification without running a scan
  -h, --help               Show this help
EOF
}

if (($# > 1)); then
    echo "Error: expected at most one option." >&2
    usage >&2
    exit 2
fi

case "${1:-}" in
    "") ;;
    -t | --test-notification)
        TEST_NOTIFICATION=true
        ;;
    -h | --help)
        usage
        exit 0
        ;;
    *)
        echo "Error: unknown option '$1'." >&2
        usage >&2
        exit 2
        ;;
esac

send_email() {
    local subject="$1"
    local body="$2"
    if [[ ! -x /usr/sbin/sendmail ]]; then
        echo "Error: '/usr/sbin/sendmail' command not found or not executable. Cannot send email." >&2
        return 1
    fi
    if [[ -z "${ADMIN_EMAIL:-}" ]]; then
        echo "Error: ADMIN_EMAIL variable is not set. Cannot send email." >&2
        return 1
    fi
    printf "From: %s\nTo: %s\nSubject: %s\n\n%s\n" \
        "$ADMIN_EMAIL" "$RECIPIENT" "$subject" "$body" | /usr/sbin/sendmail -t
}

send_test_notification() {
    local timestamp
    local subject
    local body
    local recipient_domain
    local delivery_path

    timestamp=$(date --iso-8601=seconds 2>/dev/null || date)
    subject="[TEST] Needrestart notification on ${SYSTEM_ID}"
    recipient_domain="${RECIPIENT##*@}"
    recipient_domain="${recipient_domain,,}"
    if [[ "$RECIPIENT" == *@* && "$recipient_domain" == "mailrise.xyz" ]]; then
        delivery_path="needrestart.sh (${SYSTEM_ID}) -> sendmail -> msmtp -> Mailrise -> Apprise"
    elif [[ "$RECIPIENT" == *@* && -n "$recipient_domain" ]]; then
        delivery_path="needrestart.sh (${SYSTEM_ID}) -> sendmail -> msmtp -> Email host (${recipient_domain})"
    else
        delivery_path="needrestart.sh (${SYSTEM_ID}) -> sendmail -> msmtp -> Email host"
    fi
    printf -v body '%s\n\n%s\n\n%s\n%s\n\n%s\n%s\n%s\n\n%s\n%s\n\n%s\n%s' \
        "TEST NOTIFICATION - NO ACTION IS REQUIRED" \
        "This message verifies needrestart notification delivery from ${SYSTEM_ID}." \
        "Sample kernel status:" \
        "- Kernel update available; reboot recommended." \
        "Sample services:" \
        "- example.service" \
        "- snap.example.service" \
        "Sample user sessions:" \
        "- example-user" \
        "Timestamp: ${timestamp}" \
        "Delivery path: ${delivery_path}"

    if ! send_email "$subject" "$body"; then
        echo "Error: failed to deliver the test notification." >&2
        return 1
    fi

    echo "Test notification submitted successfully to ${RECIPIENT}."
}

report_failure() {
    local exit_status="$1"
    local subject="$2"
    local details="$3"
    local timestamp
    local report
    local email_report

    timestamp=$(date --iso-8601=seconds 2>/dev/null || date)
    printf -v report 'Timestamp: %s\nSystem: %s\n%s' "$timestamp" "${SYSTEM_ID:-<unknown_hostname>}" "$details"

    # Preserve the full report on stderr so cron captures a second reporting path.
    printf '%s\n' "$report" >&2

    if [[ -z "${RECIPIENT:-}" ]]; then
        echo "Direct notification skipped: RECIPIENT is not configured." >&2
        return "$exit_status"
    fi
    if [[ -z "${ADMIN_EMAIL:-}" ]]; then
        echo "Direct notification skipped: ADMIN_EMAIL is not configured." >&2
        return "$exit_status"
    fi
    if [[ ! -x /usr/sbin/sendmail ]]; then
        echo "Direct notification skipped: /usr/sbin/sendmail is missing or not executable." >&2
        return "$exit_status"
    fi

    email_report="$report"
    if ((${#email_report} > MAX_FAILURE_EMAIL_CHARS)); then
        email_report="${email_report:0:MAX_FAILURE_EMAIL_CHARS}"$'\n\n[Output truncated for direct email; cron output contains the complete report.]'
    fi

    if ! send_email "$subject" "$email_report"; then
        echo "Direct notification failed; cron output retains the complete report." >&2
    fi

    return "$exit_status"
}

trim() {
    local var="$1"
    var="${var#"${var%%[![:space:]]*}"}"
    var="${var%"${var##*[![:space:]]}"}"
    echo -n "$var"
}

array_contains() {
    local needle="$1"
    shift
    local item
    for item in "$@"; do
        [[ "$item" == "$needle" ]] && return 0
    done
    return 1
}

SYSTEM_ID=$(hostname -f 2>/dev/null || hostname 2>/dev/null || echo "<unknown_hostname>")
if [[ "$SYSTEM_ID" == "<unknown_hostname>" ]]; then
    report_failure 2 \
        "Configuration Error - hostname unavailable" \
        "Configuration error: could not determine the system hostname."
    exit $?
fi
echo "System identifier set to: $SYSTEM_ID"

ADMIN_EMAIL="root@${SYSTEM_ID}"
echo "Admin email set to: $ADMIN_EMAIL"

if [[ -z "$RECIPIENT" ]]; then
    report_failure 2 \
        "Configuration Error on ${SYSTEM_ID} - recipient missing" \
        "Configuration error: RECIPIENT must be configured before running this script."
    exit $?
fi

if [[ ! -x /usr/sbin/sendmail ]]; then
    report_failure 2 \
        "Configuration Error on ${SYSTEM_ID} - sendmail unavailable" \
        "Configuration error: /usr/sbin/sendmail is missing or not executable. Install and configure a sendmail-compatible local MTA."
    exit $?
fi

if [[ "$TEST_NOTIFICATION" == true ]]; then
    send_test_notification
    exit $?
fi

if [[ ! -x /usr/sbin/needrestart ]]; then
    report_failure 2 \
        "Configuration Error on ${SYSTEM_ID} - needrestart missing" \
        "Configuration error: /usr/sbin/needrestart is missing or not executable. Install it with 'apt install needrestart'."
    exit $?
fi

if [[ ! -x /usr/bin/timeout ]]; then
    report_failure 2 \
        "Configuration Error on ${SYSTEM_ID} - timeout unavailable" \
        "Configuration error: /usr/bin/timeout is missing or not executable. Install the Debian coreutils package."
    exit $?
fi

if ((EUID != 0)); then
    report_failure 2 \
        "Permission Error on ${SYSTEM_ID} - root required" \
        "Permission error: the needrestart scan must run as root."
    exit $?
fi

echo "Checking for services and sessions needing attention using needrestart..."

services_to_restart_arr=()
sessions_to_restart_arr=()
kernel_status_code=""

if needrestart_output=$(/usr/bin/timeout --signal=TERM --kill-after=30s "${SCAN_TIMEOUT_SECONDS}s" /usr/sbin/needrestart -bkl 2>&1); then
    :
else
    scan_status=$?
    scan_failure_summary="Needrestart scan failed."
    if [[ "$scan_status" -eq 124 || "$scan_status" -eq 137 ]]; then
        scan_failure_summary="Needrestart scan timed out after ${SCAN_TIMEOUT_SECONDS} seconds."
    fi
    scan_failure_report="${scan_failure_summary}
Command: /usr/bin/timeout --signal=TERM --kill-after=30s ${SCAN_TIMEOUT_SECONDS}s /usr/sbin/needrestart -bkl
Exit status: ${scan_status}
Output:
${needrestart_output}"
    report_failure "$scan_status" \
        "Needrestart Scan Failed on ${SYSTEM_ID}" \
        "$scan_failure_report"
    exit $?
fi

while IFS= read -r line; do
    if [[ "$line" == NEEDRESTART-SVC:* ]]; then
        service_name=$(trim "${line#NEEDRESTART-SVC:}")
        if [[ -n "$service_name" ]] && ! array_contains "$service_name" "${services_to_restart_arr[@]}"; then
            services_to_restart_arr+=("$service_name")
        fi
    elif [[ "$line" == NEEDRESTART-SESS:* ]]; then
        session_info=$(trim "${line#NEEDRESTART-SESS:}")
        if [[ -n "$session_info" ]] && ! array_contains "$session_info" "${sessions_to_restart_arr[@]}"; then
            sessions_to_restart_arr+=("$session_info")
        fi
    elif [[ "$line" == NEEDRESTART-KSTA:* ]]; then
        kernel_status_code=$(trim "${line#NEEDRESTART-KSTA:}")
    fi
done <<<"$needrestart_output"

email_body_parts=()
needs_notification=false
final_subject_prefix=""
kernel_status_message_for_console=""
kernel_status_message_for_email=""
services_need_restart_flag=false
sessions_need_attention_flag=false

if [[ -n "$kernel_status_code" ]]; then
    case "$kernel_status_code" in
        0)
            kernel_status_message_for_console="Kernel Status: Unknown or failed to detect. Manual check recommended."
            kernel_status_message_for_email="Kernel status on ${SYSTEM_ID}: Unknown or failed to detect."$'\n'"A manual check is recommended."
            final_subject_prefix="Kernel Status: Unknown"
            needs_notification=true
            ;;
        1)
            kernel_status_message_for_console="Kernel Status: No pending kernel upgrade."
            ;;
        2)
            kernel_status_message_for_console="Kernel status: ABI compatible kernel upgrade pending. Reboot recommended."
            kernel_status_message_for_email="Kernel status on ${SYSTEM_ID}: ABI compatible kernel upgrade pending."$'\n'"A reboot is recommended."
            final_subject_prefix="Kernel Update: Reboot Recommended"
            needs_notification=true
            ;;
        3)
            kernel_status_message_for_console="Kernel status: Kernel version upgrade pending. Reboot REQUIRED."
            kernel_status_message_for_email="Kernel Status on ${SYSTEM_ID}: Kernel version upgrade pending."$'\n'"A reboot is REQUIRED."
            final_subject_prefix="Kernel Update: Reboot REQUIRED"
            needs_notification=true
            ;;
        *)
            kernel_status_message_for_console="Kernel status: Received unexpected code '$kernel_status_code'. Manual check recommended."
            kernel_status_message_for_email="Kernel Status on ${SYSTEM_ID}: Received unexpected status code '$kernel_status_code'."$'\n'"Manual check recommended."
            final_subject_prefix="Kernel Status: Alert"
            needs_notification=true
            ;;
    esac
    [[ -n "$kernel_status_message_for_console" ]] && echo "$kernel_status_message_for_console" >&2
    [[ -n "$kernel_status_message_for_email" ]] && email_body_parts+=("$kernel_status_message_for_email")
fi

if [[ ${#services_to_restart_arr[@]} -gt 0 ]]; then
    services_need_restart_flag=true
    needs_notification=true
    echo "${#services_to_restart_arr[@]} services need restart." >&2
    services_message="Services Needing Restart on ${SYSTEM_ID}:"$'\n'
    services_message+="The following services need to be restarted:"$'\n'
    for service in "${services_to_restart_arr[@]}"; do
        services_message+="- ${service}"$'\n'
    done
    services_message+=$'\n'"Run 'sudo needrestart -r a' or 'sudo systemctl restart <service_name>' to restart them. For a clean system reboot, run 'sudo reboot'."
    email_body_parts+=("$services_message")
fi

if [[ ${#sessions_to_restart_arr[@]} -gt 0 ]]; then
    sessions_need_attention_flag=true
    needs_notification=true
    echo "${#sessions_to_restart_arr[@]} user sessions need attention." >&2
    sessions_message="User Sessions Needing Attention on ${SYSTEM_ID}:"$'\n'
    sessions_message+="The following user sessions may need to be restarted:"$'\n'
    for session in "${sessions_to_restart_arr[@]}"; do
        sessions_message+="- ${session}"$'\n'
    done
    sessions_message+=$'\n'"Users may need to log out and log back in for changes to take effect."
    email_body_parts+=("$sessions_message")
fi

final_email_body=""
if [[ "$needs_notification" == true && ${#email_body_parts[@]} -gt 0 ]]; then
    for i in "${!email_body_parts[@]}"; do
        final_email_body+="${email_body_parts[$i]}"
        if ((i < ${#email_body_parts[@]} - 1)); then
            final_email_body+=$'\n\n'
        fi
    done
fi

if [[ "$needs_notification" == true ]]; then
    current_subject=""
    if [[ -n "$final_subject_prefix" ]]; then
        current_subject="$final_subject_prefix on ${SYSTEM_ID}"
        if [[ "$services_need_restart_flag" == true && "$sessions_need_attention_flag" == true ]]; then
            current_subject+=" (plus services & sessions)"
        elif [[ "$services_need_restart_flag" == true ]]; then
            current_subject+=" (plus services)"
        elif [[ "$sessions_need_attention_flag" == true ]]; then
            current_subject+=" (plus sessions)"
        fi
    elif [[ "$services_need_restart_flag" == true && "$sessions_need_attention_flag" == true ]]; then
        current_subject="Services and User Sessions on ${SYSTEM_ID} require attention"
    elif [[ "$services_need_restart_flag" == true ]]; then
        current_subject="Services on ${SYSTEM_ID} need a restart"
    elif [[ "$sessions_need_attention_flag" == true ]]; then
        current_subject="User sessions on ${SYSTEM_ID} need attention"
    else
        current_subject="System Attention Needed on ${SYSTEM_ID}"
    fi

    [[ -z "$final_email_body" ]] && final_email_body="Automated check on ${SYSTEM_ID} indicates attention is needed. Please review system logs."
    [[ -z "$current_subject" ]] && current_subject="System Attention Needed on ${SYSTEM_ID}"

    if ! send_email "$current_subject" "$final_email_body"; then
        echo "Error: failed to deliver needrestart notification." >&2
        exit 1
    fi
else
    echo "No kernel issues, services, or user sessions require attention."
fi

exit 0
