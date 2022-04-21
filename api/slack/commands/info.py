from datetime import datetime, timedelta
from typing import Dict, Optional

from django.utils import timezone

from api.models import TranscriptionCheck
from api.slack import client
from api.slack.utils import dict_to_table, parse_user
from api.views.misc import Summary
from authentication.models import BlossomUser
from blossom.strings import translation

i18n = translation()


def info_cmd(channel: str, message: str) -> None:
    """Send info about a user to slack."""
    parsed_message = message.split()
    if len(parsed_message) == 1:
        # they just sent an empty info message, create a summary response
        data = Summary().generate_summary()
        client.chat_postMessage(
            channel=channel,
            text=i18n["slack"]["server_summary"].format("\n".join(dict_to_table(data))),
        )
        return

    elif len(parsed_message) == 2:
        user, username = parse_user(parsed_message[1])
        if user:
            msg = user_info_text(user)
        else:
            msg = i18n["slack"]["errors"]["unknown_username"].format(username=username)
    else:
        msg = i18n["slack"]["errors"]["too_many_params"]

    client.chat_postMessage(channel=channel, text=msg)


def user_info_text(user: BlossomUser) -> str:
    """Get the info message for the given user."""
    name_link = f"<https://reddit.com/u/{user.username}|u/{user.username}>"
    title = f"Info about *{name_link}*:"

    general = _format_info_section("General", user_general_info(user))
    transcription_quality = _format_info_section(
        "Transcription Quality", user_transcription_quality_info(user)
    )
    debug = _format_info_section("Debug Info", user_debug_info(user))

    return f"{title}\n\n{general}\n\n{transcription_quality}\n\n{debug}"


def _format_info_section(name: str, section: Dict) -> str:
    """Format a given info section to a readable string.

    Example:
    *Section name*:
    - Key 1: Value 1
    - Key 2: Value 2
    """
    section_items = "\n".join([f"- {key}: {value}" for key, value in section.items()])

    return f"*{name}*:\n{section_items}"


def user_general_info(user: BlossomUser) -> Dict:
    """Get general info for the given user."""
    total_gamma = user.gamma
    recent_gamma = user.gamma_at_time(start_time=timezone.now() - timedelta(weeks=2))
    gamma = f"{total_gamma} Γ ({recent_gamma} Γ in last 2 weeks)"
    joined_on = _format_time(user.date_joined)
    last_active = _format_time(user.date_last_active()) or "Never"

    return {
        "Gamma": gamma,
        "Joined on": joined_on,
        "Last active": last_active,
    }


def user_transcription_quality_info(user: BlossomUser) -> Dict:
    """Get info about the transcription quality of the given user."""
    gamma = user.gamma
    check_status = TranscriptionCheck.TranscriptionCheckStatus

    # The checks for the given user
    user_checks = TranscriptionCheck.objects.filter(transcription__author=user)
    check_count = user_checks.count()
    check_ratio = check_count / gamma if gamma > 0 else 0
    checks = f"{check_count} ({check_ratio:.1%} of transcriptions)"

    # The comments for the given user
    user_comments_pending = user_checks.filter(status=check_status.COMMENT_PENDING)
    user_comments_resolved = user_checks.filter(status=check_status.COMMENT_RESOLVED)
    user_comments_unfixed = user_checks.filter(status=check_status.COMMENT_UNFIXED)
    comments_count = (
        user_comments_pending.count()
        + user_comments_resolved.count()
        + user_comments_unfixed.count()
    )
    comments_ratio = comments_count / check_count if check_count > 0 else 0
    comments = f"{comments_count} ({comments_ratio:.1%} of checks)"

    # The warnings for the given user
    user_warnings_pending = user_checks.filter(status=check_status.WARNING_PENDING)
    user_warnings_resolved = user_checks.filter(status=check_status.WARNING_RESOLVED)
    user_warnings_unfixed = user_checks.filter(status=check_status.WARNING_UNFIXED)
    warnings_count = (
        user_warnings_pending.count()
        + user_warnings_resolved.count()
        + user_warnings_unfixed.count()
    )
    warnings_ratio = warnings_count / check_count if check_count > 0 else 0
    warnings = f"{warnings_count} ({warnings_ratio:.1%} of checks)"

    # Watch status
    watch_status = user.transcription_check_reason(ignore_low_activity=True)

    return {
        "Checks": checks,
        "Warnings": warnings,
        "Comments": comments,
        "Watch status": watch_status,
    }


def user_debug_info(user: BlossomUser) -> Dict:
    """Get debug info about the given user."""
    user_id = f"`{user.id}`"
    blacklisted = bool_str(user.blacklisted)
    bot = bool_str(user.is_bot)
    accepted_coc = bool_str(user.accepted_coc)

    return {
        "ID": user_id,
        "Blacklisted": blacklisted,
        "Bot": bot,
        "Accepted CoC": accepted_coc,
    }


def bool_str(bl: bool) -> str:
    """Convert a bool to a Yes/No string."""
    return "Yes" if bl else "No"


def _format_time(time: Optional[datetime]) -> Optional[str]:
    """Format the given time in absolute and relative strings."""
    if time is None:
        return None

    now = timezone.now()
    absolute = time.date().isoformat()

    relative_delta = now - time
    relative = _relative_duration(relative_delta)

    if now >= time:
        return f"{absolute} ({relative} ago)"
    else:
        return f"{absolute} (in {relative})"


def _relative_duration(delta: timedelta) -> str:
    """Format the delta into a relative time string."""
    seconds = abs(delta.total_seconds())
    minutes = seconds / 60
    hours = minutes / 60
    days = hours / 24
    weeks = days / 7
    months = days / 30
    years = days / 365

    # Determine major time unit
    if years >= 1:
        value, unit = years, "year"
    elif months >= 1:
        value, unit = months, "month"
    elif weeks >= 1:
        value, unit = weeks, "week"
    elif days >= 1:
        value, unit = days, "day"
    elif hours >= 1:
        value, unit = hours, "hour"
    elif minutes >= 1:
        value, unit = minutes, "min"
    elif seconds > 5:
        value, unit = seconds, "sec"
    else:
        duration_ms = seconds / 1000
        value, unit = duration_ms, "ms"

    if unit == "ms":
        duration_str = f"{value:0.0f} ms"
    else:
        # Add plural s if necessary
        if value != 1:
            unit += "s"

        duration_str = f"{value:.1f} {unit}"

    return duration_str
