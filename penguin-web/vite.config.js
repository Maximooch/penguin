import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true, // Enable WebSocket proxy
        configure: (proxy, options) => {
          // Error handling for proxy
          proxy.on('error', (err, req, res) => {
            console.error('Proxy error:', err);
            
            // Handle conversations endpoint specifically
            if (req.url === '/api/conversations') {
              const workspacePath = path.resolve(__dirname, '../../workspace')
              const conversationsDir = path.join(workspacePath, 'conversations')
              
              try {
                if (!fs.existsSync(conversationsDir)) {
                  fs.mkdirSync(conversationsDir, { recursive: true })
                }

                const files = fs.readdirSync(conversationsDir)
                  .filter(file => file.endsWith('.json'))
                
                const conversations = files.map(file => {
                  const filePath = path.join(conversationsDir, file)
                  const content = fs.readFileSync(filePath, 'utf-8')
                  const data = JSON.parse(content)
                  return {
                    metadata: {
                      session_id: path.basename(file, '.json'),
                      title: data.title || 'Untitled Conversation',
                      last_active: data.last_active || new Date().toISOString(),
                      message_count: data.messages?.length || 0
                    },
                    messages: data.messages || []
                  }
                }).filter(Boolean)

                res.writeHead(200, {
                  'Content-Type': 'application/json',
                  'Access-Control-Allow-Origin': '*'
                })
                res.end(JSON.stringify(conversations))
              } catch (error) {
                console.error('Error serving conversations:', error)
                res.writeHead(500).end()
              }
            }
          })
        }
      }
    }
  }
})