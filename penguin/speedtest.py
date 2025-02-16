#!/usr/bin/env pypy3
import cProfile
import importlib
import io
import os
import pstats
import sys
import time

start_time = time.time()
os.environ["PENGUIN_START_TIME"] = str(start_time)

# Set the encoding for stdout and stderr
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


def run_main_init():
    # Import main module
    main_module = importlib.import_module("main")
    # Run the initialization part of main
    main_module.init()


# Profile the initialization process
profiler = cProfile.Profile()
profiler.enable()

run_main_init()

profiler.disable()

end_time = time.time()
total_time = end_time - start_time
print(f"\nTotal startup time (including imports): {total_time:.2f} seconds")

# Print profiling results
print("\nProfiling Results:")
stats = pstats.Stats(profiler)
stats.sort_stats("cumulative")
stats.print_stats(20)  # Print top 20 time-consuming functions

# Now run the chat loop
main_module = importlib.import_module("main")
main_module.run_chat()
