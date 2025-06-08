# Implement the MilvusProvider class

from penguin.memory.providers.base_provider import BaseProvider

class MilvusProvider(BaseProvider):
    def __init__(self, collection_name: str):
        self.collection_name = collection_name

    def add(self, data: dict):
        pass
    