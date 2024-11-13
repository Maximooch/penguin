import graphviz
from typing import Dict, List, Optional

class ModernCogArchVisualizer:
    def __init__(self):
        self.dot = graphviz.Digraph(comment='Penguin v1 Cognitive Architecture')
        self.dot.attr(rankdir='TB')
        self.setup_modern_styling()
        
    def setup_modern_styling(self):
        # Modern dark theme
        self.dot.attr('graph', 
                     bgcolor='#1a1a1a',
                     fontname='Helvetica',
                     fontcolor='#ffffff',
                     pad='0.5')
        
        self.dot.attr('node',
                     shape='box',
                     style='rounded,filled',
                     fontname='Helvetica',
                     fontcolor='#ffffff',
                     color='#2a2a2a',
                     penwidth='2')
        
        self.dot.attr('edge',
                     fontname='Helvetica',
                     fontcolor='#ffffff',
                     color='#4a4a4a',
                     penwidth='1.5')
    
    def create_cluster(self, name: str, label: str, nodes: List[Dict]):
        with self.dot.subgraph(name=f'cluster_{name}') as c:
            c.attr(label=label,
                  style='rounded',
                  color='#3a3a3a',
                  bgcolor='#2a2a2a',
                  fontcolor='#ffffff',
                  penwidth='2')
            
            for node in nodes:
                c.node(node['id'],
                      node['label'],
                      fillcolor=node.get('color', '#2a2a2a'),
                      gradientangle='315')

    def add_connections(self, connections: List[Dict]):
        for conn in connections:
            self.dot.edge(
                conn['from'],
                conn['to'],
                color=conn.get('color', '#4a4a4a'),
                style=conn.get('style', 'solid'),
                penwidth='2',
                arrowhead='vee'
            )

    def generate_modern_cogarch(self):
        colors = {
            'llm': '#1e88e5',          # Modern blue
            'memory': '#7cb342',        # Light green
            'cognition': '#00897b',     # Teal
            'processor': '#e53935',     # Red
            'system': '#8e24aa',        # Purple
            'workspace': '#ff8f00',     # Orange
            'link': '#546e7a'          # Blue grey
        }
        
        # Core LLM
        self.dot.node('llm', 'Single LLM\nInterface',
                     shape='doubleoctagon',
                     fillcolor=colors['llm'],
                     style='filled')
        
        # Memory System
        memory_nodes = [
            {'id': 'memory_search', 'label': 'Memory Search', 'color': colors['memory']},
            {'id': 'workspace_search', 'label': 'Workspace Search', 'color': colors['memory']},
            {'id': 'context_window', 'label': 'Context Window\nManager', 'color': colors['memory']},
            {'id': 'contextual_awareness', 'label': 'Contextual\nAwareness', 'color': colors['memory']}
        ]
        self.create_cluster('memory', 'Memory System', memory_nodes)
        
        # Cognition System
        cognition_nodes = [
            {'id': 'reasoning', 'label': 'Reasoning', 'color': colors['cognition']},
            {'id': 'entropix', 'label': 'Entropix', 'color': colors['cognition']}
        ]
        self.create_cluster('cognition', 'Cognition System', cognition_nodes)
        
        # Processor System
        processor_nodes = [
            {'id': 'parser', 'label': 'Parser', 'color': colors['processor']},
            {'id': 'tools', 'label': 'Tools', 'color': colors['processor']},
            {'id': 'utils', 'label': 'Utils', 'color': colors['processor']}
        ]
        self.create_cluster('processor', 'Processor System', processor_nodes)
        
        # System Components
        system_nodes = [
            {'id': 'server', 'label': 'Server', 'color': colors['system']},
            {'id': 'thought_message', 'label': 'Thought/Message\nSystem', 'color': colors['system']},
            {'id': 'conversation', 'label': 'Conversation\nHandler', 'color': colors['system']},
            {'id': 'logging', 'label': 'Logging', 'color': colors['system']}
        ]
        self.create_cluster('system', 'System', system_nodes)
        
        # Workspace System
        self.dot.node('workspace', 'Workspace\nSystem',
                     shape='component',
                     fillcolor=colors['workspace'],
                     style='filled')
        
        # Link System
        link_nodes = [
            {'id': 'task_db', 'label': 'Task Database', 'color': colors['link']},
            {'id': 'link_api', 'label': 'Link API', 'color': colors['link']}
        ]
        self.create_cluster('link', 'Link System', link_nodes)
        
        # Add connections
        connections = [
            # Memory system connections
            {'from': 'context_window', 'to': 'llm', 'color': colors['memory']},
            {'from': 'memory_search', 'to': 'workspace_search', 'color': colors['memory']},
            {'from': 'contextual_awareness', 'to': 'llm', 'color': colors['memory']},
            
            # Processor connections
            {'from': 'parser', 'to': 'tools', 'color': colors['processor']},
            {'from': 'tools', 'to': 'utils', 'color': colors['processor']},
            
            # System connections
            {'from': 'server', 'to': 'thought_message', 'color': colors['system']},
            {'from': 'conversation', 'to': 'logging', 'color': colors['system']},
            
            # Workspace integration
            {'from': 'workspace', 'to': 'workspace_search', 'color': colors['workspace']},
            {'from': 'workspace', 'to': 'server', 'color': colors['workspace']},
            
            # Link integration
            {'from': 'link_api', 'to': 'task_db', 'color': colors['link']},
            {'from': 'link_api', 'to': 'server', 'color': colors['link']},
            
            # LLM connections
            {'from': 'llm', 'to': 'reasoning', 'color': colors['llm']},
            {'from': 'llm', 'to': 'parser', 'color': colors['llm']},
            {'from': 'llm', 'to': 'conversation', 'color': colors['llm']}
        ]
        
        self.add_connections(connections)
    
    def save(self, filename: str = 'penguin_cogarch_v1'):
        self.dot.render(filename, view=True, format='png')

if __name__ == "__main__":
    visualizer = ModernCogArchVisualizer()
    visualizer.generate_modern_cogarch()
    visualizer.save()