import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';

function ThreadSidebar({ onThreadSelect, activeThreadId, onNewThread }) {
  const [threads, setThreads] = useState([]);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const loadThreads = async () => {
      try {
        console.log('Loading conversations from API...');
        setIsLoading(true);
        
        const response = await fetch('/api/conversations');
        console.log('Response status:', response.status);
        
        // Try to read the response as text first
        const text = await response.text();
        console.log('Raw response:', text);

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}, body: ${text}`);
        }
        
        // Then parse the text as JSON
        let data;
        try {
          data = JSON.parse(text);
        } catch (parseError) {
          console.error('Failed to parse JSON:', parseError);
          throw new Error(`Invalid JSON response: ${text.substring(0, 100)}...`);
        }

        console.log('Parsed conversations:', data);

        if (!Array.isArray(data)) {
          console.error('Expected array of conversations, got:', typeof data, data);
          setError('Invalid data format received');
          return;
        }

        const loadedThreads = data
          .filter(conversation => {
            if (!conversation || !conversation.metadata) {
              console.warn('Invalid conversation format:', conversation);
              return false;
            }
            return true;
          })
          .map(conversation => ({
            session_id: conversation.metadata.session_id,
            title: conversation.metadata.title || 'Untitled',
            fullTitle: conversation.metadata.title || 'Untitled',
            last_active: new Date(conversation.metadata.last_active),
            formattedDate: formatTimestamp(new Date(conversation.metadata.last_active)),
            message_count: conversation.messages?.length || 0,
            messages: conversation.messages,
            preview: getMessagePreview(conversation.messages)
          }));

        console.log('Processed threads:', loadedThreads);

        // Sort threads by last_active timestamp (most recent first)
        loadedThreads.sort((a, b) => b.last_active - a.last_active);
        setThreads(loadedThreads);
        setError(null);
      } catch (error) {
        console.error('Error loading conversations:', error);
        setError(`Failed to load conversations: ${error.message}`);
      } finally {
        setIsLoading(false);
      }
    };

    loadThreads();
  }, []);

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <button 
          className="new-thread-button"
          onClick={onNewThread}
        >
          New Conversation
        </button>
      </div>
      <div className="thread-list">
        {threads.length === 0 ? (
          <div className="empty-state">No conversations yet</div>
        ) : (
          threads.map((thread) => (
            <div
              key={thread.session_id}
              className={`thread-item ${thread.session_id === activeThreadId ? 'active' : ''}`}
              onClick={() => onThreadSelect(thread)}
              title={thread.fullTitle}
            >
              <div className="thread-title">{thread.title}</div>
              <div className="thread-preview">{thread.preview}</div>
              <div className="thread-meta">
                <span className="thread-date">{thread.formattedDate}</span>
                <span className="thread-messages">{thread.message_count} messages</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// Helper function to format timestamps
function formatTimestamp(date) {
  const now = new Date();
  const diff = now - date;
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));

  if (days === 0) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } else if (days === 1) {
    return 'Yesterday';
  } else if (days < 7) {
    return date.toLocaleDateString([], { weekday: 'long' });
  } else {
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }
}

// Helper function to get message preview
function getMessagePreview(messages) {
  if (!messages || messages.length === 0) return '';
  const lastMessage = messages[messages.length - 1];
  const text = lastMessage.content[0]?.text || '';
  return text.length > 40 ? text.substring(0, 37) + '...' : text;
}

ThreadSidebar.propTypes = {
  onThreadSelect: PropTypes.func.isRequired,
  activeThreadId: PropTypes.string,
  onNewThread: PropTypes.func.isRequired
};

export default ThreadSidebar; 