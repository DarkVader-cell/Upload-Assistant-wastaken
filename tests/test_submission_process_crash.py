# ruff: noqa: S101
import subprocess
import sys

import pytest

from src.cogs.redaction import Redaction
from src.runtime.submission_progress import SubmissionJournal, SubmissionNeedsReviewError


def test_dead_posting_process_requires_review_not_replay(tmp_path):
    code = 'from pathlib import Path; from src.runtime.submission_progress import SubmissionJournal; import sys; SubmissionJournal(Path(sys.argv[1])).begin("AITHER")'
    subprocess.run([sys.executable, '-c', code, str(tmp_path)], check=True)  # noqa: S603 -- literal isolated test program
    store = SubmissionJournal(tmp_path)
    with pytest.raises(SubmissionNeedsReviewError, match='may have reached') as error:
        store.begin('AITHER')
    token = store.lookup('AITHER')['nonce']
    assert token in Redaction.redact_private_info(str(error.value))
    assert store.begin('AITHER', confirmation=token)
