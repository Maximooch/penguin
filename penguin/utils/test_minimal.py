print("Starting minimal test...")

try:
    from utils.errors import error_handler
    print("Successfully imported error handler")
    
    # Trigger a simple error
    try:
        1/0
    except Exception as e:
        print("Triggering test error...")
        error_handler.log_error(e, context={"test": "minimal"})
        print("Error logged successfully")
        
except Exception as e:
    print(f"Test failed: {e}")
    import traceback
    print(traceback.format_exc())

print("Press Enter to exit...")
input() 