"""
Class name: LLMTokenLogger

---

**Task Description**

Create a Python class `LLMTokenLogger` for logging and organizing token usage information from LLM completions. The logger is designed for use with dspy and enforces the following requirements:

### Requirements

1. **Logging Method**
    - Accepts:
        - `lm` (dspy.LM instance): The LLM instance, must have non-empty `.history` with 'usage' in the last entry.
        - `stage` (dspy.Signature subclass): The stage of the process, passed as a dspy.Signature class (not an instance).
    - The logger asserts that `stage` is a subclass of `dspy.Signature`. If not, it raises an informative `TypeError`.
    - The logger extracts the class name of the `stage` as the stage name.
    - The logger extracts the model name from `lm.model`.

2. **Storage**
    - Stores logs in memory, organized by model name and stage name.
    - Each log entry includes:
        - All fields from the last `usage` dict in `lm.history`
        - `model_name`
        - `stage_name` (from the class name)
        - `timestamp` (Unix epoch with timezone, generated automatically)
    - Multiple entries for the same model and stage are allowed and stored in insertion order.

3. **Retrieval**
    - Provides a method to retrieve all logs as a dictionary:
      ```python
      {
          "<model_name>": {
              "<stage_name>": [
                  {
                      ...log_info fields...,
                      "model_name": ...,
                      "stage_name": ...,
                      "timestamp": ...,
                      "readable_date": ...  # Added at retrieval time, ISO 8601 format
                  },
                  ...
              ],
              ...
          },
          ...
      }
      ```
    - The `readable_date` field is added only when retrieving logs, using a human-readable ISO 8601 format.

4. **Clear Method**
    - Provides a method to clear all stored logs.

5. **Other Constraints**
    - Only dspy.Signature subclasses are allowed as stage.
    - Raises informative errors for invalid input.
    - No persistence, editing, or filtering required.

---

**Example Usage**

```python
logger = LLMTokenLogger()
logger.log(lm, MyStageSignature)
logs = logger.get_logs()
logger.clear()
```

**Example Output**

```python
{
    "gemini/gemini-2.0-flash": {
        "MyStageSignature": [
            {
                "completion_tokens": 100,
                "prompt_tokens": 200,
                "total_tokens": 300,
                "model_name": "gemini/gemini-2.0-flash",
                "stage_name": "MyStageSignature",
                "timestamp": 1718200000.0,
                "readable_date": "2024-06-12T14:33:20+00:00"
            }
        ]
    }
}
```

"""

import time
from datetime import datetime, timezone
from typing import Dict, Any, List
import dspy


class LLMTokenLogger:
    """
    Logger for organizing token usage information from LLM completions.
    Designed for use with dspy and stores logs organized by model name and stage name.

    Usage:
        logger = LLMTokenLogger()
        logger.log(lm, MyStageSignature)
        logs = logger.get_logs()
        logger.clear()
    """

    def __init__(self):
        """Initialize the logger with empty storage."""
        self._logs: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    def log(self, lm, stage) -> None:
        """
        Log token usage information for a specific model and stage using a dspy.LM instance.

        Args:
            lm: The dspy.LM instance (must have non-empty .history with 'usage' in the last entry and a .model attribute).
            stage: A dspy.Signature subclass (not an instance).

        Raises:
            TypeError: If stage is not a dspy.Signature subclass.
            ValueError: If lm does not have valid token usage info or model name.
        """
        # Validate stage is a dspy.Signature subclass
        if not (isinstance(stage, type) and issubclass(stage, dspy.Signature)):
            raise TypeError(
                f"stage must be a subclass of dspy.Signature, got {type(stage).__name__}")

        # Validate lm has model, history and usage
        if not hasattr(lm, "model"):
            raise ValueError("lm must have a .model attribute")
        if not hasattr(
                lm, "history") or not lm.history or 'usage' not in lm.history[-1]:
            raise ValueError(
                "lm must have non-empty .history with 'usage' in the last entry")

        model_name = lm.model
        stage_name = stage.__name__
        timestamp = time.time()
        log_info = lm.history[-1]['usage']

        log_entry = {
            "completion_tokens": log_info.get("completion_tokens", 0),
            "prompt_tokens": log_info.get("prompt_tokens", 0),
            "total_tokens": log_info.get("total_tokens", 0),
            "model_name": model_name,
            "stage_name": stage_name,
            "timestamp": timestamp
        }

        if model_name not in self._logs:
            self._logs[model_name] = {}

        if stage_name not in self._logs[model_name]:
            self._logs[model_name][stage_name] = []

        self._logs[model_name][stage_name].append(log_entry)

    def get_logs(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """
        Retrieve all logs with readable_date field added.

        Returns:
            Dictionary organized by model_name -> stage_name -> list of log entries.
            Each entry includes a 'readable_date' field in ISO 8601 format.
        """
        result = {}

        for model_name, stages in self._logs.items():
            result[model_name] = {}

            for stage_name, entries in stages.items():
                result[model_name][stage_name] = []

                for entry in entries:
                    # Create a copy and add readable_date
                    enhanced_entry = entry.copy()
                    timestamp = entry["timestamp"]
                    readable_date = datetime.fromtimestamp(
                        timestamp, tz=timezone.utc).isoformat()
                    enhanced_entry["readable_date"] = readable_date

                    result[model_name][stage_name].append(enhanced_entry)

        return result

    def get_logs_as_list(self) -> List[Dict[str, Any]]:
        """
        Retrieve all logs as a flat list of log entries.

        Returns:
            List of log entries with 'readable_date' field added.
        """
        logs_list = []
        for model_name, stages in self._logs.items():
            for stage_name, entries in stages.items():
                for entry in entries:
                    enhanced_entry = entry.copy()
                    timestamp = entry["timestamp"]
                    readable_date = datetime.fromtimestamp(
                        timestamp, tz=timezone.utc).isoformat()
                    enhanced_entry["readable_date"] = readable_date
                    logs_list.append(enhanced_entry)
        return logs_list

    def clear(self) -> None:
        """Clear all stored logs."""
        self._logs.clear()
