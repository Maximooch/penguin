import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

// Get the absolute path to the workspace directory
const workspacePath = path.resolve(__dirname, '../../workspace')
console.log('Workspace path:', workspacePath)

export default defineConfig({
  plugins: [react()],
  server: {
    fs: {
      strict: false,
      allow: ['..', workspacePath]
    },
    // Use the proxy configuration instead of middleware
    proxy: {
      '/api/conversations': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        configure: (proxy, options) => {
          proxy.on('error', (err, req, res) => {
            console.error('Proxy error:', err);
            // Handle proxy errors by serving local files
            if (req.url === '/api/conversations') {
              try {
                const conversationsDir = path.join(workspacePath, 'conversations')
                console.log('Falling back to local conversations in:', conversationsDir)
                
                if (!fs.existsSync(conversationsDir)) {
                  console.error('Conversations directory not found:', conversationsDir)
                  res.writeHead(404, { 'Content-Type': 'application/json' })
                  return res.end(JSON.stringify({ 
                    error: 'Conversations directory not found',
                    path: conversationsDir
                  }))
                }

                const files = fs.readdirSync(conversationsDir)
                  .filter(file => file.endsWith('.json'))
                
                const conversations = files.map(file => {
                  try {
                    const content = fs.readFileSync(
                      path.join(conversationsDir, file), 
                      'utf-8'
                    )
                    return JSON.parse(content)
                  } catch (parseError) {
                    console.warn(`Failed to parse conversation file ${file}:`, parseError)
                    return null
                  }
                }).filter(Boolean)

                res.writeHead(200, {
                  'Content-Type': 'application/json',
                  'Access-Control-Allow-Origin': '*'
                })
                return res.end(JSON.stringify(conversations))
              } catch (error) {
                console.error('Error serving conversations:', error)
                res.writeHead(500, { 'Content-Type': 'application/json' })
                return res.end(JSON.stringify({ 
                  error: 'Failed to load conversations',
                  details: error.message
                }))
              }
            }
          })
        }
      }
    }
  }
})