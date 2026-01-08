import os
import time
import json
import uuid
from pathlib import Path


class TimeLogger:

    def __init__(self, logging_dir: str):
        if isinstance(logging_dir, Path):
            logging_dir = str(logging_dir)
        self.logging_dir = logging_dir
        os.makedirs(self.logging_dir, exist_ok=True)

    def log_event(self, pr_number, test_id, event_type, component, is_error=False):
        """
        Logs an event with the following fields:
        - timestamp: Current time in seconds since epoch
        - type of event: 'start' or 'end'
        - component: Component name in snake_case_lower
        - test id: Test ID (1-20)
        - process id: Current process ID
        """
        timestamp = time.time()
        process_id = os.getpid()

        # Prepare log entry
        log_entry = {
            "timestamp": timestamp,
            "type_of_event": event_type,
            "component": component,
            "test_id": test_id,
            "process_id": process_id,
            "is_error": is_error,
            "pr_number": pr_number
        }

        # Define the output directory and file
        output_file = os.path.join(
            self.logging_dir, f"{timestamp}_{str(uuid.uuid4())[:6]}.json")

        # Write the log entry to the file
        with open(output_file, "w") as file:
            json.dump(log_entry, file, indent=4)

