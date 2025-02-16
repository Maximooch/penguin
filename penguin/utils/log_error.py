import os
import traceback
from datetime import datetime


def log_error(error: Exception, context: str):
    error_log_dir = os.path.join(os.getcwd(), "errors_log")
    if not os.path.exists(error_log_dir):
        os.makedirs(error_log_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    error_file = os.path.join(error_log_dir, f"error_{timestamp}.log")

    with open(error_file, "w") as f:
        f.write(f"Error occurred at: {datetime.now()}\n")
        f.write(f"Context: {context}\n\n")
        f.write(f"Error type: {type(error).__name__}\n")
        f.write(f"Error message: {str(error)}\n\n")
        f.write("Traceback:\n")
        f.write(traceback.format_exc())

    print(f"Detailed error log saved to: {error_file}")
