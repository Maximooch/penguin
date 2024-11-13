import logging
from logging.handlers import RotatingFileHandler
import json
import datetime
import os
from config import WORKSPACE_PATH

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

    # Set up file handlers with rotation
    for log_dir in log_dirs:
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, log_file),
            maxBytes=1024 * 1024,  # 1 MB
            backupCount=5
        )
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger

def log_event(logger: logging.Logger, event_type: str, content: str):
    timestamp = datetime.datetime.now()
    json_log_file = os.path.join(WORKSPACE_PATH, 'logs', f"chat_{timestamp.strftime('%Y%m%d_%H%M')}.json")
    md_log_file = json_log_file.replace('.json', '.md')

    try:
        _write_json_log(json_log_file, event_type, content, timestamp)
        _write_markdown_log(md_log_file, event_type, content, timestamp)
    except Exception as e:
        logger.error(f"Error writing to log files: {str(e)}")

    logger.info(f"{event_type.upper()}: {content}")

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
    log_entry = ""
    if event_type == "user":
        log_entry = f"### 👤 User ({timestamp_str}):\n{content}\n\n"
    elif event_type == "assistant":
        log_entry = f"### 🐧 Penguin AI ({timestamp_str}):\n{content}\n\n"
    else:
        log_entry = f"### System ({timestamp_str}):\n{content}\n\n"
    
    with open(file_path, 'a', encoding='utf-8') as f:
        f.write(log_entry)

# Create a global logger instance
penguin_logger = setup_logger()