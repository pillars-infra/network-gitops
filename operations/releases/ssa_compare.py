"""Bounded retries for read-only SSA projections racing status updates."""
def retry_read_conflict(read_and_project):
    for attempt in range(3):
        try:
            return read_and_project()
        except RuntimeError as error:
            # Only optimistic resourceVersion races: never ownership conflicts,
            # admission denials, auth failures, timeouts or actual SSA writes.
            if attempt == 2 or 'the object has been modified' not in str(error):
                raise


def safe_failure_reason(error):
    message = str(error).lower()
    if 'the object has been modified' in message:
        return 'concurrent object update after bounded read-only retries'
    if 'conflict with' in message or 'field manager conflict' in message:
        return 'SSA field ownership conflict'
    if 'forbidden' in message or 'unauthorized' in message:
        return 'authorization denied'
    if 'timeout' in message or 'timed out' in message or 'deadline exceeded' in message or 'serviceunavailable' in message:
        return 'API transport or availability failure'
    return 'API request rejected; raw diagnostics withheld'
