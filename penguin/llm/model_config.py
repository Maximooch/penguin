# might move this to a config file later, I suppose it could just import it from an upstream config file.

class ModelConfig:
    DEFAULT_MODEL = "llama-3.1-70b-versatile"
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_TEMPERATURE = 0.7
    # API_PROVIDER = "groq"
    API_BASE = "https://api.groq.com/openai/v1"

    def __init__(self, model=DEFAULT_MODEL, max_tokens=DEFAULT_MAX_TOKENS, temperature=DEFAULT_TEMPERATURE):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        # self.api_provider = self.API_PROVIDER
        self.api_base = self.API_BASE

    def get_config(self):
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            # "api_provider": self.api_provider,
            "api_base": self.api_base
        }

# Example usage:
# config = ModelConfig()
# print(config.get_config())
# config.update_config(model="claude-3-7-sonnet-20240620", max_tokens=8000)
# print(config.get_config())