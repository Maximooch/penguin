class ActionValidator:
    """Implements security policies for actions"""
    
    SAFE_PATHS = ["/workspace/"]
    BANNED_COMMANDS = ["rm", "sudo", "chmod"]
    
    @classmethod
    def validate(cls, action) -> bool:
        if action.type == "command":
            return cls._validate_command(action)
        elif action.type == "file_write":
            return cls._validate_file_path(action.params.get("path"))
        return True
    
    @classmethod
    def _validate_command(cls, action) -> bool:
        cmd = action.params.get("command", "")
        return not any(banned in cmd for banned in cls.BANNED_COMMANDS)
    
    @classmethod
    def _validate_file_path(cls, path: str) -> bool:
        return any(path.startswith(p) for p in cls.SAFE_PATHS) and ".." not in path 