# Setup package for Penguin first-time configuration

# Try to import setup functions, providing fallbacks if dependencies are missing
try:
    from .wizard import run_setup_wizard_sync, run_setup_wizard, check_first_run, check_config_completeness, check_setup_dependencies
    SETUP_AVAILABLE = True
    SETUP_ERROR = None
except ImportError as e:
    SETUP_AVAILABLE = False
    SETUP_ERROR = str(e)
    
    # Provide fallback functions that indicate the issue
    def run_setup_wizard_sync():
        return {"error": f"Setup wizard unavailable: {SETUP_ERROR}"}
    
    async def run_setup_wizard():
        return {"error": f"Setup wizard unavailable: {SETUP_ERROR}"}
    
    def check_first_run():
        # If setup isn't available, assume setup is not needed
        # (user will need to configure manually)
        return False
    
    def check_config_completeness():
        # If setup isn't available, assume config is complete
        return True
    
    def check_setup_dependencies():
        return False, ["questionary", "httpx", "PyYAML", "rich"]

__all__ = [
    "run_setup_wizard_sync", 
    "run_setup_wizard", 
    "check_first_run", 
    "check_config_completeness",
    "check_setup_dependencies",
    "SETUP_AVAILABLE",
    "SETUP_ERROR"
] 