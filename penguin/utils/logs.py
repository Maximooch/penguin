import logging
from logging.handlers import RotatingFileHandler
import json
import datetime
import os
from config import WORKSPACE_PATH
import logging

logger = logging.getLogger('Penguin')

def setup_logger(log_file: str = 'Penguin.log', log_level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger('Penguin')
    logger.setLevel(log_level)

    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create logs directory if it doesn't exist
    penguin_log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    log_dirs = [penguin_log_dir, os.path.join(WORKSPACE_PATH, 'logs')]
    for log_dir in log_dirs:
        os.makedirs(log_dir, exist_ok=True)

    # Set up file handlers with rotation and UTF-8 encoding
    for log_dir in log_dirs:
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, log_file),
            maxBytes=1024 * 1024,  # 1 MB
            backupCount=5,
            encoding='utf-8'  # Add UTF-8 encoding
        )
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Add a StreamHandler for console output with UTF-8 encoding
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setStream(open(os.devnull, 'w', encoding='utf-8'))  # Redirect to null device
    logger.addHandler(console_handler)

    logger.propagate = False
    return logger

def log_event(logger: logging.Logger, event_type: str, content: str):
    try:
        # Clean content of emojis and special characters for logging
        clean_content = content.encode('ascii', 'ignore').decode()
        
        # Create a new timestamp for each event
        timestamp = datetime.datetime.now()
        
        # Create logs directory if it doesn't exist
        logs_dir = os.path.join(WORKSPACE_PATH, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        
        # Generate filenames with current timestamp
        base_filename = f"chat_{timestamp.strftime('%Y%m%d_%H%M')}"
        json_log_file = os.path.join(logs_dir, f"{base_filename}.json")
        md_log_file = os.path.join(logs_dir, f"{base_filename}.md")

        # Only create new files if they don't exist
        if not os.path.exists(json_log_file):
            _write_json_log(json_log_file, event_type, content, timestamp)
        else:
            # Append to existing file
            _append_json_log(json_log_file, event_type, content, timestamp)

        if not os.path.exists(md_log_file):
            with open(md_log_file, 'w', encoding='utf-8') as f:
                f.write(f"# Chat Log - {timestamp.strftime('%Y-%m-%d %H:%M')}\n\n")
        _write_markdown_log(md_log_file, event_type, content, timestamp)
        
        # Use cleaned content for console logging
        logger.info(f"{event_type.upper()}: {clean_content}")
    except Exception as e:
        logger.error(f"Error in log_event: {str(e)}")

def _write_json_log(file_path: str, event_type: str, content: str, timestamp: datetime.datetime):
    try:
        with open(file_path, 'r+') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
            
            data.append({
                "timestamp": timestamp.isoformat(),
                "type": event_type,
                "content": content
            })
            
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2)
    except FileNotFoundError:
        with open(file_path, 'w') as f:
            json.dump([{
                "timestamp": timestamp.isoformat(),
                "type": event_type,
                "content": content
            }], f, indent=2)

def _write_markdown_log(file_path: str, event_type: str, content: str, timestamp: datetime.datetime):
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
            metadata = (parts[1].split("'action_results':")[1]
                      .replace("'", '"')  # Replace single quotes with double quotes
                      .replace("{", "")   # Remove curly braces
                      .replace("}", "")
                      .strip())
            
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
    with open(file_path, 'a', encoding='utf-8') as f:
        f.write(log_entry)

def _append_json_log(file_path: str, event_type: str, content: str, timestamp: datetime.datetime):
    """Append to existing JSON log file"""
    try:
        with open(file_path, 'r+', encoding='utf-8') as f:
            try:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
            except json.JSONDecodeError:
                data = []
            
            data.append({
                "timestamp": timestamp.isoformat(),
                "type": event_type,
                "content": content
            })
            
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error appending to JSON log: {str(e)}")

# Create a global logger instance
penguin_logger = setup_logger()

logging.getLogger().setLevel(logging.WARNING)