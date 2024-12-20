# penguin/utils/errors.py
import logging
import traceback
import sys
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
import json

logger = logging.getLogger(__name__)

class ErrorHandler:
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Configure file handler
        fh = logging.FileHandler(self.log_dir / "errors.log")
        fh.setLevel(logging.ERROR)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    def log_error(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        *,
        fatal: bool = False
    ) -> Dict[str, Any]:
        """Unified error logging"""
        error_data = {
            "timestamp": datetime.now().isoformat(),
            "error_type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
            "context": context or {},
            "severity": "FATAL" if fatal else "ERROR"
        }

        # Log to file
        logger.error(
            f"{error_data['severity']}: {error_data['message']}",
            extra={"error_data": error_data},
            exc_info=sys.exc_info() if fatal else None
        )

        # Write detailed error report
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        error_file = self.log_dir / f"error_{timestamp}.json"
        error_file.write_text(json.dumps(error_data, indent=2))

        return error_data

# Global error handler instance
error_handler = ErrorHandler(Path("errors_log"))

def setup_global_error_handling():
    """Setup global exception handler"""
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        error_handler.log_error(
            exc_value,
            context={"uncaught": True},
            fatal=True
        )

    sys.excepthook = handle_exception