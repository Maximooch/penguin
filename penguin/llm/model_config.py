class ModelConfig:
    DEFAULT_MODEL = "claude-3-5-sonnet-20240620"
    DEFAULT_MAX_TOKENS = 4000

    def __init__(self, model=DEFAULT_MODEL, max_tokens=DEFAULT_MAX_TOKENS):
        self.model = model
        self.max_tokens = max_tokens

    def update_config(self, model=None, max_tokens=None):
        if model:
            self.model = model
        if max_tokens:
            self.max_tokens = max_tokens

    def get_config(self):
        return {
            "model": self.model,
            "max_tokens": self.max_tokens
        }

# Example usage:
# config = ModelConfig()
# print(config.get_config())
# config.update_config(model="claude-3-7-sonnet-20240620", max_tokens=8000)
# print(config.get_config())