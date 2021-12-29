import binascii
import hashlib
import hmac
import os
import re
import time
from typing import Any, Dict, List, Optional
from unittest import mock

import requests
import slack
from django.conf import settings
from django.http import HttpRequest

from api.helpers import fire_and_forget
from api.models import Submission
from api.serializers import VolunteerSerializer
from api.views.misc import Summary
from app.reddit_actions import remove_post
from authentication.models import BlossomUser
from blossom.errors import ConfigurationError
from blossom.strings import translation

if settings.ENABLE_SLACK is True:
    try:
        client = slack.WebClient(token=os.environ["SLACK_API_KEY"])  # pragma: no cover
    except KeyError:
        raise ConfigurationError(
            "ENABLE_SLACK is set to True, but no API key was found. Set the"
            " SLACK_API_KEY environment variable or change ENABLE_SLACK to False."
        )
else:
    # this is to explicitly disable posting to Slack when doing local dev
    client = mock.Mock()

i18n = translation()

# find a link in the slack format, then strip out the text at the end.
# they're formatted like this: <https://example.com|Text!>
SLACK_TEXT_EXTRACTOR = re.compile(
    r"<(?:https?://)?[\w-]+(?:\.[\w-]+)+\.?(?::\d+)?(?:/\S*)?\|([^>]+)>"
)


def clean_links(text: str) -> str:
    """Strip link out of auto-generated slack fancy URLS and return the text only."""
    results = [_ for _ in re.finditer(SLACK_TEXT_EXTRACTOR, text)]
    # we'll replace things going backwards so that we don't mess up indexing
    results.reverse()

    for match in results:
        text = text[: match.start()] + match.groups()[0] + text[match.end() :]
    return text


def dict_to_table(dictionary: Dict, titles: List = None, width: int = None) -> List:
    """
    Take a dictionary and make it into a tab-separated table.

    Adapted from
    https://github.com/varadchoudhari/Neat-Dictionary/blob/master
    /src/Python%203/neat-dictionary-fixed-column-width.py
    """
    if not titles:
        titles = ["Key", "Value"]
    if not width:
        width = len(max(dictionary.keys(), key=len)) + 2

    return_list = []
    formatting = ""
    for i in range(0, len(titles)):
        formatting += "{:<" + str(width) + "}"
        formatting += " | "
    # trim off that last separator
    formatting = formatting[:-3]
    return_list.append(formatting.format(*titles))
    return_list.append(f"{'-' * width * len(titles)}")
    for key, value in dictionary.items():
        sv = []
        if isinstance(value, list):
            for subvalue in value:
                sv.append(str(subvalue))
        else:
            if value is None:
                value = "None"
            sv = [str(value)]
        return_list.append(formatting.format(key, ", ".join(sv)))
    return return_list


def send_help_message(channel: str, *args: Any) -> None:
    """Post a help message to slack."""
    client.chat_postMessage(channel=channel, text=i18n["slack"]["help_message"])


def send_github_sponsors_message(data: Dict, action: str) -> None:
    """
    Process the POST request from GitHub Sponsors.

    Every time someone performs an action on GitHub Sponsors, we'll get
    a POST request with the intent and some other information. This translates
    the GitHub call to something that Slack can understand, then forwards it
    to the #org_running channel.
    """
    emote = ":tada:"
    if action == "cancelled" or action == "pending_cancellation":
        emote = ":sob:"
    if (
        action == "edited"
        or action == "tier_changed"
        or action == "pending_tier_change"
    ):
        emote = ":rotating_light:"
    username = data["sponsorship"]["sponsor"]["login"]
    sponsorlevel = data["sponsorship"]["tier"]["name"]

    msg = i18n["slack"]["github_sponsor_update"].format(
        emote, action, username, sponsorlevel
    )
    client.chat_postMessage(channel="org_running", text=msg)


def process_submission_update(data: dict) -> None:
    """Remove the submission from both reddit and app if it needs to be removed."""
    # Blocks are created using the Slack Block Kit Builder
    # https://app.slack.com/block-kit-builder/
    value = data["actions"][0].get("value").split("_")
    blocks = data["message"]["blocks"]
    submission_obj = Submission.objects.get(id=int(value[2]))
    if value[0] == "keep":
        submission_obj.removed_from_queue = False
        submission_obj.save(skip_extras=True)
        blocks[-1] = {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Thank you! This submission has been kept.",
            },
        }
    else:
        # The submission was removed temporarily from the app queue when it was reported,
        # so we don't have to do anything else on the app side. Now that it's been
        # verified, go ahead and nuke it from Reddit's side as well.
        remove_post(submission_obj)
        blocks[-1] = {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"Submission ID {submission_obj.id} has been removed from the queue."
                ),
            },
        }

    client.chat_update(
        channel=data["channel"]["id"], ts=data["message"]["ts"], blocks=blocks
    )


def send_info(channel: str, message: str) -> None:
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
        if user := BlossomUser.objects.filter(
            username__iexact=parsed_message[1]
        ).first():
            v_data = VolunteerSerializer(user).data
            msg = i18n["slack"]["user_info"].format(
                user.username, "\n".join(dict_to_table(v_data))
            )
        else:
            msg = i18n["slack"]["errors"]["no_user_by_that_name"]
    else:
        msg = i18n["slack"]["errors"]["too_many_params"]

    client.chat_postMessage(channel=channel, text=msg)


