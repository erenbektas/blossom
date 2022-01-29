import json

from django.test import Client
from django.urls import reverse
from rest_framework import status

from utils.test_helpers import create_submission, setup_user_client


class TestSubmissionRemove:
    """Tests validating the behavior of the Submission removal process."""

    def test_remove_no_params(self, client: Client) -> None:
        """Verify that removing a submission works without parameters."""
        client, headers, user = setup_user_client(client)

        submission = create_submission(id=3)
        assert not submission.removed_from_queue

        data = {}

        result = client.patch(
            reverse("submission-remove", args=[submission.id]),
            json.dumps(data),
            content_type="application/json",
            **headers
        )

        submission.refresh_from_db()

        assert result.status_code == status.HTTP_200_OK
        assert submission.removed_from_queue

    def test_remove_no_change(self, client: Client) -> None:
        """Verify that removing a submission works without parameters."""
        client, headers, user = setup_user_client(client)

        submission = create_submission(id=3, removed_from_queue=True)
        assert submission.removed_from_queue

        data = {}

        result = client.patch(
            reverse("submission-remove", args=[submission.id]),
            json.dumps(data),
            content_type="application/json",
            **headers
        )

        submission.refresh_from_db()

        assert result.status_code == status.HTTP_200_OK
        assert submission.removed_from_queue

    def test_remove_param_false(self, client: Client) -> None:
        """Verify that restoring submissions works correctly."""
        client, headers, user = setup_user_client(client)

        submission = create_submission(id=3, removed_from_queue=True)
        assert submission.removed_from_queue

        data = {"removed_from_queue": False}

        result = client.patch(
            reverse("submission-remove", args=[submission.id]),
            json.dumps(data),
            content_type="application/json",
            **headers
        )

        submission.refresh_from_db()

        assert result.status_code == status.HTTP_200_OK
        assert not submission.removed_from_queue

    def test_remove_param_true(self, client: Client) -> None:
        """Verify that removing a submission works without parameters."""
        client, headers, user = setup_user_client(client)

        submission = create_submission(id=3)
        assert not submission.removed_from_queue

        data = {"removed_from_queue": True}

        result = client.patch(
            reverse("submission-remove", args=[submission.id]),
            json.dumps(data),
            content_type="application/json",
            **headers
        )

        submission.refresh_from_db()

        assert result.status_code == status.HTTP_200_OK
        assert submission.removed_from_queue

    def test_remove_reverting_approval(self, client: Client) -> None:
        """Verify that removing the submission reverts an approval."""
        client, headers, user = setup_user_client(client)

        submission = create_submission(id=3, approved=True)
        assert not submission.removed_from_queue
        assert submission.approved

        data = {}

        result = client.patch(
            reverse("submission-remove", args=[submission.id]),
            json.dumps(data),
            content_type="application/json",
            **headers
        )

        submission.refresh_from_db()

        assert result.status_code == status.HTTP_200_OK
        assert submission.removed_from_queue
        assert not submission.approved
