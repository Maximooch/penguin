import time
import os
import subprocess
import sys
import io

start_time = time.time()
os.environ['PENGUIN_START_TIME'] = str(start_time)

# Set the encoding for subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Run the main.py script
result = subprocess.run([sys.executable, 'main.py'], capture_output=True, text=True, encoding='utf-8')

end_time = time.time()
total_time = end_time - start_time
print(f"\nTotal startup time (including imports): {total_time:.2f} seconds")

# Print the output from main.py
print(result.stdout)

if result.stderr:
    print("Errors:", result.stderr, file=sys.stderr)