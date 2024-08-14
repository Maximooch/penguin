from rank_bm25 import BM25Okapi
import re
import os
import shutil
import json
from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime

Base = declarative_base()

"""
Manages the conversation history and provides search capabilities.

Also thinking of a declarative memory entry log that can be used to store important information. Probably loaded from a file or database at startup.


"""

# Search Tools

class ConversationBM25Search:
    def __init__(self):
        self.messages = []
        self.bm25 = None

    def add_message(self, message):
        self.messages.append(message)
        tokenized_corpus = [msg['content'].split() for msg in self.messages]
        self.bm25 = BM25Okapi(tokenized_corpus)

    def search(self, query, k=5):
        tokenized_query = query.split()
        doc_scores = self.bm25.get_scores(tokenized_query)
        top_n = sorted(range(len(doc_scores)), key=lambda i: doc_scores[i], reverse=True)[:k]
        return [self.messages[i] for i in top_n]
    
class ConversationGrepSearch:
    def __init__(self):
        self.messages = []

    def add_message(self, message):
        self.messages.append(message)

    def search(self, pattern, k=5):
        regex = re.compile(pattern, re.IGNORECASE)
        matches = []
        for msg in self.messages:
            if regex.search(msg['content']):
                matches.append(msg)
            if len(matches) == k:
                break
        return matches


class ConversationEntry(Base):
    __tablename__ = 'conversation_history'

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    role = Column(String)
    content = Column(JSON)

class SimpleMemory:
    def __init__(self, db_path='penguin_memory.db'):
        self.engine = create_engine(f'sqlite:///{db_path}')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def add_message(self, role, content):
        session = self.Session()
        entry = ConversationEntry(role=role, content=content)
        session.add(entry)
        session.commit()
        session.close()

    def get_history(self, limit=None):
        session = self.Session()
        query = session.query(ConversationEntry).order_by(ConversationEntry.timestamp.desc())
        if limit:
            query = query.limit(limit)
        history = [{"role": entry.role, "content": entry.content} for entry in query.all()]
        session.close()
        return list(reversed(history))

    def clear_history(self):
        session = self.Session()
        session.query(ConversationEntry).delete()
        session.commit()
        session.close()

    def search_history(self, query, limit=5):
        session = self.Session()
        results = session.query(ConversationEntry).filter(
            ConversationEntry.content.like(f'%{query}%')
        ).order_by(ConversationEntry.timestamp.desc()).limit(limit).all()
        session.close()
        return [{"role": entry.role, "content": entry.content} for entry in results]