import React, { useState, useRef, useEffect } from 'react';
import Avatar from './components/Avatar';
import './App.css';
import MessageParser from './utils/messageParser';
import TextareaAutosize from 'react-textarea-autosize';
import penguinAvatar from './assets/penguin-avatar.png'; // Add your penguin avatar image
import userAvatar from './assets/user-avatar.jpg'; // Add your user avatar image
import ThreadSidebar from './components/ThreadSidebar';

function autoResizeTextArea(element) {
  element.style.height = 'inherit';
  element.style.height = `${Math.min(element.scrollHeight, 200)}px`; // Cap at 200px
}

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);
  const ws = useRef(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 3;
  const [activeThread, setActiveThread] = useState(null);
  const [sessionId, setSessionId] = useState(null);

  const createNewConversation = async () => {
    try {
      const response = await fetch('/api/conversations/new', {
        method: 'POST'
      });
      const data = await response.json();
      return data.session_id;
    } catch (error) {
      console.error('Error creating conversation:', error);
      return null;
    }
  };

  const connectWebSocket = async (sid = null) => {
    try {
      setIsConnecting(true);
      
      // Create new conversation if no session ID provided
      const session_id = sid || await createNewConversation();
      if (!session_id) throw new Error('Failed to get session ID');
      
      setSessionId(session_id);
      ws.current = new WebSocket(`ws://localhost:8000/ws/${session_id}`);
      
      ws.current.onmessage = (event) => {
        console.log('WebSocket message received:', event.data);
        try {
          const response = JSON.parse(event.data);
          addMessage('assistant', response.response);
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
          addMessage('assistant', 'Sorry, I encountered an error processing that message.');
        }
      };

      ws.current.onerror = (error) => {
        console.error('WebSocket error:', error);
      };

      ws.current.onopen = () => {
        console.log('WebSocket connected');
        setIsConnecting(false);
        reconnectAttempts.current = 0;
        addMessage('assistant', 'Hello! How can I help you today?');
      };

      ws.current.onclose = () => {
        console.log('WebSocket disconnected');
        if (reconnectAttempts.current < maxReconnectAttempts) {
          console.log(`Attempting to reconnect... (${reconnectAttempts.current + 1}/${maxReconnectAttempts})`);
          reconnectAttempts.current += 1;
          setTimeout(connectWebSocket, 2000); // Try to reconnect after 2 seconds
        } else {
          setIsConnecting(false);
          addMessage('assistant', 'Connection lost. Please refresh the page to try again.');
        }
      };

    } catch (error) {
      console.error('Error setting up WebSocket:', error);
      setIsConnecting(false);
      addMessage('assistant', 'Failed to establish connection. Please try again.');
    }
  };

  useEffect(() => {
    connectWebSocket();
    return () => {
      if (ws.current) {
        ws.current.close();
      }
    };
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(scrollToBottom, [messages]);

  const addMessage = (sender, text) => {
    setMessages(prev => [...prev, { 
      sender, 
      text, 
      timestamp: new Date(),
      // Add Discord-like metadata
      isBot: sender === 'assistant',
      username: sender === 'assistant' ? 'Penguin' : 'You'
    }]);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim()) {
      addMessage('user', input);
      if (ws.current?.readyState === WebSocket.OPEN) {
        ws.current.send(JSON.stringify({ text: input }));
      }
      setInput('');
    }
  };

  const handleThreadSelect = async (thread) => {
    // Close existing connection if any
    if (ws.current) {
      ws.current.close();
    }
    
    setActiveThread(thread);
    
    // Connect to WebSocket with thread's session ID
    await connectWebSocket(thread.session_id);
    
    // Load messages from the selected thread
    if (thread && thread.messages) {
      const formattedMessages = thread.messages.map(msg => ({
        sender: msg.role === 'assistant' ? 'assistant' : 'user',
        text: msg.content[0].text,
        timestamp: new Date(msg.timestamp),
        isBot: msg.role === 'assistant',
        username: msg.role === 'assistant' ? 'Penguin' : 'You'
      }));
      setMessages(formattedMessages);
    }
  };

  return (
    <div className="app">
      <ThreadSidebar 
        onThreadSelect={handleThreadSelect}
        activeThreadId={activeThread?.session_id}
        onNewThread={() => {
          // Close existing connection
          if (ws.current) {
            ws.current.close();
          }
          // Start new conversation
          connectWebSocket();
          setMessages([]);
          setActiveThread(null);
        }}
      />
      <div className="main-content">
        <div className="chat-container">
          <div className="messages">
            {messages.map((message, index) => (
              <MessageCard 
                key={index} 
                message={message} 
                showAvatar={shouldShowAvatar(messages, index)}
              />
            ))}
            <div ref={messagesEndRef} />
          </div>
          <form className="input-form" onSubmit={handleSubmit}>
            <TextareaAutosize
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
              placeholder="Message Penguin..."
              minRows={1}
              maxRows={5}
              className="chat-input"
              style={{ resize: 'none' }}
            />
            <button type="submit">Send</button>
          </form>
        </div>
      </div>
    </div>
  );
}

// Helper function to determine if avatar should be shown
function shouldShowAvatar(messages, index) {
  if (index === 0) return true;
  const currentMessage = messages[index];
  const prevMessage = messages[index - 1];
  
  // Show avatar if first message or different sender from previous
  return prevMessage.sender !== currentMessage.sender;
}

function MessageCard({ message, showAvatar }) {
  return (
    <div className={`message ${message.sender}-message`}>
      {showAvatar && (
        <div className="message-header">
          <Avatar 
            type="message"
            isBot={message.isBot}
            imageUrl={message.isBot ? penguinAvatar : userAvatar}
          />
          <div className="message-meta">
            <span className="sender-name">
              {message.username}
            </span>
            <span className="timestamp">
              {new Date(message.timestamp).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit'
              })}
            </span>
          </div>
        </div>
      )}
      <div className={`message-content ${!showAvatar ? 'no-avatar' : ''}`}>
        {formatMessage(message.text)}
      </div>
    </div>
  );
}

function formatMessage(text) {
  const parsed = MessageParser.parseResponse(text);
  
  return (
    <div className="message-blocks">
      {/* Handle execute blocks */}
      {parsed.executeBlocks.map((block, i) => (
        <div key={`execute-${i}`} className="execute-block">
          <div className="execute-header">
            <span className="execute-icon">▶</span>
            <span className="execute-label">execute</span>
          </div>
          <pre className="execute-content">
            <code>{block.content}</code>
          </pre>
        </div>
      ))}

      {/* Handle markdown code blocks */}
      {parsed.codeBlocks.map((block, i) => (
        <div key={`code-${i}`} className="code-block">
          {block.language && (
            <div className="language-badge">{block.language}</div>
          )}
          <pre>
            <code>{block.content}</code>
          </pre>
        </div>
      ))}

      {/* Handle tool results */}
      {parsed.toolResults.map((result, i) => (
        <div key={`tool-${i}`} className="tool-result">
          {result.trim()}
        </div>
      ))}

      {/* Handle plain text */}
      {parsed.plainText && parsed.plainText.split('\n').map((line, i) => {
        if (!line.trim()) return null;
        const parts = line.split(/(`[^`]+`)/g);
        return (
          <p key={`text-${i}`} className="text-line">
            {parts.map((part, j) => {
              if (part.startsWith('`') && part.endsWith('`')) {
                return <code key={j}>{part.slice(1, -1)}</code>;
              }
              return part;
            })}
          </p>
        );
      })}
    </div>
  );
}

export default App;
