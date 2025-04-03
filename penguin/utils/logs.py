import datetime
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Remove direct import from config
# from penguin.config import WORKSPACE_PATH

# Instead, use a function to get the workspace path
def get_workspace_path():
    """Get the workspace path without importing from config to avoid circular imports."""
    # Default workspace path for development environment
    default_path = Path.home() / "Documents" / "code" / "Penguin" / "penguin_workspace"
    
    # Try to get from environment variable first
    ws_path = os.getenv('PENGUIN_WORKSPACE')
    if ws_path:
        return Path(ws_path)
    
    # Return default if environment variable not set
    return default_path

# Use the function instead of the imported variable
WORKSPACE_PATH = get_workspace_path()


def setup_logger(
    log_file: str = "Penguin.log", log_level: int = logging.INFO
) -> logging.Logger:
    logger = logging.getLogger("Penguin")
    logger.setLevel(log_level)

    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create logs directory if it doesn't exist
    penguin_log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    log_dirs = [penguin_log_dir, os.path.join(WORKSPACE_PATH, "logs")]
    for log_dir in log_dirs:
        os.makedirs(log_dir, exist_ok=True)

    # Set up file handlers with rotation
    for log_dir in log_dirs:
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, log_file),
            maxBytes=1024 * 1024,  # 1 MB
            backupCount=5,
        )
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, event_type: str, content: str):
    timestamp = datetime.datetime.now()
    json_log_file = os.path.join(
        WORKSPACE_PATH, "logs", f"chat_{timestamp.strftime('%Y%m%d_%H%M')}.json"
    )
    md_log_file = json_log_file.replace(".json", ".md")

    # Add debug logging
    print(
        f"Attempting to log to: {json_log_file} and {md_log_file}"
    )  # Temporary debug print
    print(f"WORKSPACE_PATH: {WORKSPACE_PATH}")  # Verify workspace path

    try:
        # Verify directories exist
        log_dir = os.path.dirname(json_log_file)
        if not os.path.exists(log_dir):
            print(f"Creating log directory: {log_dir}")
            os.makedirs(log_dir, exist_ok=True)

        _write_json_log(json_log_file, event_type, content, timestamp)
        _write_markdown_log(md_log_file, event_type, content, timestamp)
        print("Successfully wrote logs")  # Confirm write succeeded
    except Exception as e:
        print(f"Error writing logs: {str(e)}")  # Print the actual error
        logger.error(f"Error writing to log files: {str(e)}")


def _write_json_log(
    file_path: str, event_type: str, content: str, timestamp: datetime.datetime
):
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        data = []
        # Try to read existing data
        if os.path.exists(file_path):
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                print(f"Error reading existing JSON file: {file_path}")
                # Continue with empty data if file is corrupted
                pass

        # Append new entry
        data.append(
            {"timestamp": timestamp.isoformat(), "type": event_type, "content": content}
        )

        # Write updated data
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        print(f"Error in _write_json_log: {str(e)}")
        raise


def _write_markdown_log(
    file_path: str, event_type: str, content: str, timestamp: datetime.datetime
):
    timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")

    if event_type == "user":
        log_entry = f"### 👤 User ({timestamp_str}):\n{content}\n\n"
    elif event_type == "assistant":
        # Check if this is already a formatted response
        if "'assistant_response':" not in content:
            log_entry = f"### 🐧 Penguin AI ({timestamp_str}):\n{content}\n\n"
        else:
            parts = content.split("'assistant_response': ")
            message = parts[1].split("', 'action_results")[0].strip('"')
            metadata = (
                parts[1]
                .split("'action_results':")[1]
                .replace("'", '"')  # Replace single quotes with double quotes
                .replace("{", "")  # Remove curly braces
                .replace("}", "")
                .strip()
            )

            log_entry = (
                f"### 🐧 Penguin AI ({timestamp_str}):\n"
                f"{message}\n"
                f"\n"
                f"\n"
                f"    {metadata}\n"
                f"\n"
            )
            # No else needed here since we're already in the assistant block
    else:
        log_entry = f"### System ({timestamp_str}):\n{content}\n\n"
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(log_entry)


# Create a global logger instance
penguin_logger = setup_logger()