def process_blacklist(channel: str, message: str) -> None:
    """Blacklist a user based on a message from slack."""
    parsed_message = message.split()
    if len(parsed_message) == 1:
        # they didn't give a username
        msg = i18n["slack"]["errors"]["missing_username"]
    elif len(parsed_message) == 2:
        username = clean_links(parsed_message[1])
        if user := BlossomUser.objects.filter(username__iexact=username).first():
            if user.blacklisted:
                user.blacklisted = False
                user.save()
                msg = i18n["slack"]["blacklist"]["success_undo"].format(username)
            else:
                user.blacklisted = True
                user.save()
                msg = i18n["slack"]["blacklist"]["success"].format(username)
        else:
            msg = i18n["slack"]["errors"]["unknown_username"]
    else:
        msg = i18n["slack"]["errors"]["too_many_params"]

    client.chat_postMessage(channel=channel, text=msg)


def pong(channel: str, *args: Any) -> None:
    """Respond to pings."""
    client.chat_postMessage(channel=channel, text="PONG")


def process_coc_reset(channel: str, message: str) -> None:
    """Reset the CoC status for a given volunteer."""
    parsed_message = message.split()
    if len(parsed_message) == 1:
        # they didn't give a username
        msg = i18n["slack"]["errors"]["missing_username"]
    elif len(parsed_message) == 2:
        username = clean_links(parsed_message[1])
        if user := BlossomUser.objects.filter(username__iexact=username).first():
            if user.accepted_coc:
                user.accepted_coc = False
                user.save()
                msg = i18n["slack"]["reset_coc"]["success"].format(username)
            else:
                user.accepted_coc = True
                user.save()
                msg = i18n["slack"]["reset_coc"]["success_undo"].format(username)
        else:
            msg = i18n["slack"]["errors"]["unknown_username"]

    else:
        msg = i18n["slack"]["errors"]["too_many_params"]

    client.chat_postMessage(channel=channel, text=msg)


def dadjoke_target(channel: str, message: str, use_api: bool = True) -> None:
    """Send the pinged user a dad joke. Or just send everybody a joke."""
    parsed_message = message.split()
    ping_username, msg = None, None
    try:
        if use_api:
            joke = requests.get(
                "https://icanhazdadjoke.com/", headers={"Accept": "text/plain"}
            ).content.decode()
        else:
            raise Exception("Testing mode -- just use fallback.")
    except:  # noqa: E722
        joke = i18n["slack"]["dadjoke"]["fallback_joke"]

    if len(parsed_message) == 2:
        if parsed_message[1].startswith("<"):
            ping_username = parsed_message[1].upper()

        if ping_username:
            msg = i18n["slack"]["dadjoke"]["message"].format(ping_username, joke)

    if not msg:
        msg = joke

    client.chat_postMessage(channel=channel, text=msg, link_names=True)


def get_message(data: Dict) -> Optional[str]:
    """
    Pull message text out of slack event.

    What comes in: "<@UTPFNCQS2> hello!" Strip out the beginning section
    and see what's left.
    """
    event = data.get("event")
    # Note: black and flake8 disagree on the formatting. Black wins.
    try:
        return event["text"][event["text"].index(">") + 2 :].lower()  # noqa: E203
    except IndexError:
        return None


@fire_and_forget
def process_message(data: Dict) -> None:
    """Identify the purpose of a slack message and route accordingly."""
    if data.get("type") == "block_actions":
        value = data["actions"][0].get("value")
        if "keep" in value or "remove" in value:
            process_submission_update(data)
        else:
            client.chat_postMessage(
                channel=data["channel"]["id"],
                text=i18n["slack"]["errors"]["unknown_payload"].format(value),
            )
        return

    e = data.get("event")  # noqa: VNE001
    channel = e.get("channel")

    message = get_message(data)
    actions = data.get("actions")

    if not message and not actions:
        client.chat_postMessage(
            channel=channel, text=i18n["slack"]["errors"]["message_parse_error"],
        )
        return

    if not message:
        client.chat_postMessage(
            channel=channel, text=i18n["slack"]["errors"]["empty_message_error"],
        )
        return

    # format: first word command -> function to call
    # Reformatted this way because E228 hates the if / elif routing tree.
    options = {
        "ping": pong,
        "help": send_help_message,
        "reset": process_coc_reset,
        "info": send_info,
        "blacklist": process_blacklist,
        "dadjoke": dadjoke_target,
    }

    for key in options.keys():
        if message.startswith(key):
            options[key](channel, message)
            return

    # if we fall through here, we got a message that we don't understand.
    client.chat_postMessage(
        channel=channel, text=i18n["slack"]["errors"]["unknown_request"]
    )


def is_valid_github_request(request: HttpRequest) -> bool:
    """Verify that a webhook from github sponsors is encoded using our key."""
    if (github_signature := request.headers.get("x-hub-signature")) is None:
        return False

    body_hex = binascii.hexlify(
        hmac.digest(
            msg=request.body,
            key=settings.GITHUB_SPONSORS_SECRET_KEY.encode(),
            digest="sha1",
        )
    ).decode()

    body_hex = f"sha1={body_hex}"
    return hmac.compare_digest(body_hex, github_signature)


def is_valid_slack_request(request: HttpRequest) -> bool:
    """Verify that a webhook from Slack is actually from them."""
    # adapted from https://api.slack.com/authentication/verifying-requests-from-slack
    if (slack_signature := request.headers.get("X-Slack-Signature")) is None:
        return False

    timestamp = request.headers["X-Slack-Request-Timestamp"]
    if abs(time.time() - int(timestamp)) > 60 * 5:
        # The request timestamp is more than five minutes from local time.
        # It could be a replay attack, so let's ignore it.
        return False

    sig_basestring = "v0:" + timestamp + ":" + request.body.decode()

    signature = (
        "v0="
        + hmac.new(
            bytes(settings.SLACK_SIGNING_SECRET, "latin-1"),
            msg=bytes(sig_basestring, "latin-1"),
            digestmod=hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(signature, slack_signature)
