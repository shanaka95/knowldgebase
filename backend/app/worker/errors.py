class JobCancelled(Exception):
    """Raised when the job was asked to cancel (newer document version or manual)."""


class JobSuperseded(Exception):
    """The document changed while the job ran; results must not be written."""


class RetryableError(Exception):
    """Transient failure: the job goes back to the queue with backoff."""


class FatalError(Exception):
    """Permanent failure: the job fails immediately without retries."""
