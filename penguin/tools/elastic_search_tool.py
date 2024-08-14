from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
import os
import json
from typing import List, Dict, Union
import logging

class ElasticSearch:
    def __init__(self, root_dir: str = '.', es_host: str = 'localhost', es_port: int = 9200):
        self.root_dir = root_dir
        self.es = Elasticsearch([{'host': es_host, 'port': es_port, 'scheme': 'http'}])
        self.index_name = 'penguin_search'
        
        if not self.es.indices.exists(index=self.index_name):
            self.es.indices.create(index=self.index_name)
        
        self.index_files()

    def index_files(self):
        actions = []
        for root, _, files in os.walk(self.root_dir):
            for file in files:
                if file.endswith(('.py', '.md', '.txt')):
                    file_path = os.path.join(root, file)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        actions.append({
                            '_index': self.index_name,
                            '_source': {
                                'type': 'file',
                                'path': file_path,
                                'content': content
                            }
                        })
        
        if actions:
            success, _ = bulk(self.es, actions)
            logging.info(f"Indexed {success} files")

    def add_message(self, message: Dict[str, str]):
        self.es.index(index=self.index_name, body={
            'type': 'message',
            'content': message['content'],
            'role': message.get('role', 'user')
        })

    def search(self, query: Union[str, List[str]], k: int = 5, case_sensitive: bool = False, search_files: bool = True) -> List[Dict[str, str]]:
        if isinstance(query, str):
            query = [query]
        
        should_clauses = []
        for q in query:
            should_clauses.append({
                'match': {
                    'content': {
                        'query': q,
                        'operator': 'and',
                        'fuzziness': 'AUTO'
                    }
                }
            })
        
        body = {
            'query': {
                'bool': {
                    'should': should_clauses,
                    'minimum_should_match': 1
                }
            },
            'size': k
        }

        if not search_files:
            body['query']['bool']['must'] = [{'term': {'type': 'message'}}]

        if not case_sensitive:
            body['query']['bool']['should'] = [{'match': {'content': {'query': q, 'analyzer': 'standard'}}} for q in query]

        results = self.es.search(index=self.index_name, body=body)
        
        formatted_results = []
        for hit in results['hits']['hits']:
            source = hit['_source']
            if source['type'] == 'file':
                formatted_results.append({
                    'type': 'file',
                    'path': source['path'],
                    'content': source['content'][:500] + '...' if len(source['content']) > 500 else source['content']
                })
            else:
                formatted_results.append({
                    'type': 'message',
                    'content': source['content'],
                    'role': source.get('role', 'user')
                })
        
        return formatted_results

    def update_index(self):
        self.es.indices.delete(index=self.index_name, ignore=[404])
        self.es.indices.create(index=self.index_name)
        self.index_files()