import logging
import json
import datetime
import os
from config import WORKSPACE_PATH

def setup_logger():
    log_dirs = ['logs', os.path.join(WORKSPACE_PATH, 'logs')]
    for log_dir in log_dirs:
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_files = [f"{log_dir}/chat_{timestamp}.json" for log_dir in log_dirs]
    return log_files

def log_event(log_files, event_type, content):
    for log_file in log_files:
        # JSON logging
        try:
            with open(log_file, 'r+') as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = []
                
                data.append({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "type": event_type,
                    "content": content
                })
                
                f.seek(0)
                json.dump(data, f, indent=2)
                f.truncate()
        except FileNotFoundError:
            with open(log_file, 'w') as f:
                json.dump([{
                    "timestamp": datetime.datetime.now().isoformat(),
                    "type": event_type,
                    "content": content
                }], f, indent=2)

        # Markdown logging
        md_file = log_file.replace('.json', '.md')
        with open(md_file, 'a', encoding='utf-8') as f:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if event_type == "user":
                f.write(f"### 👤 User ({timestamp}):\n{content}\n\n")
            elif event_type == "assistant":
                f.write(f"### 🐧 Penguin AI ({timestamp}):\n{content}\n\n")
            else:
                f.write(f"### System ({timestamp}):\n{content}\n\n")



# Create a global logger instance
logger = logging.getLogger('Penguin')
logger.setLevel(logging.INFO)

# Prevent the logger from propagating to the root logger
logger.propagate = False